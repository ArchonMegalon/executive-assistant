#!/usr/bin/env python3
from __future__ import annotations

import io
import hashlib
import json
import math
import os
import re
import struct
import stat
import sys
import time
import unicodedata
import wave
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import HTTPException

REPO_ROOT = Path(__file__).resolve().parents[1]
EA_APP_ROOT = REPO_ROOT / "ea"
if str(EA_APP_ROOT) not in sys.path:
    sys.path.insert(0, str(EA_APP_ROOT))

try:
    from scripts.source_state_head import resolve_source_state_head
    from scripts.source_state_head import resolve_source_worktree_fingerprint
except ModuleNotFoundError:  # pragma: no cover - script execution path
    from source_state_head import resolve_source_state_head
    from source_state_head import resolve_source_worktree_fingerprint

try:
    from scripts.materialize_memorial_stt_fixture_candidate import (
        APPROVED_ALLOWED_PURPOSE,
        APPROVED_ACCENT,
        APPROVED_CAPTURE_ORIGIN,
        APPROVED_LANGUAGE,
        APPROVED_RETENTION_VALUES,
        APPROVED_SPEAKER_CONSENT,
        CANONICALIZATION,
        CANDIDATE_BINDING_CONTRACT,
        CANDIDATE_CONTRACT_VERSION,
        DEFAULT_MAX_AUDIO_DURATION_SECONDS,
        GROUND_TRUTH_REVIEW_BINDING_CONTRACT,
        PROVIDER_UPLOAD_LANES,
        RESERVED_CANDIDATE_SAMPLES,
        SAFE_CANDIDATE_SAMPLE_PATTERN,
        SAFE_BUNDLE_ID_PATTERN,
        SAFE_FIXTURE_FILE_PATTERN,
        _canonical_sha256,
        _abort_atomic_json_output,
        _commit_atomic_json_output,
        _load_input_wav,
        _load_private_ground_truth_review,
        _normalized_review,
        _required_token_contract_failures,
        _review_freshness_failures,
        _review_binding_payload,
        _prepare_atomic_json_output,
        _safe_atomic_output_preflight_failure_code,
        _validate_raw_review_schema,
        _validate_review,
    )
except ModuleNotFoundError:  # pragma: no cover - script execution path
    from materialize_memorial_stt_fixture_candidate import (
        APPROVED_ALLOWED_PURPOSE,
        APPROVED_ACCENT,
        APPROVED_CAPTURE_ORIGIN,
        APPROVED_LANGUAGE,
        APPROVED_RETENTION_VALUES,
        APPROVED_SPEAKER_CONSENT,
        CANONICALIZATION,
        CANDIDATE_BINDING_CONTRACT,
        CANDIDATE_CONTRACT_VERSION,
        DEFAULT_MAX_AUDIO_DURATION_SECONDS,
        GROUND_TRUTH_REVIEW_BINDING_CONTRACT,
        PROVIDER_UPLOAD_LANES,
        RESERVED_CANDIDATE_SAMPLES,
        SAFE_CANDIDATE_SAMPLE_PATTERN,
        SAFE_BUNDLE_ID_PATTERN,
        SAFE_FIXTURE_FILE_PATTERN,
        _canonical_sha256,
        _abort_atomic_json_output,
        _commit_atomic_json_output,
        _load_input_wav,
        _load_private_ground_truth_review,
        _normalized_review,
        _required_token_contract_failures,
        _review_freshness_failures,
        _review_binding_payload,
        _prepare_atomic_json_output,
        _safe_atomic_output_preflight_failure_code,
        _validate_raw_review_schema,
        _validate_review,
    )

try:
    from app.api.routes import public_memorials
except Exception:
    class _PublicMemorialFallback:
        _CARTESIA_DEFAULT_CREDENTIAL_FILES: tuple[str, ...] = ()
        _CARTESIA_DIRECT_KEY_ENV_NAMES = ("CARTESIA_API_KEY", "EA_CARTESIA_API_KEY")
        _CARTESIA_INLINE_CREDENTIAL_ENV_NAMES = ("EA_CARTESIA_CREDENTIALS_JSON",)
        _CARTESIA_CREDENTIAL_FILE_ENV_NAMES = ("EA_CARTESIA_CREDENTIAL_FILE",)

        @staticmethod
        def _text(value: object, default: str = "") -> str:
            text = str(value or "").strip()
            return text if text else default

        @staticmethod
        def _cartesia_credential_path_candidates(raw_path: object) -> tuple[Path, ...]:
            text = str(raw_path or "").strip()
            return (Path(text).expanduser(),) if text else ()

        @staticmethod
        def _load_cartesia_credential_file(raw_path: object) -> str:
            path = Path(str(raw_path or "")).expanduser()
            return path.read_text(encoding="utf-8") if path.is_file() else ""

        @staticmethod
        def _cartesia_api_key_from_payload(payload: object) -> str:
            text = str(payload or "").strip()
            if not text:
                return ""
            try:
                parsed = json.loads(text)
            except Exception:
                return text
            if isinstance(parsed, dict):
                return str(parsed.get("api_key") or parsed.get("key") or "").strip()
            return ""

        @classmethod
        def _memorial_cartesia_api_key(cls) -> str:
            for name in cls._CARTESIA_DIRECT_KEY_ENV_NAMES:
                key = cls._cartesia_api_key_from_payload(os.getenv(name))
                if key:
                    return key
            for name in cls._CARTESIA_INLINE_CREDENTIAL_ENV_NAMES:
                key = cls._cartesia_api_key_from_payload(os.getenv(name))
                if key:
                    return key
            for name in cls._CARTESIA_CREDENTIAL_FILE_ENV_NAMES:
                path = os.getenv(name)
                if not path:
                    continue
                key = cls._cartesia_api_key_from_payload(cls._load_cartesia_credential_file(path))
                if key:
                    return key
            for path in cls._CARTESIA_DEFAULT_CREDENTIAL_FILES:
                key = cls._cartesia_api_key_from_payload(cls._load_cartesia_credential_file(path))
                if key:
                    return key
            return ""

        @staticmethod
        def _repair_memorial_transcript_text(value: object) -> str:
            return " ".join(str(value or "").split()).strip()

        @staticmethod
        def _is_known_bad_memorial_subtitle_transcript(value: object) -> bool:
            normalized = str(value or "").casefold()
            return "amara.org" in normalized or "untertitel" in normalized

        @staticmethod
        def _memorial_shadow_stt_result(**_kwargs: object) -> dict[str, object]:
            return {"transcript_text": "", "transcription_status": "unavailable"}

        @staticmethod
        def _memorial_onemin_available_keys(candidate_keys: tuple[str, ...]) -> tuple[str, ...]:
            return tuple(candidate_keys)

        @staticmethod
        def _memorial_onemin_max_key_attempts() -> int:
            raw = str(os.getenv("EA_MEMORIAL_ONEMIN_MAX_KEY_ATTEMPTS") or "3").strip()
            try:
                value = int(raw)
            except ValueError:
                return 3
            return value if value > 0 else 3

        @staticmethod
        def _memorial_transcribe_audio_blob(**_kwargs: object) -> dict[str, object]:
            return {"transcription_status": "unavailable", "transcript_text": "", "transcriber": "fallback"}

    public_memorials = _PublicMemorialFallback()

try:
    from app.product import service as product_service
except Exception:
    class _ProductServiceFallback:
        @staticmethod
        def _extract_transcript_text(value: object) -> str:
            if isinstance(value, str):
                return value
            if isinstance(value, dict):
                for key in ("text", "transcript", "transcript_text", "content"):
                    text = _ProductServiceFallback._extract_transcript_text(value.get(key))
                    if text:
                        return text
            if isinstance(value, list):
                for item in value:
                    text = _ProductServiceFallback._extract_transcript_text(item)
                    if text:
                        return text
            return ""

        @staticmethod
        def _pocket_onemin_api_keys() -> tuple[str, ...]:
            return tuple(key.strip() for key in str(os.getenv("ONEMIN_AI_API_KEY") or "").split(",") if key.strip())

        @staticmethod
        def _onemin_asset_upload(**_kwargs: object) -> dict[str, object]:
            return {}

        @staticmethod
        def _onemin_speech_to_text(**_kwargs: object) -> dict[str, object]:
            return {}

    product_service = _ProductServiceFallback()


def _fallback_extract_transcript_text(value: object) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        for key in ("text", "transcript", "transcript_text", "content"):
            text = _fallback_extract_transcript_text(value.get(key))
            if text:
                return text
    if isinstance(value, list):
        for item in value:
            text = _fallback_extract_transcript_text(item)
            if text:
                return text
    return ""


if not hasattr(product_service, "_extract_transcript_text"):
    product_service._extract_transcript_text = _fallback_extract_transcript_text  # type: ignore[attr-defined]
if not hasattr(product_service, "_pocket_onemin_api_keys"):
    product_service._pocket_onemin_api_keys = lambda: tuple(  # type: ignore[attr-defined]
        key.strip() for key in str(os.getenv("ONEMIN_AI_API_KEY") or "").split(",") if key.strip()
    )
if not hasattr(product_service, "_onemin_asset_upload"):
    product_service._onemin_asset_upload = lambda **_kwargs: {}  # type: ignore[attr-defined]
if not hasattr(product_service, "_onemin_speech_to_text"):
    product_service._onemin_speech_to_text = lambda **_kwargs: {}  # type: ignore[attr-defined]


FIXTURE_ROOT = Path(os.environ.get("EA_MEMORIAL_STT_FIXTURE_ROOT") or REPO_ROOT / "tests" / "fixtures" / "memorial")
FIXTURE_MANIFEST = FIXTURE_ROOT / "stt_fixture_manifest.json"
DEFAULT_OUTPUT = REPO_ROOT / ".codex-studio/published/memorial_stt_provider_benchmark.generated.json"
FULL_TEXT_MODES = {"full", "raw", "operator_full"}
DEFAULT_PROVIDER_ENV_FILES = (REPO_ROOT / ".env", REPO_ROOT / ".env.local")
DEFAULT_STT_ERROR_LOG_ROOT = Path(
    os.environ.get("EA_MEMORIAL_STT_ERROR_LOG_ROOT")
    or REPO_ROOT / ".codex-studio" / "published" / "memorial_stt_errors"
)
DEFAULT_MAX_EXTERNAL_CANDIDATE_BYTES = 25 * 1024 * 1024
DEFAULT_MAX_CANDIDATE_RECEIPT_BYTES = 512 * 1024
TRANSFORMATION_RECEIPT_CONTRACT = "ea.memorial_stt_audio_transformation_receipt.v1"
PROVIDER_ERROR_DETAIL_CONTRACT = "ea.memorial_stt_provider_error_detail.v1"
SUCCESSFUL_PROVIDER_STATUSES = frozenset({"ok", "success", "transcribed"})
SAFE_PROVIDER_STATUS_CODES = SUCCESSFUL_PROVIDER_STATUSES | frozenset(
    {
        "empty",
        "error",
        "fixture_invalid",
        "http_error",
        "known_bad",
        "not_authorized",
        "unavailable",
        "unknown",
    }
)
DEFAULT_PROVIDER_UPLOAD_AUTHORIZATION = {
    "full_runtime": True,
    "shadow": True,
    "onemin_sample": True,
}


def _load_fixture_manifest(path: Path = FIXTURE_MANIFEST) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("contract_name") != "ea.memorial_stt_fixture_manifest":
        raise RuntimeError("invalid_stt_fixture_manifest_contract")
    return payload


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _sha256_text(value: str) -> str:
    return hashlib.sha256(str(value or "").encode("utf-8")).hexdigest()


def _benchmark_text_mode(value: str | None = None) -> str:
    requested = str(value or os.environ.get("EA_MEMORIAL_STT_BENCHMARK_TEXT_MODE") or "redacted").strip().lower()
    return "full" if requested in FULL_TEXT_MODES else "redacted"


def _parse_env_value(raw: str) -> str:
    value = str(raw or "").strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def _load_provider_env_files(paths: tuple[Path, ...]) -> dict[str, object]:
    loaded_file_count = 0
    loaded_names: list[str] = []
    for path in paths:
        try:
            candidate = path if path.is_absolute() else REPO_ROOT / path
        except Exception:
            continue
        if not candidate.exists():
            continue
        loaded_file_count += 1
        try:
            lines = candidate.read_text(encoding="utf-8").splitlines()
        except Exception:
            continue
        for raw_line in lines:
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            if line.startswith("export "):
                line = line.removeprefix("export ").strip()
            name, raw_value = line.split("=", 1)
            name = name.strip()
            if not re.fullmatch(r"[A-Z_][A-Z0-9_]*", name):
                continue
            if os.environ.get(name):
                continue
            value = _parse_env_value(raw_value)
            if not value:
                continue
            os.environ[name] = value
            loaded_names.append(name)
    return {
        "file_count": loaded_file_count,
        "loaded_names": sorted(set(loaded_names)),
        "loaded_count": len(set(loaded_names)),
    }


def _provider_env_receipt_summary(
    report: dict[str, object],
    *,
    cartesia_probe: dict[str, object] | None = None,
) -> dict[str, object]:
    names = {str(name or "").strip() for name in list(report.get("loaded_names") or [])}
    cartesia = dict(cartesia_probe or {})
    return {
        "file_count": _safe_nonnegative_int(report.get("file_count"))
        or len(list(report.get("files") or [])),
        "loaded_count": int(report.get("loaded_count") or 0),
        "provider_families": {
            "cartesia": any("CARTESIA" in name for name in names) or bool(cartesia.get("configured")),
            "onemin": any("ONEMIN" in name for name in names),
            "blipai_shadow": any(name.startswith("BLIPAI_") for name in names),
        },
    }


def _display_path(path: Path) -> str:
    try:
        return path.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return "[external_path]"


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _cartesia_default_credential_file_present() -> bool:
    for raw_path in getattr(public_memorials, "_CARTESIA_DEFAULT_CREDENTIAL_FILES", ()):
        try:
            candidates = public_memorials._cartesia_credential_path_candidates(raw_path)  # noqa: SLF001
        except Exception:
            candidates = ()
        if any(candidate.is_file() for candidate in candidates):
            return True
    return False


def _cartesia_credential_probe() -> dict[str, object]:
    direct_env = any(
        bool(public_memorials._cartesia_api_key_from_payload(os.getenv(name)))  # noqa: SLF001
        for name in getattr(public_memorials, "_CARTESIA_DIRECT_KEY_ENV_NAMES", ())
    )
    inline_json_env = any(
        bool(public_memorials._cartesia_api_key_from_payload(os.getenv(name)))  # noqa: SLF001
        for name in getattr(public_memorials, "_CARTESIA_INLINE_CREDENTIAL_ENV_NAMES", ())
    )
    credential_file_env = any(
        bool(
            public_memorials._cartesia_api_key_from_payload(  # noqa: SLF001
                public_memorials._load_cartesia_credential_file(os.getenv(name))  # noqa: SLF001
            )
        )
        for name in getattr(public_memorials, "_CARTESIA_CREDENTIAL_FILE_ENV_NAMES", ())
    )
    default_files: list[dict[str, object]] = []
    default_file_key_present = False
    for slot, raw_path in enumerate(getattr(public_memorials, "_CARTESIA_DEFAULT_CREDENTIAL_FILES", ())):
        try:
            candidates = public_memorials._cartesia_credential_path_candidates(raw_path)  # noqa: SLF001
        except Exception:
            candidates = ()
        present = any(candidate.is_file() for candidate in candidates)
        contains_key = bool(
            public_memorials._cartesia_api_key_from_payload(  # noqa: SLF001
                public_memorials._load_cartesia_credential_file(raw_path)  # noqa: SLF001
            )
        )
        default_file_key_present = default_file_key_present or contains_key
        default_files.append(
            {
                "slot": slot,
                "present": present,
                "contains_key": contains_key,
            }
        )
    configured = bool(public_memorials._memorial_cartesia_api_key()) or default_file_key_present
    source = "none"
    if direct_env:
        source = "direct_env"
    elif inline_json_env:
        source = "inline_json_env"
    elif credential_file_env:
        source = "credential_file_env"
    elif default_file_key_present:
        source = "default_credential_file"
    return {
        "configured": configured,
        "credential_source": source,
        "accepted_source_types": [
            "direct_env",
            "inline_json_env",
            "credential_file_env",
            "default_credential_file",
        ],
        "default_credential_files": default_files,
        "operator_hint": ""
        if configured
        else "Configure Cartesia with a governed credential source.",
    }


def _sanitize_provider_error_detail(value: object) -> object:
    if isinstance(value, dict) and value.get("contract_name") == PROVIDER_ERROR_DETAIL_CONTRACT:
        allowed_categories = {"http_error", "insufficient_credits", "provider_error", "timeout"}
        category = str(value.get("category") or "")
        code = str(value.get("code") or "")
        digest = str(value.get("detail_sha256") or "").lower()
        safe_code = (
            code
            if code in {"provider_error", "provider_http_error", "provider_timeout", "onemin_http_error"}
            or re.fullmatch(r"(?:onemin|cartesia|blipai|memorial)_[a-z_]+_http_\d+", code)
            else "provider_error"
        )
        if not re.fullmatch(r"[a-f0-9]{64}", digest):
            try:
                digest = _canonical_sha256(value)
            except (TypeError, ValueError, OverflowError):
                digest = _sha256_text("invalid_provider_error_detail")
        return {
            "contract_name": PROVIDER_ERROR_DETAIL_CONTRACT,
            "category": category if category in allowed_categories else "provider_error",
            "code": safe_code,
            "detail_sha256": digest,
        }
    if isinstance(value, (dict, list, tuple)):
        try:
            text = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
        except (TypeError, ValueError):
            text = "non_finite_or_non_json_provider_detail"
    else:
        text = str(value or "").strip()
    if not text:
        return ""
    lowered = text.lower()
    category = "provider_error"
    code = "provider_error"
    if "insufficient_credits" in lowered:
        category = "insufficient_credits"
        status_match = re.search(r"(onemin_[a-z_]+_http_\d+)", text, flags=re.IGNORECASE)
        code = status_match.group(1).lower() if status_match else "onemin_http_error"
    elif "http" in lowered:
        category = "http_error"
        status_match = re.search(
            r"((?:onemin|cartesia|blipai|memorial)_[a-z_]+_http_\d+)",
            text,
            flags=re.IGNORECASE,
        )
        code = status_match.group(1).lower() if status_match else "provider_http_error"
    elif "timeout" in lowered:
        category = "timeout"
        code = "provider_timeout"
    return {
        "contract_name": PROVIDER_ERROR_DETAIL_CONTRACT,
        "category": category,
        "code": code,
        "detail_sha256": _sha256_text(text),
    }


def _safe_provider_status(value: object) -> str:
    status = str(value or "").strip().lower()
    return status if status in SAFE_PROVIDER_STATUS_CODES else "unknown"


def _safe_transcriber_receipt(value: object) -> dict[str, str]:
    transcriber = str(value or "").strip().lower()
    family = "unknown"
    for candidate in ("cartesia", "onemin", "blipai", "memorial"):
        if candidate in transcriber:
            family = candidate
            break
    return {
        "family": family,
        "identifier_sha256": _sha256_text(transcriber) if transcriber else "",
    }


def _pcm_wav_layout(payload: bytes) -> tuple[int, int, int]:
    if len(payload) < 44 or payload[:4] != b"RIFF" or payload[8:12] != b"WAVE":
        return 0, 0, 0
    position = 12
    byte_rate = 0
    block_align = 0
    data_start = 0
    data_size = 0
    while position + 8 <= len(payload):
        chunk_id = payload[position:position + 4]
        chunk_size = int.from_bytes(payload[position + 4:position + 8], "little", signed=False)
        chunk_payload_start = position + 8
        if chunk_id == b"fmt " and chunk_payload_start + 16 <= len(payload):
            audio_format = int.from_bytes(payload[chunk_payload_start:chunk_payload_start + 2], "little", signed=False)
            byte_rate = int.from_bytes(payload[chunk_payload_start + 8:chunk_payload_start + 12], "little", signed=False)
            block_align = int.from_bytes(payload[chunk_payload_start + 12:chunk_payload_start + 14], "little", signed=False)
            if audio_format != 1:
                return 0, 0, 0
        elif chunk_id == b"data":
            available = max(0, len(payload) - chunk_payload_start)
            data_start = chunk_payload_start
            data_size = available if chunk_size == 0xFFFFFFFF else min(chunk_size, available)
            break
        if chunk_size == 0xFFFFFFFF:
            break
        position = chunk_payload_start + chunk_size + (chunk_size % 2)
    if data_size <= 0 or byte_rate <= 0 or block_align <= 0:
        return 0, 0, 0
    usable_data_size = data_size - (data_size % block_align)
    return data_start, usable_data_size, byte_rate


def _pcm_wav_duration_from_payload(payload: bytes) -> float:
    _data_start, data_size, byte_rate = _pcm_wav_layout(payload)
    if data_size <= 0 or byte_rate <= 0:
        return 0.0
    return round(data_size / float(byte_rate), 3)


def _wav_duration_seconds(payload: bytes) -> float:
    if len(payload) < 12 or payload[:4] != b"RIFF" or payload[8:12] != b"WAVE":
        return 0.0
    try:
        with wave.open(io.BytesIO(payload), "rb") as wav_file:
            frames = int(wav_file.getnframes() or 0)
            rate = int(wav_file.getframerate() or 0)
        if frames <= 0 or rate <= 0:
            return 0.0
        duration = round(frames / float(rate), 3)
        payload_duration = _pcm_wav_duration_from_payload(payload)
        if payload_duration and duration > max(payload_duration * 2.0, payload_duration + 30.0):
            return payload_duration
        return duration
    except Exception:
        return _pcm_wav_duration_from_payload(payload)


def _pcm_wav_format(payload: bytes) -> dict[str, object]:
    if len(payload) < 12 or payload[:4] != b"RIFF" or payload[8:12] != b"WAVE":
        return {
            "audio_format": 0,
            "channels": 0,
            "sample_rate_hz": 0,
            "sample_width_bytes": 0,
        }
    position = 12
    while position + 8 <= len(payload):
        chunk_id = payload[position:position + 4]
        chunk_size = int.from_bytes(payload[position + 4:position + 8], "little", signed=False)
        chunk_payload_start = position + 8
        if chunk_id == b"fmt " and chunk_payload_start + 16 <= len(payload):
            bits_per_sample = int.from_bytes(
                payload[chunk_payload_start + 14:chunk_payload_start + 16],
                "little",
                signed=False,
            )
            return {
                "audio_format": int.from_bytes(
                    payload[chunk_payload_start:chunk_payload_start + 2],
                    "little",
                    signed=False,
                ),
                "channels": int.from_bytes(
                    payload[chunk_payload_start + 2:chunk_payload_start + 4],
                    "little",
                    signed=False,
                ),
                "sample_rate_hz": int.from_bytes(
                    payload[chunk_payload_start + 4:chunk_payload_start + 8],
                    "little",
                    signed=False,
                ),
                "sample_width_bytes": bits_per_sample // 8 if bits_per_sample % 8 == 0 else 0,
            }
        if chunk_size == 0xFFFFFFFF:
            break
        position = chunk_payload_start + chunk_size + (chunk_size % 2)
    return {
        "audio_format": 0,
        "channels": 0,
        "sample_rate_hz": 0,
        "sample_width_bytes": 0,
    }


def _expected_min_duration_seconds(expected_text: str) -> float:
    token_count = len(re.findall(r"[\w]+", str(expected_text or ""), flags=re.UNICODE))
    if token_count <= 0:
        return 0.0
    # Lenient lower bound: about 215 wpm plus a small capture margin.
    return round(max(0.8, token_count * 0.28), 3)


def _fixture_quality(
    *,
    payload: bytes,
    expected_text: str,
    synthetic: bool,
    max_duration_seconds: float = DEFAULT_MAX_AUDIO_DURATION_SECONDS,
) -> dict[str, object]:
    duration_seconds = _wav_duration_seconds(payload)
    min_duration_seconds = _expected_min_duration_seconds(expected_text)
    wav_format = _pcm_wav_format(payload)
    failures: list[str] = []
    try:
        effective_max_duration_seconds = float(max_duration_seconds)
    except (TypeError, ValueError, OverflowError):
        effective_max_duration_seconds = DEFAULT_MAX_AUDIO_DURATION_SECONDS
        failures.append("max_audio_duration_invalid")
    if (
        not math.isfinite(effective_max_duration_seconds)
        or effective_max_duration_seconds <= 0
        or effective_max_duration_seconds > DEFAULT_MAX_AUDIO_DURATION_SECONDS
    ):
        effective_max_duration_seconds = DEFAULT_MAX_AUDIO_DURATION_SECONDS
        failures.append("max_audio_duration_invalid")
    if payload and (len(payload) < 12 or payload[:4] != b"RIFF" or payload[8:12] != b"WAVE"):
        failures.append("audio_not_wav")
    elif payload:
        if int(wav_format.get("audio_format") or 0) != 1:
            failures.append("audio_not_pcm")
        if int(wav_format.get("channels") or 0) != 1:
            failures.append("audio_channels_not_mono")
        if int(wav_format.get("sample_width_bytes") or 0) != 2:
            failures.append("audio_sample_width_not_pcm16")
    if duration_seconds <= 0:
        failures.append("audio_duration_missing")
    if min_duration_seconds and duration_seconds < min_duration_seconds:
        failures.append("audio_too_short_for_expected_text")
    if not bool(synthetic) and duration_seconds < 0.8:
        failures.append("captured_audio_too_short")
    if duration_seconds > effective_max_duration_seconds:
        failures.append("audio_duration_implausible")
    return {
        "status": "pass" if not failures else "blocked",
        "failed_codes": failures,
        "audio_duration_seconds": duration_seconds,
        "expected_min_duration_seconds": min_duration_seconds,
        "max_duration_seconds": effective_max_duration_seconds,
        "wav_format": wav_format,
    }


def _tracked_provider_authorization(
    value: object,
    *,
    synthetic: bool,
) -> tuple[dict[str, bool], list[str]]:
    if value is None and synthetic:
        return dict(DEFAULT_PROVIDER_UPLOAD_AUTHORIZATION), []
    if (
        type(value) is not dict
        or set(value) != set(PROVIDER_UPLOAD_LANES)
        or any(type(value.get(lane)) is not bool for lane in PROVIDER_UPLOAD_LANES)
    ):
        return (
            {lane: False for lane in PROVIDER_UPLOAD_LANES},
            ["tracked_provider_upload_authorization_invalid"],
        )
    return {lane: bool(value[lane]) for lane in PROVIDER_UPLOAD_LANES}, []


def _validate_fixture_entry(entry: dict[str, Any], *, fixture_root: Path = FIXTURE_ROOT) -> dict[str, Any]:
    required_fields = (
        "sample",
        "file",
        "origin",
        "speaker_consent",
        "allowed_purpose",
        "retention",
        "expected_text",
        "required_tokens",
        "sha256",
    )
    missing = [field for field in required_fields if not entry.get(field)]
    if missing:
        raise RuntimeError(f"stt_fixture_manifest_missing_fields:{entry.get('sample') or entry.get('file')}:{','.join(missing)}")
    raw_file = str(entry["file"])
    path = fixture_root / raw_file
    if (
        Path(raw_file).is_absolute()
        or Path(raw_file).name != raw_file
        or not SAFE_FIXTURE_FILE_PATTERN.fullmatch(raw_file)
        or not _is_relative_to(path, fixture_root)
    ):
        raise RuntimeError("stt_fixture_path_invalid")
    payload, fixture_read_failures = _load_input_wav(
        path,
        max_audio_bytes=DEFAULT_MAX_EXTERNAL_CANDIDATE_BYTES,
    )
    if fixture_read_failures:
        raise RuntimeError(f"stt_fixture_read_invalid:{','.join(fixture_read_failures)}")
    digest = _sha256_bytes(payload)
    if digest != str(entry.get("sha256") or "").strip():
        raise RuntimeError(f"stt_fixture_hash_mismatch:{entry['file']}")
    governance_failures: list[str] = []
    raw_sample = entry.get("sample")
    if type(raw_sample) is not str or not SAFE_CANDIDATE_SAMPLE_PATTERN.fullmatch(raw_sample):
        governance_failures.append("tracked_sample_invalid")
        safe_sample = "invalid_fixture_sample"
    else:
        safe_sample = raw_sample
    raw_expected_text = entry.get("expected_text")
    raw_required_tokens = entry.get("required_tokens")
    if type(raw_expected_text) is not str:
        governance_failures.append("tracked_expected_text_type_invalid")
    governance_failures.extend(
        _required_token_contract_failures(
            expected_text=raw_expected_text,
            required_tokens=raw_required_tokens,
            prefix="tracked_fixture",
        )
    )
    expected_text = str(raw_expected_text or "").strip() if type(raw_expected_text) is str else ""
    tokens = (
        [str(token).strip() for token in raw_required_tokens]
        if type(raw_required_tokens) is list
        and all(type(token) is str for token in raw_required_tokens)
        else []
    )
    raw_synthetic = entry.get("synthetic")
    if type(raw_synthetic) is not bool:
        governance_failures.append("tracked_synthetic_type_invalid")
        synthetic = False
    else:
        synthetic = raw_synthetic
    provider_authorization, authorization_failures = _tracked_provider_authorization(
        entry.get("provider_upload_authorization"),
        synthetic=synthetic,
    )
    governance_failures.extend(authorization_failures)
    if not synthetic:
        if entry.get("speaker_consent") != APPROVED_SPEAKER_CONSENT:
            governance_failures.append("tracked_speaker_consent_invalid")
        if entry.get("allowed_purpose") != APPROVED_ALLOWED_PURPOSE:
            governance_failures.append("tracked_allowed_purpose_invalid")
        if entry.get("retention") not in APPROVED_RETENTION_VALUES:
            governance_failures.append("tracked_retention_invalid")
    try:
        min_token_f1 = float(entry.get("min_token_f1") or 0.6)
        max_wer = float(entry.get("max_wer") or 0.5)
    except (TypeError, ValueError, OverflowError) as exc:
        raise RuntimeError(f"stt_fixture_threshold_invalid:{entry['sample']}") from exc
    if (
        not math.isfinite(min_token_f1)
        or not math.isfinite(max_wer)
        or not 0.0 <= min_token_f1 <= 1.0
        or not 0.0 <= max_wer <= 1.0
    ):
        raise RuntimeError(f"stt_fixture_threshold_invalid:{entry['sample']}")
    quality = _fixture_quality(
        payload=payload,
        expected_text=expected_text,
        synthetic=synthetic,
    )
    if governance_failures:
        quality = {
            **quality,
            "status": "blocked",
            "failed_codes": sorted(
                set(list(quality.get("failed_codes") or []) + governance_failures)
            ),
        }
    return {
        "sample": safe_sample,
        "file": raw_file,
        "payload": payload,
        "expected_text": expected_text,
        "required_tokens": tokens,
        "language": APPROVED_LANGUAGE,
        "min_token_f1": min_token_f1,
        "max_wer": max_wer,
        "fixture_sha256": digest,
        "fixture_quality": quality,
        "provider_upload_authorization": provider_authorization,
        "_governance_preflight_failed_codes": sorted(set(governance_failures)),
        "provenance": {
            "origin": "governed_synthetic_stt_fixture" if synthetic else "governed_tracked_captured_stt_fixture",
            "speaker_consent": (
                "synthetic_fixture_no_human_speaker"
                if synthetic
                else APPROVED_SPEAKER_CONSENT
            ),
            "allowed_purpose": APPROVED_ALLOWED_PURPOSE,
            "retention": (
                "repo_synthetic_regression_fixture"
                if synthetic
                else str(entry.get("retention"))
            ),
            "synthetic": synthetic,
            "accent": (
                "synthetic"
                if synthetic
                else APPROVED_ACCENT if entry.get("accent") == APPROVED_ACCENT else "unspecified"
            ),
            "provider_upload_authorization": provider_authorization,
        },
    }


def _fixture_specs() -> list[dict[str, Any]]:
    manifest = _load_fixture_manifest()
    return [_validate_fixture_entry(dict(entry)) for entry in list(manifest.get("fixtures") or []) if isinstance(entry, dict)]


def _load_candidate_receipt(
    path: Path,
    *,
    max_bytes: int = DEFAULT_MAX_CANDIDATE_RECEIPT_BYTES,
) -> tuple[dict[str, object], bytes, list[str]]:
    path = path.expanduser()
    try:
        effective_max_bytes = int(max_bytes)
    except (TypeError, ValueError, OverflowError):
        return {}, b"", ["candidate_receipt_max_bytes_invalid"]
    if effective_max_bytes <= 0 or effective_max_bytes > DEFAULT_MAX_CANDIDATE_RECEIPT_BYTES:
        return {}, b"", ["candidate_receipt_max_bytes_invalid"]
    try:
        if path.is_symlink():
            return {}, b"", ["candidate_receipt_symlink_forbidden"]
    except OSError:
        return {}, b"", ["candidate_receipt_stat_failed"]
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except FileNotFoundError:
        return {}, b"", ["candidate_receipt_missing"]
    except OSError:
        return {}, b"", ["candidate_receipt_open_failed"]
    try:
        file_stat = os.fstat(descriptor)
        if not stat.S_ISREG(file_stat.st_mode):
            return {}, b"", ["candidate_receipt_not_regular_file"]
        byte_count = int(file_stat.st_size)
        if byte_count <= 0:
            return {}, b"", ["candidate_receipt_empty"]
        if byte_count > effective_max_bytes:
            return {}, b"", ["candidate_receipt_too_large"]
        chunks: list[bytes] = []
        remaining = byte_count
        while remaining > 0:
            chunk = os.read(descriptor, min(remaining, 64 * 1024))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        raw = b"".join(chunks)
        if len(raw) != byte_count:
            return {}, b"", ["candidate_receipt_short_read"]
    except OSError:
        return {}, b"", ["candidate_receipt_read_failed"]
    finally:
        os.close(descriptor)
    try:
        parsed = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {}, raw, ["candidate_receipt_invalid_json"]
    if not isinstance(parsed, dict):
        return {}, raw, ["candidate_receipt_invalid_object"]
    return dict(parsed), raw, []


def _object(value: object) -> dict[str, object]:
    return dict(value) if isinstance(value, dict) else {}


def _candidate_binding_from_receipt(receipt: dict[str, object]) -> dict[str, object]:
    binding = _object(receipt.get("candidate_binding"))
    payload = _object(binding.get("payload"))
    if binding.get("contract_name") != CANDIDATE_BINDING_CONTRACT:
        raise RuntimeError("candidate_binding_contract_invalid")
    if binding.get("canonicalization") != CANONICALIZATION:
        raise RuntimeError("candidate_binding_canonicalization_invalid")
    if payload.get("contract_name") != CANDIDATE_BINDING_CONTRACT:
        raise RuntimeError("candidate_binding_payload_contract_invalid")
    if str(binding.get("sha256") or "") != _canonical_sha256(payload):
        raise RuntimeError("candidate_binding_sha256_mismatch")
    return binding


def _candidate_receipt_projection(
    receipt: dict[str, object],
    *,
    review_binding_sha256: str,
) -> dict[str, object]:
    bundle = _object(receipt.get("bundle"))
    audio = _object(receipt.get("audio"))
    entry = _object(receipt.get("candidate_manifest_entry"))
    expected = _object(entry.get("expected_text"))
    raw_required = entry.get("required_tokens")
    required = [_object(item) for item in list(raw_required if isinstance(raw_required, list) else [])]
    raw_failed_codes = receipt.get("failed_codes")
    return {
        "contract_name": CANDIDATE_BINDING_CONTRACT,
        "audio_sha256": str(audio.get("sha256") or ""),
        "bundle_id": str(bundle.get("id") or ""),
        "sample": str(entry.get("sample") or ""),
        "fixture_file": str(entry.get("file") or ""),
        "origin": str(entry.get("origin") or ""),
        "expected_text_sha256": str(expected.get("text_sha256") or ""),
        "required_token_sha256": [str(item.get("text_sha256") or "") for item in required],
        "speaker_consent": str(entry.get("speaker_consent") or ""),
        "allowed_purpose": str(entry.get("allowed_purpose") or ""),
        "retention": str(entry.get("retention") or ""),
        "language": str(entry.get("language") or ""),
        "accent": str(entry.get("accent") or ""),
        "fixture_quality": _object(receipt.get("fixture_quality")),
        "privacy_mode": str(receipt.get("privacy_mode") or receipt.get("text_mode") or ""),
        "operator_ground_truth_review_binding_sha256": review_binding_sha256,
        "provider_upload_authorization": _object(entry.get("provider_upload_authorization")),
        "status": str(receipt.get("status") or ""),
        "failed_codes": sorted(
            str(item)
            for item in list(raw_failed_codes if isinstance(raw_failed_codes, list) else [])
            if str(item)
        ),
    }


def _external_captured_candidate_spec(
    *,
    bundle_dir: Path,
    candidate_receipt_path: Path,
    ground_truth_review_path: Path,
    min_token_f1: float = 0.55,
    max_wer: float = 0.55,
    allow_external_root: bool = False,
    bundle_root: Path = DEFAULT_STT_ERROR_LOG_ROOT,
    max_bytes: int = DEFAULT_MAX_EXTERNAL_CANDIDATE_BYTES,
) -> dict[str, Any]:
    bundle_dir = bundle_dir.expanduser()
    failures: list[str] = []
    try:
        effective_min_token_f1 = float(min_token_f1)
        effective_max_wer = float(max_wer)
    except (TypeError, ValueError, OverflowError):
        effective_min_token_f1 = 0.55
        effective_max_wer = 0.55
        failures.append("candidate_threshold_invalid")
    if (
        not math.isfinite(effective_min_token_f1)
        or not math.isfinite(effective_max_wer)
        or not 0.0 <= effective_min_token_f1 <= 1.0
        or not 0.0 <= effective_max_wer <= 1.0
    ):
        effective_min_token_f1 = 0.55
        effective_max_wer = 0.55
        failures.append("candidate_threshold_invalid")
    try:
        effective_max_bytes = int(max_bytes)
    except (TypeError, ValueError, OverflowError):
        effective_max_bytes = DEFAULT_MAX_EXTERNAL_CANDIDATE_BYTES
        failures.append("candidate_max_bytes_invalid")
    if effective_max_bytes <= 0 or effective_max_bytes > DEFAULT_MAX_EXTERNAL_CANDIDATE_BYTES:
        effective_max_bytes = DEFAULT_MAX_EXTERNAL_CANDIDATE_BYTES
        failures.append("candidate_max_bytes_invalid")
    if not allow_external_root and not _is_relative_to(bundle_dir, bundle_root):
        failures.append("bundle_not_under_memorial_stt_error_root")
    path = bundle_dir / "input.wav"
    payload, input_failures = _load_input_wav(path, max_audio_bytes=effective_max_bytes)
    failures.extend(input_failures)
    digest = _sha256_bytes(payload) if payload else ""
    receipt, receipt_raw, receipt_failures = _load_candidate_receipt(candidate_receipt_path)
    failures.extend(receipt_failures)
    raw_review, review_load_failures = _load_private_ground_truth_review(ground_truth_review_path)
    failures.extend(review_load_failures)
    failures.extend(_validate_raw_review_schema(raw_review))
    review = _normalized_review(raw_review)
    review_binding_payload = _review_binding_payload(review)
    review_binding_sha256 = _canonical_sha256(review_binding_payload)
    failures.extend(
        _validate_review(
            review,
            audio_sha256=digest,
            bundle_id=bundle_dir.name,
            now=datetime.now(UTC),
        )
    )
    if receipt.get("contract_name") != "ea.memorial_stt_fixture_candidate":
        failures.append("candidate_receipt_contract_invalid")
    try:
        candidate_contract_version = int(receipt.get("contract_version") or 0)
    except (TypeError, ValueError, OverflowError):
        candidate_contract_version = 0
    if candidate_contract_version != CANDIDATE_CONTRACT_VERSION:
        failures.append("candidate_receipt_version_invalid")
    if receipt.get("status") != "pass":
        failures.append("candidate_receipt_not_passed")
    try:
        candidate_binding = _candidate_binding_from_receipt(receipt)
    except RuntimeError as exc:
        candidate_binding = {}
        failures.append(str(exc))
    binding_payload = _object(candidate_binding.get("payload"))
    review_receipt = _object(receipt.get("operator_ground_truth_review"))
    if review_receipt.get("contract_name") != GROUND_TRUTH_REVIEW_BINDING_CONTRACT:
        failures.append("candidate_review_binding_contract_invalid")
    if str(review_receipt.get("sha256") or "") != review_binding_sha256:
        failures.append("candidate_review_binding_sha256_mismatch")
    expected_projection = _candidate_receipt_projection(
        receipt,
        review_binding_sha256=review_binding_sha256,
    )
    if binding_payload != expected_projection:
        failures.append("candidate_binding_payload_projection_mismatch")
    expected_text = str(review.get("expected_text") or "")
    tokens = [str(token) for token in list(review.get("required_tokens") or [])]
    sample = str(review.get("sample") or "")
    provider_upload_authorization = dict(review.get("provider_upload_authorization") or {})
    safe_bundle_id = bundle_dir.name if SAFE_BUNDLE_ID_PATTERN.fullmatch(bundle_dir.name) else "invalid_bundle_id"
    safe_sample = (
        sample
        if SAFE_CANDIDATE_SAMPLE_PATTERN.fullmatch(sample) and sample not in RESERVED_CANDIDATE_SAMPLES
        else "invalid_candidate_sample"
    )
    safe_provider_upload_authorization = (
        provider_upload_authorization
        if set(provider_upload_authorization) == set(PROVIDER_UPLOAD_LANES)
        and all(isinstance(provider_upload_authorization.get(lane), bool) for lane in PROVIDER_UPLOAD_LANES)
        else {lane: False for lane in PROVIDER_UPLOAD_LANES}
    )
    expected_hash = _sha256_text(expected_text)
    token_hashes = [_sha256_text(token) for token in tokens]
    if str(review.get("status") or "") != "approved":
        failures.append("ground_truth_review_not_approved")
    if str(review.get("audio_sha256") or "") != digest:
        failures.append("ground_truth_review_audio_sha256_mismatch")
    if str(review.get("bundle_id") or "") != bundle_dir.name:
        failures.append("ground_truth_review_bundle_id_mismatch")
    if not sample:
        failures.append("ground_truth_review_sample_missing")
    if not expected_text:
        failures.append("ground_truth_review_expected_text_missing")
    if not tokens:
        failures.append("ground_truth_review_required_tokens_missing")
    if not SAFE_CANDIDATE_SAMPLE_PATTERN.fullmatch(sample):
        failures.append("candidate_sample_invalid")
    if sample in RESERVED_CANDIDATE_SAMPLES:
        failures.append("candidate_sample_reserved")
    if str(binding_payload.get("audio_sha256") or "") != digest:
        failures.append("candidate_audio_sha256_mismatch")
    if str(binding_payload.get("bundle_id") or "") != bundle_dir.name:
        failures.append("candidate_bundle_id_mismatch")
    if not SAFE_BUNDLE_ID_PATTERN.fullmatch(bundle_dir.name):
        failures.append("candidate_bundle_id_invalid")
    if str(binding_payload.get("sample") or "") != sample:
        failures.append("candidate_sample_mismatch")
    bound_fixture_file = str(binding_payload.get("fixture_file") or "")
    if (
        not SAFE_FIXTURE_FILE_PATTERN.fullmatch(bound_fixture_file)
        or Path(bound_fixture_file).name != bound_fixture_file
        or bound_fixture_file != f"{sample}_captured.wav"
    ):
        failures.append("candidate_fixture_file_invalid")
    if str(binding_payload.get("origin") or "") != APPROVED_CAPTURE_ORIGIN:
        failures.append("candidate_origin_invalid")
    if str(binding_payload.get("expected_text_sha256") or "") != expected_hash:
        failures.append("candidate_expected_text_sha256_mismatch")
    bound_token_hashes = binding_payload.get("required_token_sha256")
    if list(bound_token_hashes if isinstance(bound_token_hashes, list) else []) != token_hashes:
        failures.append("candidate_required_token_sha256_mismatch")
    for field in ("speaker_consent", "allowed_purpose", "retention", "language", "accent"):
        if str(binding_payload.get(field) or "") != str(review.get(field) or ""):
            failures.append(f"candidate_{field}_mismatch")
    if str(review.get("language") or "") != APPROVED_LANGUAGE:
        failures.append("candidate_language_invalid")
    if str(review.get("accent") or "") != APPROVED_ACCENT:
        failures.append("candidate_accent_invalid")
    if _object(binding_payload.get("provider_upload_authorization")) != provider_upload_authorization:
        failures.append("candidate_provider_upload_authorization_mismatch")
    if str(binding_payload.get("status") or "") != "pass":
        failures.append("candidate_bound_status_not_passed")
    bound_failed_codes = binding_payload.get("failed_codes")
    if list(bound_failed_codes if isinstance(bound_failed_codes, list) else []):
        failures.append("candidate_bound_failed_codes_present")
    bound_quality = _object(binding_payload.get("fixture_quality"))
    if bound_quality.get("status") != "pass" or list(bound_quality.get("failed_codes") or []):
        failures.append("candidate_bound_fixture_quality_not_passed")
    try:
        bound_max_duration_seconds = float(
            bound_quality.get("max_duration_seconds") or DEFAULT_MAX_AUDIO_DURATION_SECONDS
        )
    except (TypeError, ValueError, OverflowError):
        bound_max_duration_seconds = DEFAULT_MAX_AUDIO_DURATION_SECONDS
        failures.append("candidate_bound_max_duration_invalid")
    if (
        not math.isfinite(bound_max_duration_seconds)
        or bound_max_duration_seconds <= 0
        or bound_max_duration_seconds > DEFAULT_MAX_AUDIO_DURATION_SECONDS
    ):
        failures.append("candidate_bound_max_duration_invalid")
        bound_max_duration_seconds = DEFAULT_MAX_AUDIO_DURATION_SECONDS
    quality = _fixture_quality(
        payload=payload,
        expected_text=expected_text,
        synthetic=False,
        max_duration_seconds=bound_max_duration_seconds,
    ) if payload else {
        "status": "blocked",
        "failed_codes": ["audio_missing"],
        "audio_duration_seconds": 0.0,
        "expected_min_duration_seconds": _expected_min_duration_seconds(expected_text),
        "max_duration_seconds": bound_max_duration_seconds,
        "wav_format": _pcm_wav_format(payload),
    }
    if quality != bound_quality:
        failures.append("candidate_bound_fixture_quality_mismatch")
    failures.extend(str(code) for code in list(quality.get("failed_codes") or []) if str(code))
    if failures:
        quality = {
            **quality,
            "status": "blocked",
            "failed_codes": sorted(set(failures)),
        }
    return {
        "sample": safe_sample,
        "file": "input.wav",
        "payload": payload,
        "expected_text": expected_text.strip(),
        "required_tokens": tokens,
        "language": APPROVED_LANGUAGE if review.get("language") == APPROVED_LANGUAGE else "invalid",
        "min_token_f1": effective_min_token_f1,
        "max_wer": effective_max_wer,
        "fixture_sha256": digest,
        "fixture_quality": quality,
        "provider_upload_authorization": safe_provider_upload_authorization,
        "_ground_truth_reviewed_at": str(review.get("reviewed_at") or ""),
        "captured_candidate_binding": {
            "candidate_receipt_sha256": _sha256_bytes(receipt_raw) if receipt_raw else "",
            "candidate_binding_contract_name": str(candidate_binding.get("contract_name") or ""),
            "candidate_binding_sha256": str(candidate_binding.get("sha256") or ""),
            "operator_ground_truth_review_binding_sha256": review_binding_sha256,
            "source_audio_sha256": digest,
            "bundle_id": safe_bundle_id,
            "sample": safe_sample,
            "provider_upload_authorization": safe_provider_upload_authorization,
        },
        "provenance": {
            "origin": APPROVED_CAPTURE_ORIGIN,
            "speaker_consent": (
                APPROVED_SPEAKER_CONSENT
                if review.get("speaker_consent") == APPROVED_SPEAKER_CONSENT
                else "invalid"
            ),
            "allowed_purpose": (
                APPROVED_ALLOWED_PURPOSE
                if review.get("allowed_purpose") == APPROVED_ALLOWED_PURPOSE
                else "invalid"
            ),
            "retention": (
                str(review.get("retention"))
                if review.get("retention") in APPROVED_RETENTION_VALUES
                else "invalid"
            ),
            "synthetic": False,
            "accent": APPROVED_ACCENT if review.get("accent") == APPROVED_ACCENT else "invalid",
            "external_bundle": True,
            "bundle_root": "[memorial_stt_error_root]" if _is_relative_to(bundle_dir, bundle_root) else "[external_root]",
            "bundle_id": safe_bundle_id,
            "candidate_receipt_sha256": _sha256_bytes(receipt_raw) if receipt_raw else "",
            "candidate_binding_contract_name": str(candidate_binding.get("contract_name") or ""),
            "candidate_binding_sha256": str(candidate_binding.get("sha256") or ""),
            "operator_ground_truth_review_binding_sha256": review_binding_sha256,
            "provider_upload_authorization": safe_provider_upload_authorization,
        },
    }


def _wav_pcm16_samples(payload: bytes) -> tuple[int, list[int]]:
    with wave.open(io.BytesIO(payload), "rb") as wav_file:
        sample_rate = int(wav_file.getframerate() or 16_000)
        frames = int(wav_file.getnframes() or 0)
        payload_duration = _pcm_wav_duration_from_payload(payload)
        if payload_duration and frames / float(sample_rate or 16_000) > max(payload_duration * 2.0, payload_duration + 30.0):
            data_start, data_size, _byte_rate = _pcm_wav_layout(payload)
            raw = payload[data_start:data_start + data_size]
        else:
            raw = wav_file.readframes(frames)
    samples = [sample for (sample,) in struct.iter_unpack("<h", raw[: len(raw) - (len(raw) % 2)])]
    return sample_rate, samples


def _wav_from_samples(samples: list[int], *, sample_rate: int) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(struct.pack("<" + "h" * len(samples), *samples))
    return buffer.getvalue()


def _hostile(payload: bytes) -> bytes:
    sample_rate, samples = _wav_pcm16_samples(payload)
    amplified = [max(-32768, min(32767, int(sample * 1.18))) for sample in samples]
    delay_samples = max(1, int(sample_rate * 0.076))
    echoed = list(amplified)
    for index, sample in enumerate(amplified):
        delayed_index = index + delay_samples
        if delayed_index < len(echoed):
            echoed[delayed_index] = max(-32768, min(32767, echoed[delayed_index] + int(sample * 0.22)))
    noise = [132, -132, 66, -66]
    mixed = [max(-32768, min(32767, sample + noise[index % len(noise)])) for index, sample in enumerate(echoed)]
    return _wav_from_samples(mixed, sample_rate=sample_rate)


def _transformation_receipt(
    *,
    source_payload: bytes,
    output_payload: bytes,
    transformation_id: str,
    transformation_version: int,
    parameters: dict[str, object],
) -> dict[str, object]:
    source_duration = _wav_duration_seconds(source_payload)
    output_duration = _wav_duration_seconds(output_payload)
    payload = {
        "contract_name": TRANSFORMATION_RECEIPT_CONTRACT,
        "transformation_id": transformation_id,
        "transformation_version": int(transformation_version),
        "source_audio_sha256": _sha256_bytes(source_payload) if source_payload else "",
        "output_audio_sha256": _sha256_bytes(output_payload) if output_payload else "",
        "source_duration_seconds": source_duration,
        "output_duration_seconds": output_duration,
        "duration_preserved": (
            source_duration > 0.0
            and output_duration > 0.0
            and abs(source_duration - output_duration) <= 0.001
        ),
        "parameters": parameters,
    }
    return {
        "contract_name": TRANSFORMATION_RECEIPT_CONTRACT,
        "canonicalization": CANONICALIZATION,
        "sha256": _canonical_sha256(payload),
        "payload": payload,
    }


def _sample_variants(spec: dict[str, Any]) -> list[dict[str, Any]]:
    source_payload = bytes(spec.get("payload") or b"")
    source_sha256 = str(spec.get("fixture_sha256") or "")
    synthetic = bool(dict(spec.get("provenance") or {}).get("synthetic"))
    base_variant = "synthetic" if synthetic else "captured"
    computed_base_quality = _fixture_quality(
        payload=source_payload,
        expected_text=str(spec.get("expected_text") or ""),
        synthetic=synthetic,
    ) if source_payload else dict(spec.get("fixture_quality") or {})
    source_quality = dict(spec.get("fixture_quality") or {})
    source_failures = [str(item) for item in list(source_quality.get("failed_codes") or []) if str(item)]
    computed_failures = [str(item) for item in list(computed_base_quality.get("failed_codes") or []) if str(item)]
    source_quality_passed = source_quality.get("status") == "pass" and not source_failures
    base_quality = {
        **computed_base_quality,
        "status": "pass" if source_quality_passed and not computed_failures else "blocked",
        "failed_codes": sorted(set(source_failures + computed_failures)),
    }
    identity = {
        **spec,
        "variant": base_variant,
        "payload": source_payload,
        "source_fixture_sha256": source_sha256,
        "fixture_sha256": _sha256_bytes(source_payload) if source_payload else "",
        "source_fixture_quality": source_quality,
        "fixture_quality": base_quality,
        "transformation": _transformation_receipt(
            source_payload=source_payload,
            output_payload=source_payload,
            transformation_id="identity_v1",
            transformation_version=1,
            parameters={},
        ),
    }
    transformation_failures: list[str] = []
    if source_payload and base_quality.get("status") == "pass":
        try:
            hostile_payload = _hostile(source_payload)
        except (EOFError, ValueError, wave.Error, struct.error):
            hostile_payload = source_payload
            transformation_failures.append("hostile_transform_failed")
    else:
        hostile_payload = source_payload
    computed_hostile_quality = _fixture_quality(
        payload=hostile_payload,
        expected_text=str(spec.get("expected_text") or ""),
        synthetic=synthetic,
    ) if hostile_payload else dict(base_quality)
    hostile_failures = [
        str(item)
        for item in list(computed_hostile_quality.get("failed_codes") or [])
        if str(item)
    ]
    hostile_transformation = _transformation_receipt(
        source_payload=source_payload,
        output_payload=hostile_payload,
        transformation_id="hostile_room_v1",
        transformation_version=1,
        parameters={
            "gain": 1.18,
            "echo_delay_ms": 76,
            "echo_mix": 0.22,
            "noise_cycle_pcm16": [132, -132, 66, -66],
            "speed_factor": 1.0,
        },
    )
    if source_payload and base_quality.get("status") == "pass" and not bool(
        _object(hostile_transformation.get("payload")).get("duration_preserved")
    ):
        transformation_failures.append("hostile_transform_duration_not_preserved")
    hostile_quality = {
        **computed_hostile_quality,
        "status": (
            "pass"
            if source_quality_passed and not hostile_failures and not transformation_failures
            else "blocked"
        ),
        "failed_codes": sorted(set(source_failures + hostile_failures + transformation_failures)),
    }
    hostile = {
        **spec,
        "sample": f"{spec['sample']}_hostile",
        "variant": "hostile",
        "payload": hostile_payload,
        "source_fixture_sha256": source_sha256,
        "fixture_sha256": _sha256_bytes(hostile_payload) if hostile_payload else "",
        "source_fixture_quality": source_quality,
        "fixture_quality": hostile_quality,
        "transformation": hostile_transformation,
    }
    return [identity, hostile]


def _tokens(text: str) -> list[str]:
    normalized = unicodedata.normalize("NFKD", str(text or "").lower().replace("ß", "ss"))
    stripped = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    return re.findall(r"[a-z0-9]+", stripped)


def _levenshtein(left: list[str], right: list[str]) -> int:
    if not left:
        return len(right)
    if not right:
        return len(left)
    previous = list(range(len(right) + 1))
    for left_index, left_token in enumerate(left, start=1):
        current = [left_index]
        for right_index, right_token in enumerate(right, start=1):
            current.append(
                min(
                    previous[right_index] + 1,
                    current[right_index - 1] + 1,
                    previous[right_index - 1] + (0 if left_token == right_token else 1),
                )
            )
        previous = current
    return previous[-1]


def _word_error_rate(expected_text: str, actual_text: str) -> float:
    expected = _tokens(expected_text)
    actual = _tokens(actual_text)
    if not expected:
        return 0.0 if not actual else 1.0
    return round(_levenshtein(expected, actual) / len(expected), 4)


def _token_f1(expected_text: str, actual_text: str) -> float:
    expected = _tokens(expected_text)
    actual = _tokens(actual_text)
    if not expected and not actual:
        return 1.0
    if not expected or not actual:
        return 0.0
    remaining: dict[str, int] = {}
    for token in actual:
        remaining[token] = remaining.get(token, 0) + 1
    overlap = 0
    for token in expected:
        count = remaining.get(token, 0)
        if count <= 0:
            continue
        overlap += 1
        remaining[token] = count - 1
    precision = overlap / len(actual) if actual else 0.0
    recall = overlap / len(expected) if expected else 0.0
    if precision + recall <= 0:
        return 0.0
    return round((2 * precision * recall) / (precision + recall), 4)


def _required_tokens_present(required_tokens: list[str], actual_text: str) -> bool:
    actual = set(_tokens(actual_text))
    if not required_tokens:
        return False
    for token_phrase in required_tokens:
        components = _tokens(token_phrase)
        if not components or any(component not in actual for component in components):
            return False
    return True


def _usable(text: str) -> bool:
    raw = _raw_transcript_text(text)
    normalized = raw.casefold()
    known_bad = "amara.org" in normalized or "untertitel" in normalized
    return bool(raw) and not known_bad


def _raw_transcript_text(value: object) -> str:
    return " ".join(str(value or "").split()).strip()


def _score_text(text: str, spec: dict[str, Any], *, text_mode: str | None = None) -> dict[str, object]:
    public_text_mode = _benchmark_text_mode(text_mode)
    raw = _raw_transcript_text(text)
    expected = str(spec.get("expected_text") or "").strip()
    required_tokens = [str(token) for token in list(spec.get("required_tokens") or [])]
    wer = _word_error_rate(expected, raw)
    f1 = _token_f1(expected, raw)
    intent_correct = _required_tokens_present(required_tokens, raw)
    usable = _usable(raw)
    passed = (
        usable
        and intent_correct
        and f1 >= float(spec.get("min_token_f1") or 0.6)
        and wer <= float(spec.get("max_wer") or 0.5)
    )
    score: dict[str, object] = {
        "wer": wer,
        "token_f1": f1,
        "intent_correct": intent_correct,
        "usable": usable,
        "passed": passed,
        "min_token_f1": float(spec.get("min_token_f1") or 0.6),
        "max_wer": float(spec.get("max_wer") or 0.5),
        "text_mode": public_text_mode,
        "expected_text_chars": len(expected),
        "expected_text_sha256": _sha256_text(expected),
        "actual_text_chars": len(raw),
        "actual_text_sha256": _sha256_text(raw),
        "required_token_count": len(required_tokens),
        "required_token_sha256": [_sha256_text(_raw_transcript_text(token)) for token in required_tokens],
    }
    if public_text_mode == "full":
        score.update(
            {
                "expected_text": expected,
                "required_tokens": required_tokens,
                "actual_text": raw,
            }
        )
    else:
        score["text_redacted"] = True
    return score


def _attach_score(
    result: dict[str, object],
    spec: dict[str, Any],
    *,
    text_mode: str | None = None,
    evidence_eligible: bool | None = None,
    evidence_failed_codes: list[str] | None = None,
) -> dict[str, object]:
    public_text_mode = _benchmark_text_mode(text_mode)
    scored = dict(result)
    raw_detail = scored.pop("detail", "")
    raw_reason = scored.pop("reason", "")
    if raw_detail or raw_reason:
        scored["detail"] = _sanitize_provider_error_detail(
            {"detail": raw_detail, "reason": raw_reason}
            if raw_reason
            else raw_detail
        )
    raw_text = str(scored.get("text") or "")
    scored.update(_score_text(raw_text, spec, text_mode=public_text_mode))
    failures = sorted(set(str(item) for item in list(evidence_failed_codes or []) if str(item)))
    if evidence_eligible is None:
        evidence_eligible = str(scored.get("status") or "").strip().lower() in SUCCESSFUL_PROVIDER_STATUSES
        if not evidence_eligible:
            failures.append("provider_status_not_successful")
    if not evidence_eligible:
        scored["passed"] = False
        if not failures:
            failures.append("provider_evidence_not_eligible")
    failures = sorted(set(failures))
    scored["provider_evidence_status"] = "eligible" if evidence_eligible else "blocked"
    scored["provider_evidence_failed_codes"] = failures
    if public_text_mode != "full":
        scored.pop("text", None)
    return scored


def _run_shadow(payload: bytes, spec: dict[str, Any], *, text_mode: str | None = None) -> dict[str, object]:
    started = time.perf_counter()
    result = public_memorials._memorial_shadow_stt_result(
        user_audio_payload=payload,
        content_type="audio/wav",
        primary_transcript="",
        primary_transcriber="",
    )
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    text = _raw_transcript_text(result.get("transcript_text"))
    raw_status = str(result.get("status") or result.get("transcription_status") or "").strip().lower()
    status_accepted = raw_status in SUCCESSFUL_PROVIDER_STATUSES
    return _attach_score({
        "status": _safe_provider_status(raw_status),
        "text": text,
        "ms": round(elapsed_ms, 1),
        "reason": result.get("reason", ""),
    }, spec, text_mode=text_mode, evidence_eligible=status_accepted, evidence_failed_codes=(
        [] if status_accepted else ["provider_status_not_successful"]
    ))


def _run_onemin_sample(payload: bytes, spec: dict[str, Any], *, text_mode: str | None = None) -> dict[str, object]:
    candidate_keys = product_service._pocket_onemin_api_keys()
    keys = public_memorials._memorial_onemin_available_keys(tuple(candidate_keys))
    if not keys:
        return _attach_score(
            {
                "status": "unavailable",
                "detail": "no_keys",
                "candidate_key_count": len(candidate_keys),
                "text": "",
            },
            spec,
            text_mode=text_mode,
            evidence_eligible=False,
            evidence_failed_codes=["provider_unavailable"],
        )
    errors: list[str] = []
    for api_key in keys:
        try:
            started = time.perf_counter()
            uploaded = product_service._onemin_asset_upload(
                api_key=api_key,
                filename="memorial-speech.wav",
                content_type="audio/wav",
                payload=payload,
            )
            asset = dict(uploaded.get("asset") or {}) if isinstance(uploaded.get("asset"), dict) else {}
            file_content = dict(uploaded.get("fileContent") or {}) if isinstance(uploaded.get("fileContent"), dict) else {}
            audio_path = str(file_content.get("path") or asset.get("key") or "").strip()
            transcribed = product_service._onemin_speech_to_text(
                api_key=api_key,
                audio_path=audio_path,
                language=str(spec.get("language") or "de"),
            )
            ai_record = dict(transcribed.get("aiRecord") or {}) if isinstance(transcribed.get("aiRecord"), dict) else {}
            ai_detail = dict(ai_record.get("aiRecordDetail") or {}) if isinstance(ai_record.get("aiRecordDetail"), dict) else {}
            text = _raw_transcript_text(
                product_service._extract_transcript_text(ai_detail.get("responseObject"))
                or product_service._extract_transcript_text(ai_detail.get("resultObject"))
            )
            elapsed_ms = (time.perf_counter() - started) * 1000.0
            status = "known_bad" if not _usable(text) and bool(text) else ("ok" if text else "empty")
            return _attach_score({
                "status": status,
                "text": text,
                "ms": round(elapsed_ms, 1),
            }, spec, text_mode=text_mode, evidence_eligible=status == "ok", evidence_failed_codes=(
                [] if status == "ok" else ["provider_status_not_successful"]
            ))
        except Exception as exc:
            errors.append(str(exc))
    return _attach_score(
        {
            "status": "error",
            "detail": errors[:3],
            "sampled_keys": len(keys),
            "candidate_key_count": len(candidate_keys),
            "sample_strategy": "primary_plus_spread_fallbacks",
            "text": "",
        },
        spec,
        text_mode=text_mode,
        evidence_eligible=False,
        evidence_failed_codes=["provider_error"],
    )


def _run_full_runtime(payload: bytes, spec: dict[str, Any], *, text_mode: str | None = None) -> dict[str, object]:
    started = time.perf_counter()
    try:
        result = public_memorials._memorial_transcribe_audio_blob(payload=payload, content_type="audio/wav")
    except HTTPException as exc:
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        return _attach_score({
            "status": "http_error",
            "text": "",
            "ms": round(elapsed_ms, 1),
            "transcriber": _safe_transcriber_receipt(""),
            "detail": str(exc.detail),
        }, spec, text_mode=text_mode, evidence_eligible=False, evidence_failed_codes=["provider_http_error"])
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    raw_status = str(result.get("transcription_status") or "").strip().lower()
    primary_value = result.get("primary_transcript_text")
    primary_text_present = "primary_transcript_text" in result and isinstance(primary_value, str)
    text = _raw_transcript_text(primary_value) if primary_text_present else ""
    evidence_failures: list[str] = []
    if raw_status not in SUCCESSFUL_PROVIDER_STATUSES:
        evidence_failures.append("provider_status_not_successful")
    if not primary_text_present:
        evidence_failures.append("primary_raw_transcript_missing")
    return _attach_score({
        "status": _safe_provider_status(raw_status),
        "text": text,
        "ms": round(elapsed_ms, 1),
        "transcriber": _safe_transcriber_receipt(result.get("transcriber", "")),
        "detail": result.get("detail", ""),
        "scored_text_source": "primary_transcript_text" if primary_text_present else "none",
    }, spec, text_mode=text_mode, evidence_eligible=not evidence_failures, evidence_failed_codes=evidence_failures)


def _provider_summary(rows: list[dict[str, object]], provider_key: str) -> dict[str, object]:
    scored = [dict(row.get(provider_key) or {}) for row in rows]
    pass_count = sum(1 for row in scored if row.get("passed") is True)
    scored_count = sum(1 for row in scored if "token_f1" in row)
    avg_f1 = round(sum(float(row.get("token_f1") or 0.0) for row in scored) / scored_count, 4) if scored_count else 0.0
    wer_values: list[float] = []
    for row in scored:
        if "wer" not in row:
            continue
        try:
            wer_values.append(float(row.get("wer")))
        except (TypeError, ValueError):
            wer_values.append(1.0)
    avg_wer = round(sum(wer_values) / len(wer_values), 4) if wer_values else 1.0
    intent_count = sum(1 for row in scored if row.get("intent_correct") is True)
    latencies = [float(row.get("ms") or 0.0) for row in scored if float(row.get("ms") or 0.0) > 0]
    return {
        "provider": provider_key,
        "passed_samples": pass_count,
        "sample_count": len(scored),
        "scored_samples": scored_count,
        "intent_correct_samples": intent_count,
        "avg_token_f1": avg_f1,
        "avg_wer": avg_wer,
        "avg_latency_ms": round(sum(latencies) / len(latencies), 1) if latencies else 0.0,
        "production_eligible": pass_count == len(scored) and len(scored) > 0,
    }


def _fixture_invalid_result(spec: dict[str, Any], *, text_mode: str | None = None) -> dict[str, object]:
    result = _attach_score(
        {
            "status": "fixture_invalid",
            "text": "",
            "ms": 0.0,
            "detail": list(dict(spec.get("fixture_quality") or {}).get("failed_codes") or []),
        },
        spec,
        text_mode=text_mode,
        evidence_eligible=False,
        evidence_failed_codes=["fixture_invalid"],
    )
    result["fixture_invalid"] = True
    return result


def _provider_not_authorized_result(
    spec: dict[str, Any],
    *,
    provider_key: str,
    text_mode: str | None = None,
) -> dict[str, object]:
    return _attach_score(
        {
            "status": "not_authorized",
            "text": "",
            "ms": 0.0,
            "detail": {"provider_key": provider_key, "reason": "private_audio_upload_not_authorized"},
        },
        spec,
        text_mode=text_mode,
        evidence_eligible=False,
        evidence_failed_codes=["provider_upload_not_authorized"],
    )


def _run_provider_safely(
    provider_key: str,
    callback: object,
    payload: bytes,
    spec: dict[str, Any],
    *,
    text_mode: str,
) -> dict[str, object]:
    try:
        return callback(payload, spec, text_mode=text_mode)  # type: ignore[operator]
    except Exception as exc:
        return _attach_score(
            {
                "status": "error",
                "text": "",
                "ms": 0.0,
                "detail": {
                    "provider_key": provider_key,
                    "exception": str(exc),
                },
            },
            spec,
            text_mode=text_mode,
            evidence_eligible=False,
            evidence_failed_codes=["provider_execution_error"],
        )


def _candidate_identity_failures(sample: str, *, occupied_row_ids: set[str]) -> list[str]:
    failures: list[str] = []
    if not SAFE_CANDIDATE_SAMPLE_PATTERN.fullmatch(str(sample or "")):
        failures.append("candidate_sample_invalid")
    if sample in RESERVED_CANDIDATE_SAMPLES:
        failures.append("candidate_sample_reserved")
    candidate_row_ids = {sample, f"{sample}_hostile"}
    if candidate_row_ids & occupied_row_ids:
        failures.append("candidate_sample_collision")
    return failures


def _candidate_pair_failures(
    variants: list[dict[str, Any]],
    *,
    binding: dict[str, object],
) -> list[str]:
    failures: list[str] = []
    sample = str(binding.get("sample") or "")
    expected_identities = [(sample, "captured"), (f"{sample}_hostile", "hostile")]
    actual_identities = [
        (str(item.get("sample") or ""), str(item.get("variant") or ""))
        for item in variants
    ]
    if actual_identities != expected_identities or len(set(actual_identities)) != 2:
        failures.append("captured_candidate_pair_invalid")
    source_audio_sha256 = str(binding.get("source_audio_sha256") or "")
    expected_transformations = ("identity_v1", "hostile_room_v1")
    for index, item in enumerate(variants):
        if _object(item.get("captured_candidate_binding")) != binding:
            failures.append("captured_candidate_pair_binding_mismatch")
        if str(item.get("source_fixture_sha256") or "") != source_audio_sha256:
            failures.append("captured_candidate_pair_source_sha256_mismatch")
        if index == 0 and str(item.get("fixture_sha256") or "") != source_audio_sha256:
            failures.append("captured_candidate_identity_sha256_mismatch")
        transformation = _object(item.get("transformation"))
        transformation_payload = _object(transformation.get("payload"))
        if transformation.get("contract_name") != TRANSFORMATION_RECEIPT_CONTRACT:
            failures.append("captured_candidate_transformation_contract_invalid")
        if str(transformation.get("sha256") or "") != _canonical_sha256(transformation_payload):
            failures.append("captured_candidate_transformation_sha256_mismatch")
        expected_transformation = expected_transformations[index] if index < len(expected_transformations) else ""
        if transformation_payload.get("transformation_id") != expected_transformation:
            failures.append("captured_candidate_transformation_id_mismatch")
        if str(transformation_payload.get("source_audio_sha256") or "") != source_audio_sha256:
            failures.append("captured_candidate_transformation_source_sha256_mismatch")
        if str(transformation_payload.get("output_audio_sha256") or "") != str(item.get("fixture_sha256") or ""):
            failures.append("captured_candidate_transformation_output_sha256_mismatch")
        if transformation_payload.get("duration_preserved") is not True:
            failures.append("captured_candidate_transformation_duration_not_preserved")
    return sorted(set(failures))


def _block_spec(spec: dict[str, Any], failed_codes: list[str]) -> dict[str, Any]:
    blocked = dict(spec)
    quality = _object(spec.get("fixture_quality"))
    existing = [str(item) for item in list(quality.get("failed_codes") or []) if str(item)]
    blocked["fixture_quality"] = {
        **quality,
        "status": "blocked",
        "failed_codes": sorted(set(existing + failed_codes)),
    }
    return blocked


def _provider_upload_authorized(spec: dict[str, Any], provider_key: str) -> bool:
    authorization = _object(spec.get("provider_upload_authorization"))
    return authorization.get(provider_key) is True


def _rank_providers(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    summaries = [_provider_summary(rows, key) for key in ("full_runtime", "shadow", "onemin_sample")]
    return sorted(
        summaries,
        key=lambda item: (
            int(item["passed_samples"]),
            int(item["scored_samples"]),
            int(item["intent_correct_samples"]),
            float(item["avg_token_f1"]),
            -float(item["avg_wer"]),
            -float(item["avg_latency_ms"]),
        ),
        reverse=True,
    )


def _benchmark_status(ranking: list[dict[str, object]]) -> str:
    return "pass" if any(row.get("production_eligible") for row in ranking) else "blocked"


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _safe_failed_codes(value: object) -> list[str]:
    return sorted(
        {
            code
            for code in (str(item) for item in list(value if isinstance(value, list) else []))
            if re.fullmatch(r"[a-z0-9_.:-]{1,120}", code)
        }
    )


def _safe_nonnegative_int(value: object) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError, OverflowError):
        return 0


def _safe_finite_float(value: object, *, default: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return default
    return number if math.isfinite(number) else default


def _safe_sha256(value: object) -> str:
    digest = str(value or "").lower()
    return digest if re.fullmatch(r"[a-f0-9]{64}", digest) else _sha256_text(digest)


def _safe_availability(value: dict[str, object]) -> dict[str, object]:
    cartesia = _object(value.get("cartesia"))
    credential_source = str(cartesia.get("credential_source") or "none")
    if credential_source not in {
        "none",
        "direct_env",
        "inline_json_env",
        "credential_file_env",
        "default_credential_file",
    }:
        credential_source = "unknown"
    provider_env = _object(value.get("provider_env"))
    provider_families = _object(provider_env.get("provider_families"))
    onemin_key_count = _safe_nonnegative_int(value.get("onemin_key_count"))
    onemin_max_attempts = _safe_nonnegative_int(value.get("onemin_max_key_attempts"))
    shadow_raw = str(value.get("shadow_provider") or "").strip().lower()
    external_codes = _safe_failed_codes(value.get("external_candidate_preflight_failed_codes"))
    tracked_codes = _safe_failed_codes(value.get("tracked_governance_preflight_failed_codes"))
    governance_codes = _safe_failed_codes(value.get("governance_preflight_failed_codes"))
    return {
        "providers": {
            "full_runtime": {
                "configured": bool(cartesia.get("configured") or value.get("cartesia_configured")),
                "credential_source": credential_source,
            },
            "shadow": {
                "configured": bool(shadow_raw),
                "provider_family": "blipai" if shadow_raw == "blipai" else "unknown",
            },
            "onemin_sample": {
                "configured": onemin_key_count > 0,
                "key_count": onemin_key_count,
                "max_key_attempts": onemin_max_attempts,
            },
        },
        "credential_environment": {
            "file_count": _safe_nonnegative_int(provider_env.get("file_count")),
            "loaded_count": _safe_nonnegative_int(provider_env.get("loaded_count")),
            "provider_families": {
                "cartesia": bool(provider_families.get("cartesia")),
                "onemin": bool(provider_families.get("onemin")),
                "blipai_shadow": bool(provider_families.get("blipai_shadow")),
            },
        },
        "governance_preflight": {
            "blocked": bool(governance_codes),
            "failed_codes": governance_codes,
            "external_candidate_failed_codes": external_codes,
            "tracked_fixture_failed_codes": tracked_codes,
            "captured_candidate_pair_count": 1
            if _safe_nonnegative_int(value.get("captured_candidate_pair_count")) == 1
            else 0,
        },
    }


def _safe_provider_ranking(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    safe: list[dict[str, object]] = []
    for row in rows:
        provider = str(row.get("provider") or "")
        if provider not in {"full_runtime", "shadow", "onemin_sample"}:
            continue
        safe.append(
            {
                "provider": provider,
                "passed_samples": _safe_nonnegative_int(row.get("passed_samples")),
                "sample_count": _safe_nonnegative_int(row.get("sample_count")),
                "scored_samples": _safe_nonnegative_int(row.get("scored_samples")),
                "intent_correct_samples": _safe_nonnegative_int(row.get("intent_correct_samples")),
                "avg_token_f1": _safe_finite_float(row.get("avg_token_f1"), default=0.0),
                "avg_wer": _safe_finite_float(row.get("avg_wer"), default=1.0),
                "avg_latency_ms": _safe_finite_float(row.get("avg_latency_ms"), default=0.0),
                "production_eligible": row.get("production_eligible") is True,
            }
        )
    return safe


def _safe_provider_result(provider: dict[str, object], *, text_mode: str) -> dict[str, object]:
    safe: dict[str, object] = {
        "status": _safe_provider_status(provider.get("status")),
    }
    raw_detail = provider.get("detail")
    raw_reason = provider.get("reason")
    if raw_detail or raw_reason:
        safe["detail"] = _sanitize_provider_error_detail(
            {"detail": raw_detail, "reason": raw_reason}
            if raw_reason
            else raw_detail
        )
    for field, default in (
        ("ms", 0.0),
        ("wer", 1.0),
        ("token_f1", 0.0),
        ("min_token_f1", 0.0),
        ("max_wer", 1.0),
    ):
        if field in provider:
            safe[field] = _safe_finite_float(provider.get(field), default=default)
    for field in (
        "expected_text_chars",
        "actual_text_chars",
        "required_token_count",
        "candidate_key_count",
        "sampled_keys",
    ):
        if field in provider:
            safe[field] = _safe_nonnegative_int(provider.get(field))
    for field in ("intent_correct", "usable", "passed", "fixture_invalid", "text_redacted"):
        if field in provider:
            safe[field] = provider.get(field) is True
    for field in ("expected_text_sha256", "actual_text_sha256"):
        if field in provider:
            safe[field] = _safe_sha256(provider.get(field))
    if "required_token_sha256" in provider:
        raw_token_hashes = provider.get("required_token_sha256")
        safe["required_token_sha256"] = [
            _safe_sha256(item)
            for item in list(raw_token_hashes if isinstance(raw_token_hashes, list) else [])
        ]
    evidence_status = str(provider.get("provider_evidence_status") or "blocked")
    safe["provider_evidence_status"] = evidence_status if evidence_status in {"eligible", "blocked"} else "blocked"
    safe["provider_evidence_failed_codes"] = _safe_failed_codes(
        provider.get("provider_evidence_failed_codes")
    )
    scored_source = str(provider.get("scored_text_source") or "")
    if scored_source in {"primary_transcript_text", "none"}:
        safe["scored_text_source"] = scored_source
    strategy = str(provider.get("sample_strategy") or "")
    if strategy == "primary_plus_spread_fallbacks":
        safe["sample_strategy"] = strategy
    if "transcriber" in provider:
        raw_transcriber = provider.get("transcriber")
        if isinstance(raw_transcriber, dict):
            family = str(raw_transcriber.get("family") or "unknown")
            safe["transcriber"] = {
                "family": family if family in {"cartesia", "onemin", "blipai", "memorial", "unknown"} else "unknown",
                "identifier_sha256": _safe_sha256(raw_transcriber.get("identifier_sha256")),
            }
        else:
            safe["transcriber"] = _safe_transcriber_receipt(raw_transcriber)
    safe["text_mode"] = "full" if text_mode == "full" else "redacted"
    if text_mode == "full":
        for field in ("text", "actual_text", "expected_text"):
            if field in provider:
                safe[field] = str(provider.get(field) or "")
        raw_required_tokens = provider.get("required_tokens")
        if isinstance(raw_required_tokens, list) and all(type(item) is str for item in raw_required_tokens):
            safe["required_tokens"] = list(raw_required_tokens)
    else:
        safe["text_redacted"] = True
    return safe


def _safe_fixture_quality_receipt(value: object) -> dict[str, object]:
    quality = _object(value)
    wav_format = _object(quality.get("wav_format"))
    return {
        "status": "pass" if quality.get("status") == "pass" else "blocked",
        "failed_codes": _safe_failed_codes(quality.get("failed_codes")),
        "audio_duration_seconds": _safe_finite_float(quality.get("audio_duration_seconds"), default=0.0),
        "expected_min_duration_seconds": _safe_finite_float(
            quality.get("expected_min_duration_seconds"),
            default=0.0,
        ),
        "max_duration_seconds": _safe_finite_float(
            quality.get("max_duration_seconds"),
            default=DEFAULT_MAX_AUDIO_DURATION_SECONDS,
        ),
        "wav_format": {
            "audio_format": _safe_nonnegative_int(wav_format.get("audio_format")),
            "channels": _safe_nonnegative_int(wav_format.get("channels")),
            "sample_rate_hz": _safe_nonnegative_int(wav_format.get("sample_rate_hz")),
            "sample_width_bytes": _safe_nonnegative_int(wav_format.get("sample_width_bytes")),
        },
    }


def _safe_provider_authorization_receipt(value: object) -> dict[str, bool]:
    authorization = _object(value)
    if set(authorization) != set(PROVIDER_UPLOAD_LANES) or any(
        type(authorization.get(lane)) is not bool
        for lane in PROVIDER_UPLOAD_LANES
    ):
        return {lane: False for lane in PROVIDER_UPLOAD_LANES}
    return {lane: bool(authorization[lane]) for lane in PROVIDER_UPLOAD_LANES}


def _safe_provenance_receipt(value: object) -> dict[str, object]:
    provenance = _object(value)
    synthetic = provenance.get("synthetic") is True
    external = provenance.get("external_bundle") is True
    allowed_origins = {
        APPROVED_CAPTURE_ORIGIN,
        "governed_synthetic_stt_fixture",
        "governed_tracked_captured_stt_fixture",
    }
    origin = str(provenance.get("origin") or "")
    retention = str(provenance.get("retention") or "")
    safe: dict[str, object] = {
        "origin": origin if origin in allowed_origins else "invalid",
        "speaker_consent": (
            "synthetic_fixture_no_human_speaker"
            if synthetic
            else APPROVED_SPEAKER_CONSENT
            if provenance.get("speaker_consent") == APPROVED_SPEAKER_CONSENT
            else "invalid"
        ),
        "allowed_purpose": (
            APPROVED_ALLOWED_PURPOSE
            if provenance.get("allowed_purpose") == APPROVED_ALLOWED_PURPOSE
            else "invalid"
        ),
        "retention": (
            "repo_synthetic_regression_fixture"
            if synthetic
            else retention if retention in APPROVED_RETENTION_VALUES else "invalid"
        ),
        "synthetic": synthetic,
        "accent": (
            "synthetic"
            if synthetic
            else APPROVED_ACCENT if provenance.get("accent") == APPROVED_ACCENT else "unspecified"
        ),
        "provider_upload_authorization": _safe_provider_authorization_receipt(
            provenance.get("provider_upload_authorization")
        ),
    }
    if external:
        bundle_id = str(provenance.get("bundle_id") or "")
        safe.update(
            {
                "external_bundle": True,
                "bundle_root": (
                    str(provenance.get("bundle_root"))
                    if provenance.get("bundle_root") in {"[memorial_stt_error_root]", "[external_root]"}
                    else "[invalid_root]"
                ),
                "bundle_id": bundle_id if SAFE_BUNDLE_ID_PATTERN.fullmatch(bundle_id) else "invalid_bundle_id",
                "candidate_receipt_sha256": _safe_sha256(provenance.get("candidate_receipt_sha256")),
                "candidate_binding_contract_name": (
                    CANDIDATE_BINDING_CONTRACT
                    if provenance.get("candidate_binding_contract_name") == CANDIDATE_BINDING_CONTRACT
                    else "invalid"
                ),
                "candidate_binding_sha256": _safe_sha256(provenance.get("candidate_binding_sha256")),
                "operator_ground_truth_review_binding_sha256": _safe_sha256(
                    provenance.get("operator_ground_truth_review_binding_sha256")
                ),
            }
        )
    return safe


def _safe_transformation_receipt(value: object) -> dict[str, object]:
    transformation = _object(value)
    payload = _object(transformation.get("payload"))
    transformation_id = str(payload.get("transformation_id") or "")
    safe_parameters: dict[str, object] = {}
    if transformation_id == "hostile_room_v1":
        safe_parameters = {
            "gain": 1.18,
            "echo_delay_ms": 76,
            "echo_mix": 0.22,
            "noise_cycle_pcm16": [132, -132, 66, -66],
            "speed_factor": 1.0,
        }
    elif transformation_id != "identity_v1":
        transformation_id = "invalid"
    safe_payload = {
        "contract_name": (
            TRANSFORMATION_RECEIPT_CONTRACT
            if payload.get("contract_name") == TRANSFORMATION_RECEIPT_CONTRACT
            else "invalid"
        ),
        "transformation_id": transformation_id,
        "transformation_version": _safe_nonnegative_int(payload.get("transformation_version")),
        "source_audio_sha256": _safe_sha256(payload.get("source_audio_sha256")),
        "output_audio_sha256": _safe_sha256(payload.get("output_audio_sha256")),
        "source_duration_seconds": _safe_finite_float(payload.get("source_duration_seconds"), default=0.0),
        "output_duration_seconds": _safe_finite_float(payload.get("output_duration_seconds"), default=0.0),
        "duration_preserved": payload.get("duration_preserved") is True,
        "parameters": safe_parameters,
    }
    return {
        "contract_name": (
            TRANSFORMATION_RECEIPT_CONTRACT
            if transformation.get("contract_name") == TRANSFORMATION_RECEIPT_CONTRACT
            else "invalid"
        ),
        "canonicalization": CANONICALIZATION
        if transformation.get("canonicalization") == CANONICALIZATION
        else "invalid",
        "sha256": _safe_sha256(transformation.get("sha256")),
        "payload": safe_payload,
    }


def _safe_captured_binding_receipt(value: object) -> dict[str, object]:
    binding = _object(value)
    if not binding:
        return {}
    bundle_id = str(binding.get("bundle_id") or "")
    sample = str(binding.get("sample") or "")
    return {
        "candidate_receipt_sha256": _safe_sha256(binding.get("candidate_receipt_sha256")),
        "candidate_binding_contract_name": CANDIDATE_BINDING_CONTRACT
        if binding.get("candidate_binding_contract_name") == CANDIDATE_BINDING_CONTRACT
        else "invalid",
        "candidate_binding_sha256": _safe_sha256(binding.get("candidate_binding_sha256")),
        "operator_ground_truth_review_binding_sha256": _safe_sha256(
            binding.get("operator_ground_truth_review_binding_sha256")
        ),
        "source_audio_sha256": _safe_sha256(binding.get("source_audio_sha256")),
        "bundle_id": bundle_id if SAFE_BUNDLE_ID_PATTERN.fullmatch(bundle_id) else "invalid_bundle_id",
        "sample": sample if SAFE_CANDIDATE_SAMPLE_PATTERN.fullmatch(sample) else "invalid_candidate_sample",
        "provider_upload_authorization": _safe_provider_authorization_receipt(
            binding.get("provider_upload_authorization")
        ),
    }


def _receipt_rows(rows: list[dict[str, object]], *, text_mode: str) -> list[dict[str, object]]:
    safe_rows: list[dict[str, object]] = []
    for raw_row in rows:
        row = _object(raw_row)
        sample = str(row.get("sample") or "")
        fixture = str(row.get("fixture") or "")
        variant = str(row.get("variant") or "")
        safe_row: dict[str, object] = {
            "sample": sample if SAFE_CANDIDATE_SAMPLE_PATTERN.fullmatch(sample) else "invalid_fixture_sample",
            "variant": variant if variant in {"synthetic", "captured", "hostile"} else "invalid",
            "fixture": fixture if SAFE_FIXTURE_FILE_PATTERN.fullmatch(fixture) else "invalid_fixture.wav",
            "fixture_sha256": _safe_sha256(row.get("fixture_sha256")),
            "source_fixture_sha256": _safe_sha256(row.get("source_fixture_sha256")),
            "fixture_quality": _safe_fixture_quality_receipt(row.get("fixture_quality")),
            "source_fixture_quality": _safe_fixture_quality_receipt(row.get("source_fixture_quality")),
            "transformation": _safe_transformation_receipt(row.get("transformation")),
            "provenance": _safe_provenance_receipt(row.get("provenance")),
            "captured_candidate_binding": _safe_captured_binding_receipt(
                row.get("captured_candidate_binding")
            ),
            "provider_upload_authorization": _safe_provider_authorization_receipt(
                row.get("provider_upload_authorization")
            ),
        }
        for provider_key in ("full_runtime", "shadow", "onemin_sample"):
            provider = row.get(provider_key)
            safe_row[provider_key] = _safe_provider_result(
                _object(provider),
                text_mode=text_mode,
            )
        safe_rows.append(safe_row)
    return safe_rows


def _build_report(
    *,
    rows: list[dict[str, object]],
    availability: dict[str, object],
    text_mode: str | None = None,
    captured_candidate_binding: dict[str, object] | None = None,
) -> dict[str, object]:
    public_text_mode = _benchmark_text_mode(text_mode)
    receipt_rows = _receipt_rows(rows, text_mode=public_text_mode)
    ranking = _safe_provider_ranking(_rank_providers(receipt_rows))
    fixture_blockers = sorted(
        {
            str(code)
            for row in receipt_rows
            for code in list(dict(row.get("fixture_quality") or {}).get("failed_codes") or [])
            if str(code)
        }
    )
    fixture_statuses_passed = all(
        _object(row.get("fixture_quality")).get("status") == "pass"
        for row in receipt_rows
    )
    if not fixture_statuses_passed and not fixture_blockers:
        fixture_blockers.append("fixture_quality_not_passed")
    return {
        "contract_name": "ea.memorial_stt_provider_benchmark",
        "generated_at": _utc_now(),
        "generated_by": "scripts/benchmark_memorial_stt_providers.py",
        "source_git_head": resolve_source_state_head(REPO_ROOT),
        "head_semantics": "source_state",
        "source_state_fingerprint": resolve_source_worktree_fingerprint(REPO_ROOT),
        "source_state_fingerprint_semantics": "worktree_source_files_sha256_excluding_generated_only_paths",
        "captured_candidate_binding": _safe_captured_binding_receipt(captured_candidate_binding),
        "status": _benchmark_status(ranking),
        "scoring": {
            "pass_rule": "usable transcript + required tokens present + token_f1 >= sample min + WER <= sample max",
            "raw_provider_transcript_scored": True,
            "semantic_repair_applied": False,
            "fixture_quality_rule": "ground-truth fixtures must be long enough to contain their expected transcript before provider accuracy is scored",
            "known_bad_non_empty_text_is_not_enough": True,
            "production_eligible_rule": "provider must pass every ground-truth benchmark sample and hostile variant",
            "text_mode": public_text_mode,
            "raw_transcript_fields": public_text_mode == "full",
            "redacted_text_fields": public_text_mode != "full",
            "redacted_receipt_rule": (
                "Default receipts store transcript hashes, lengths, and token hashes instead of raw expected/actual text. "
                "Set EA_MEMORIAL_STT_BENCHMARK_TEXT_MODE=full or pass --text-mode full for operator-local raw transcript diagnostics."
            ),
        },
        "fixture_quality_status": "pass" if fixture_statuses_passed and not fixture_blockers else "blocked",
        "fixture_quality_failed_codes": fixture_blockers,
        "availability": _safe_availability(availability),
        "provider_ranking": ranking,
        "rows": receipt_rows,
    }


def _redacted_report_for_stdout(report: dict[str, object]) -> dict[str, object]:
    safe = json.loads(json.dumps(report, ensure_ascii=False, allow_nan=False))
    for row in list(safe.get("rows") or []):
        if not isinstance(row, dict):
            continue
        for provider_key in ("full_runtime", "shadow", "onemin_sample"):
            provider = row.get(provider_key)
            if not isinstance(provider, dict):
                continue
            for field in ("text", "actual_text", "expected_text", "required_tokens"):
                provider.pop(field, None)
            provider["text_redacted"] = True
            provider["text_mode"] = "redacted"
    scoring = dict(safe.get("scoring") or {})
    scoring["text_mode"] = "redacted"
    scoring["raw_transcript_fields"] = False
    scoring["redacted_text_fields"] = True
    safe["scoring"] = scoring
    safe["stdout_redacted"] = True
    return safe


def _write_report(path: Path, report: dict[str, object], *, contains_full_text: bool) -> None:
    reservation = _prepare_atomic_json_output(
        path,
        contains_full_text=contains_full_text,
        repo_root=REPO_ROOT,
    )
    try:
        _commit_atomic_json_output(reservation, report)
    finally:
        _abort_atomic_json_output(reservation)


def _exit_code_for_report(report: dict[str, object], *, require_production_eligible: bool) -> int:
    if require_production_eligible and str(report.get("status") or "") != "pass":
        return 2
    return 0


def _blocked_benchmark_receipt(failed_code: str) -> dict[str, object]:
    safe_code = failed_code if failed_code in {
        "benchmark_precommit_failed",
        "full_text_repo_output_forbidden",
        "output_commit_failed",
        "output_parent_identity_changed",
        "output_parent_not_directory",
        "output_parent_unsafe",
        "output_preflight_failed",
        "output_repo_boundary_unverifiable",
        "output_target_name_invalid",
        "output_target_stat_failed",
        "output_target_unsafe",
        "output_temp_reservation_failed",
    } else "benchmark_precommit_failed"
    return {
        "contract_name": "ea.memorial_stt_provider_benchmark",
        "status": "blocked",
        "failed_codes": [safe_code],
        "stdout_redacted": True,
    }


def main() -> int:
    import argparse
    parser = argparse.ArgumentParser(description="Benchmark memorial STT providers against ground-truth captured fixtures.")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--require-production-eligible",
        action="store_true",
        help="Exit non-zero unless at least one provider passes every benchmark sample.",
    )
    parser.add_argument(
        "--text-mode",
        choices=("redacted", "full"),
        default=None,
        help="Controls transcript text in the receipt. Defaults to EA_MEMORIAL_STT_BENCHMARK_TEXT_MODE or redacted.",
    )
    parser.add_argument(
        "--env-file",
        action="append",
        type=Path,
        default=None,
        help="Provider env file to load before probing providers. Defaults to .env when present.",
    )
    parser.add_argument(
        "--no-local-env",
        action="store_true",
        help="Do not load local provider env files before probing providers.",
    )
    parser.add_argument(
        "--captured-candidate-bundle-dir",
        type=Path,
        default=None,
        help="Optional private STT error bundle to include without copying private audio into repo fixtures.",
    )
    parser.add_argument(
        "--captured-candidate-receipt",
        type=Path,
        default=None,
        help="Exact redacted candidate receipt generated by materialize_memorial_stt_fixture_candidate.py.",
    )
    parser.add_argument(
        "--captured-candidate-ground-truth-review",
        type=Path,
        default=None,
        help="Private external 0600 non-symlink operator ground-truth review JSON bound by the candidate receipt.",
    )
    parser.add_argument("--captured-candidate-allow-external-root", action="store_true")
    args = parser.parse_args()
    text_mode = _benchmark_text_mode(args.text_mode)
    if text_mode == "full" and _is_relative_to(args.output, REPO_ROOT):
        print(json.dumps({
            "contract_name": "ea.memorial_stt_provider_benchmark",
            "status": "blocked",
            "failed_codes": ["full_text_repo_output_forbidden"],
            "stdout_redacted": True,
        }, ensure_ascii=False, indent=2, allow_nan=False))
        return 2
    captured_args = (
        args.captured_candidate_bundle_dir,
        args.captured_candidate_receipt,
        args.captured_candidate_ground_truth_review,
    )
    if any(value is not None for value in captured_args) and not all(value is not None for value in captured_args):
        parser.error(
            "--captured-candidate-bundle-dir, --captured-candidate-receipt, and "
            "--captured-candidate-ground-truth-review must be supplied together"
        )
    try:
        output_reservation = _prepare_atomic_json_output(
            args.output,
            contains_full_text=text_mode == "full",
            repo_root=REPO_ROOT,
        )
    except Exception as exc:
        blocked = _blocked_benchmark_receipt(_safe_atomic_output_preflight_failure_code(exc))
        print(json.dumps(blocked, ensure_ascii=False, indent=2, allow_nan=False))
        return 2
    try:
        env_file_report = {"file_count": 0, "loaded_names": [], "loaded_count": 0}
        if not bool(args.no_local_env):
            env_file_report = _load_provider_env_files(tuple(args.env_file or DEFAULT_PROVIDER_ENV_FILES))

        samples: list[dict[str, Any]] = []
        tracked_specs = _fixture_specs()
        occupied_row_ids = {
            row_id
            for spec in tracked_specs
            for row_id in (str(spec.get("sample") or ""), f"{spec.get('sample')}_hostile")
            if row_id
        }
        base_specs = [spec for spec in tracked_specs if spec.get("sample") != "technical_retry"]
        tracked_preflight_failed_codes = sorted(
            {
                str(code)
                for spec in tracked_specs
                for code in list(spec.get("_governance_preflight_failed_codes") or [])
                if str(code)
            }
        )
        captured_candidate_binding: dict[str, object] = {}
        captured_candidate_variants: list[dict[str, Any]] = []
        external_preflight_failed_codes: list[str] = []
        if args.captured_candidate_bundle_dir is not None:
            external_spec = _external_captured_candidate_spec(
                bundle_dir=args.captured_candidate_bundle_dir,
                candidate_receipt_path=args.captured_candidate_receipt,
                ground_truth_review_path=args.captured_candidate_ground_truth_review,
                allow_external_root=bool(args.captured_candidate_allow_external_root),
            )
            captured_candidate_binding = dict(external_spec.get("captured_candidate_binding") or {})
            identity_failures = _candidate_identity_failures(
                str(external_spec.get("sample") or ""),
                occupied_row_ids=occupied_row_ids,
            )
            if identity_failures:
                external_spec = _block_spec(external_spec, identity_failures)
            captured_candidate_variants = _sample_variants(external_spec)
            pair_failures = _candidate_pair_failures(
                captured_candidate_variants,
                binding=captured_candidate_binding,
            )
            if pair_failures:
                captured_candidate_variants = [
                    _block_spec(spec, pair_failures)
                    for spec in captured_candidate_variants
                ]
            external_preflight_failed_codes = sorted(
                {
                    str(code)
                    for spec in captured_candidate_variants
                    for code in list(_object(spec.get("fixture_quality")).get("failed_codes") or [])
                    if str(code)
                }
            )
            if any(
                _object(spec.get("fixture_quality")).get("status") != "pass"
                for spec in captured_candidate_variants
            ):
                external_preflight_failed_codes = sorted(
                    set(external_preflight_failed_codes + ["external_candidate_fixture_quality_not_passed"])
                )
        for spec in base_specs:
            samples.extend(_sample_variants(spec))
        samples.extend(captured_candidate_variants)
        cartesia_probe = _cartesia_credential_probe()
        availability = {
            "shadow_provider": public_memorials._text(
                os.environ.get("EA_MEMORIAL_SHADOW_STT_PROVIDER"),
                "blipai",
            )
            or "blipai",
            "cartesia_configured": bool(cartesia_probe.get("configured")),
            "cartesia_default_credential_file_present": _cartesia_default_credential_file_present(),
            "cartesia": cartesia_probe,
            "onemin_key_count": len(product_service._pocket_onemin_api_keys()),
            "onemin_max_key_attempts": public_memorials._memorial_onemin_max_key_attempts(),
            "provider_env": _provider_env_receipt_summary(env_file_report, cartesia_probe=cartesia_probe),
            "provider_calls_blocked_by_external_candidate_preflight": bool(external_preflight_failed_codes),
            "external_candidate_preflight_failed_codes": external_preflight_failed_codes,
            "tracked_governance_preflight_failed_codes": tracked_preflight_failed_codes,
            "captured_candidate_pair_count": 1 if captured_candidate_variants and not external_preflight_failed_codes else 0,
        }
        if captured_candidate_variants:
            immediate_freshness_failures = _review_freshness_failures(
                captured_candidate_variants[0].get("_ground_truth_reviewed_at"),
                now=datetime.now(UTC),
            )
            if immediate_freshness_failures:
                external_preflight_failed_codes = sorted(
                    set(external_preflight_failed_codes + immediate_freshness_failures)
                )
                availability["provider_calls_blocked_by_external_candidate_preflight"] = True
                availability["external_candidate_preflight_failed_codes"] = external_preflight_failed_codes
                availability["captured_candidate_pair_count"] = 0
        provider_preflight_failed_codes = sorted(
            set(external_preflight_failed_codes + tracked_preflight_failed_codes)
        )
        availability["provider_calls_blocked_by_governance_preflight"] = bool(provider_preflight_failed_codes)
        availability["governance_preflight_failed_codes"] = provider_preflight_failed_codes
        rows = []
        runtime_freshness_failed_codes: set[str] = set()
        for spec in samples:
            payload = bytes(spec["payload"])
            fixture_quality = dict(spec.get("fixture_quality") or {})
            per_upload_freshness_failures = (
                _review_freshness_failures(
                    spec.get("_ground_truth_reviewed_at"),
                    now=datetime.now(UTC),
                )
                if spec.get("captured_candidate_binding")
                else []
            )
            runtime_freshness_failed_codes.update(per_upload_freshness_failures)
            if provider_preflight_failed_codes or per_upload_freshness_failures:
                effective_preflight_failures = sorted(
                    set(provider_preflight_failed_codes + per_upload_freshness_failures)
                )
                globally_blocked_spec = _block_spec(spec, effective_preflight_failures)
                fixture_quality = dict(globally_blocked_spec.get("fixture_quality") or {})
                blocked_result = _fixture_invalid_result(globally_blocked_spec, text_mode=text_mode)
                shadow = dict(blocked_result)
                onemin_sample = dict(blocked_result)
                full_runtime = dict(blocked_result)
            elif fixture_quality.get("status") != "pass":
                blocked_result = _fixture_invalid_result(spec, text_mode=text_mode)
                shadow = dict(blocked_result)
                onemin_sample = dict(blocked_result)
                full_runtime = dict(blocked_result)
            else:
                shadow = (
                    _run_provider_safely("shadow", _run_shadow, payload, spec, text_mode=text_mode)
                    if _provider_upload_authorized(spec, "shadow")
                    else _provider_not_authorized_result(spec, provider_key="shadow", text_mode=text_mode)
                )
                onemin_sample = (
                    _run_provider_safely(
                        "onemin_sample",
                        _run_onemin_sample,
                        payload,
                        spec,
                        text_mode=text_mode,
                    )
                    if _provider_upload_authorized(spec, "onemin_sample")
                    else _provider_not_authorized_result(spec, provider_key="onemin_sample", text_mode=text_mode)
                )
                full_runtime = (
                    _run_provider_safely(
                        "full_runtime",
                        _run_full_runtime,
                        payload,
                        spec,
                        text_mode=text_mode,
                    )
                    if _provider_upload_authorized(spec, "full_runtime")
                    else _provider_not_authorized_result(spec, provider_key="full_runtime", text_mode=text_mode)
                )
            rows.append(
                {
                    "sample": spec["sample"],
                    "variant": spec["variant"],
                    "fixture": spec["file"],
                    "fixture_sha256": spec["fixture_sha256"],
                    "source_fixture_sha256": spec["source_fixture_sha256"],
                    "fixture_quality": fixture_quality,
                    "source_fixture_quality": spec["source_fixture_quality"],
                    "transformation": spec["transformation"],
                    "provenance": spec["provenance"],
                    "captured_candidate_binding": dict(spec.get("captured_candidate_binding") or {}),
                    "provider_upload_authorization": dict(spec.get("provider_upload_authorization") or {}),
                    "shadow": shadow,
                    "onemin_sample": onemin_sample,
                    "full_runtime": full_runtime,
                }
            )
        if runtime_freshness_failed_codes:
            external_preflight_failed_codes = sorted(
                set(external_preflight_failed_codes) | runtime_freshness_failed_codes
            )
            provider_preflight_failed_codes = sorted(
                set(provider_preflight_failed_codes) | runtime_freshness_failed_codes
            )
            availability["external_candidate_preflight_failed_codes"] = external_preflight_failed_codes
            availability["governance_preflight_failed_codes"] = provider_preflight_failed_codes
            availability["provider_calls_blocked_by_governance_preflight"] = True
            availability["captured_candidate_pair_count"] = 0
        report = _build_report(
            rows=rows,
            availability=availability,
            text_mode=text_mode,
            captured_candidate_binding=captured_candidate_binding,
        )
        try:
            _commit_atomic_json_output(output_reservation, report)
        except Exception:
            _abort_atomic_json_output(output_reservation)
            blocked = _blocked_benchmark_receipt("output_commit_failed")
            print(json.dumps(blocked, ensure_ascii=False, indent=2, allow_nan=False))
            return 2
        finally:
            _abort_atomic_json_output(output_reservation)
        print(json.dumps(_redacted_report_for_stdout(report), ensure_ascii=False, indent=2, allow_nan=False))
        return _exit_code_for_report(report, require_production_eligible=bool(args.require_production_eligible))
    except Exception:
        blocked = _blocked_benchmark_receipt("benchmark_precommit_failed")
        try:
            _commit_atomic_json_output(output_reservation, blocked)
        except Exception:
            blocked = _blocked_benchmark_receipt("output_commit_failed")
        print(json.dumps(blocked, ensure_ascii=False, indent=2, allow_nan=False))
        return 2
    finally:
        _abort_atomic_json_output(output_reservation)


if __name__ == "__main__":
    raise SystemExit(main())
