#!/usr/bin/env python3
from __future__ import annotations

import io
import hashlib
import json
import os
import re
import struct
import sys
import time
import unicodedata
import wave
from pathlib import Path
from typing import Any

from fastapi import HTTPException

REPO_ROOT = Path(__file__).resolve().parents[1]
EA_APP_ROOT = REPO_ROOT / "ea"
if str(EA_APP_ROOT) not in sys.path:
    sys.path.insert(0, str(EA_APP_ROOT))

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
    loaded_files: list[str] = []
    loaded_names: list[str] = []
    for path in paths:
        try:
            candidate = path if path.is_absolute() else REPO_ROOT / path
        except Exception:
            continue
        if not candidate.exists():
            continue
        loaded_files.append(candidate.relative_to(REPO_ROOT).as_posix() if candidate.is_relative_to(REPO_ROOT) else candidate.as_posix())
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
        "files": loaded_files,
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
        "files": list(report.get("files") or []),
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
    for raw_path in getattr(public_memorials, "_CARTESIA_DEFAULT_CREDENTIAL_FILES", ()):
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
        display_candidate = next((candidate for candidate in candidates if candidate.is_relative_to(REPO_ROOT)), None)
        if display_candidate is None and candidates:
            display_candidate = candidates[0]
        default_files.append(
            {
                "path": str(raw_path),
                "resolved_path": _display_path(display_candidate) if display_candidate is not None else "",
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
        else "Configure Cartesia with an env key, inline JSON, credential-file env, or ignored config/cartesia.local.json.",
    }


def _sanitize_provider_error_detail(value: object) -> object:
    if isinstance(value, list):
        return [_sanitize_provider_error_detail(item) for item in value]
    if isinstance(value, tuple):
        return [_sanitize_provider_error_detail(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _sanitize_provider_error_detail(item) for key, item in value.items()}
    text = str(value or "").strip()
    if not text:
        return ""
    lowered = text.lower()
    if "insufficient_credits" in lowered:
        status_match = re.search(r"(onemin_[a-z_]+_http_\d+)", text, flags=re.IGNORECASE)
        required_match = re.search(r"requires\s+(\d+)\s+credits", text, flags=re.IGNORECASE)
        available_match = re.search(r"(?:only\s+has|has)\s+(\d+)\s+credits", text, flags=re.IGNORECASE)
        parts = [status_match.group(1) if status_match else "onemin_http_error", "INSUFFICIENT_CREDITS"]
        if required_match:
            parts.append(f"required_{required_match.group(1)}")
        if available_match:
            parts.append(f"available_{available_match.group(1)}")
        return ":".join(parts)
    text = re.sub(r"sk[_-][A-Za-z0-9_-]{8,}", "[secret]", text)
    text = re.sub(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", "[email]", text)
    text = re.sub(r"https?://[^\s\"')]+", "[url]", text)
    return text[:180]


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


def _expected_min_duration_seconds(expected_text: str) -> float:
    token_count = len(re.findall(r"[\w]+", str(expected_text or ""), flags=re.UNICODE))
    if token_count <= 0:
        return 0.0
    # Lenient lower bound: about 215 wpm plus a small capture margin.
    return round(max(0.8, token_count * 0.28), 3)


def _fixture_quality(*, payload: bytes, expected_text: str, synthetic: bool) -> dict[str, object]:
    duration_seconds = _wav_duration_seconds(payload)
    min_duration_seconds = _expected_min_duration_seconds(expected_text)
    failures: list[str] = []
    if duration_seconds <= 0:
        failures.append("audio_duration_missing")
    if min_duration_seconds and duration_seconds < min_duration_seconds:
        failures.append("audio_too_short_for_expected_text")
    if not bool(synthetic) and duration_seconds < 0.8:
        failures.append("captured_audio_too_short")
    return {
        "status": "pass" if not failures else "blocked",
        "failed_codes": failures,
        "audio_duration_seconds": duration_seconds,
        "expected_min_duration_seconds": min_duration_seconds,
    }


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
    path = fixture_root / str(entry["file"])
    payload = path.read_bytes()
    digest = _sha256_bytes(payload)
    if digest != str(entry.get("sha256") or "").strip():
        raise RuntimeError(f"stt_fixture_hash_mismatch:{entry['file']}")
    tokens = [str(token).strip() for token in list(entry.get("required_tokens") or []) if str(token).strip()]
    if not tokens:
        raise RuntimeError(f"stt_fixture_required_tokens_missing:{entry['sample']}")
    expected_text = str(entry["expected_text"]).strip()
    quality = _fixture_quality(
        payload=payload,
        expected_text=expected_text,
        synthetic=bool(entry.get("synthetic")),
    )
    return {
        "sample": str(entry["sample"]),
        "file": str(entry["file"]),
        "payload": payload,
        "expected_text": expected_text,
        "required_tokens": tokens,
        "language": str(entry.get("language") or "de").strip() or "de",
        "min_token_f1": float(entry.get("min_token_f1") or 0.6),
        "max_wer": float(entry.get("max_wer") or 0.5),
        "fixture_sha256": digest,
        "fixture_quality": quality,
        "provenance": {
            "origin": str(entry.get("origin") or "").strip(),
            "speaker_consent": str(entry.get("speaker_consent") or "").strip(),
            "allowed_purpose": str(entry.get("allowed_purpose") or "").strip(),
            "retention": str(entry.get("retention") or "").strip(),
            "synthetic": bool(entry.get("synthetic")),
            "accent": str(entry.get("accent") or "").strip(),
        },
    }


def _fixture_specs() -> list[dict[str, Any]]:
    manifest = _load_fixture_manifest()
    return [_validate_fixture_entry(dict(entry)) for entry in list(manifest.get("fixtures") or []) if isinstance(entry, dict)]


def _external_captured_candidate_spec(
    *,
    bundle_dir: Path,
    sample: str,
    expected_text: str,
    required_tokens: list[str],
    speaker_consent: str,
    origin: str,
    accent: str = "Austrian German",
    allowed_purpose: str = "memorial_stt_regression_and_provider_bakeoff",
    retention: str = "private_captured_regression_candidate",
    min_token_f1: float = 0.55,
    max_wer: float = 0.55,
    allow_external_root: bool = False,
    bundle_root: Path = DEFAULT_STT_ERROR_LOG_ROOT,
    max_bytes: int = DEFAULT_MAX_EXTERNAL_CANDIDATE_BYTES,
) -> dict[str, Any]:
    bundle_dir = bundle_dir.expanduser()
    failures: list[str] = []
    if not sample.strip():
        failures.append("sample_missing")
    if not expected_text.strip():
        failures.append("expected_text_missing")
    tokens = [str(token).strip() for token in required_tokens if str(token).strip()]
    if not tokens:
        failures.append("required_tokens_missing")
    if not speaker_consent.strip():
        failures.append("speaker_consent_missing")
    if not allow_external_root and not _is_relative_to(bundle_dir, bundle_root):
        failures.append("bundle_not_under_memorial_stt_error_root")
    path = bundle_dir / "input.wav"
    if not path.is_file():
        failures.append("input_wav_missing")
        payload = b""
    else:
        byte_count = path.stat().st_size
        if byte_count > max_bytes:
            failures.append("input_wav_too_large")
            payload = b""
        else:
            payload = path.read_bytes()
    digest = _sha256_bytes(payload) if payload else ""
    quality = _fixture_quality(payload=payload, expected_text=expected_text, synthetic=False) if payload else {
        "status": "blocked",
        "failed_codes": ["audio_missing"],
        "audio_duration_seconds": 0.0,
        "expected_min_duration_seconds": _expected_min_duration_seconds(expected_text),
    }
    failures.extend(str(code) for code in list(quality.get("failed_codes") or []) if str(code))
    if failures:
        quality = {
            **quality,
            "status": "blocked",
            "failed_codes": sorted(set(failures)),
        }
    return {
        "sample": sample.strip(),
        "file": f"[private_bundle]/{bundle_dir.name}/input.wav",
        "payload": payload,
        "expected_text": expected_text.strip(),
        "required_tokens": tokens,
        "language": "de",
        "min_token_f1": float(min_token_f1),
        "max_wer": float(max_wer),
        "fixture_sha256": digest,
        "fixture_quality": quality,
        "provenance": {
            "origin": origin.strip(),
            "speaker_consent": speaker_consent.strip(),
            "allowed_purpose": allowed_purpose.strip(),
            "retention": retention.strip(),
            "synthetic": False,
            "accent": accent.strip(),
            "external_bundle": True,
            "bundle_root": "[memorial_stt_error_root]" if _is_relative_to(bundle_dir, bundle_root) else "[external_root]",
            "bundle_id": bundle_dir.name,
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
    factor = 1.35
    target_len = max(1, int(len(mixed) / factor))
    sped = [mixed[min(len(mixed) - 1, int(index * factor))] for index in range(target_len)]
    return _wav_from_samples(sped, sample_rate=sample_rate)


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
    return all(_tokens(token)[0] in actual for token in required_tokens if _tokens(token))


def _usable(text: str) -> bool:
    repaired = public_memorials._repair_memorial_transcript_text(text)
    return bool(repaired) and not public_memorials._is_known_bad_memorial_subtitle_transcript(repaired)


def _benchmark_transcript_text(value: object) -> str:
    text = public_memorials._repair_memorial_transcript_text(value)
    if text.startswith("{") and text.endswith("}"):
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            parsed = {}
        if isinstance(parsed, dict):
            text = public_memorials._repair_memorial_transcript_text(
                product_service._extract_transcript_text(parsed.get("text"))
                or product_service._extract_transcript_text(parsed)
                or text
            )
    return text


def _score_text(text: str, spec: dict[str, Any], *, text_mode: str | None = None) -> dict[str, object]:
    public_text_mode = _benchmark_text_mode(text_mode)
    repaired = _benchmark_transcript_text(text)
    expected = str(spec.get("expected_text") or "").strip()
    required_tokens = [str(token) for token in list(spec.get("required_tokens") or [])]
    wer = _word_error_rate(expected, repaired)
    f1 = _token_f1(expected, repaired)
    intent_correct = _required_tokens_present(required_tokens, repaired)
    usable = _usable(repaired)
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
        "actual_text_chars": len(repaired),
        "actual_text_sha256": _sha256_text(repaired),
        "required_token_count": len(required_tokens),
        "required_token_sha256": [_sha256_text(" ".join(_tokens(token))) for token in required_tokens],
    }
    if public_text_mode == "full":
        score.update(
            {
                "expected_text": expected,
                "required_tokens": required_tokens,
                "actual_text": repaired,
            }
        )
    else:
        score["text_redacted"] = True
    return score


def _attach_score(result: dict[str, object], spec: dict[str, Any], *, text_mode: str | None = None) -> dict[str, object]:
    public_text_mode = _benchmark_text_mode(text_mode)
    scored = dict(result)
    for detail_key in ("detail", "reason"):
        if detail_key in scored:
            scored[detail_key] = _sanitize_provider_error_detail(scored.get(detail_key))
    raw_text = str(scored.get("text") or "")
    scored.update(_score_text(raw_text, spec, text_mode=public_text_mode))
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
    text = public_memorials._repair_memorial_transcript_text(result.get("transcript_text"))
    return _attach_score({
        "status": result.get("status"),
        "text": text,
        "ms": round(elapsed_ms, 1),
        "reason": result.get("reason", ""),
    }, spec, text_mode=text_mode)


def _run_onemin_sample(payload: bytes, spec: dict[str, Any], *, text_mode: str | None = None) -> dict[str, object]:
    candidate_keys = product_service._pocket_onemin_api_keys()
    keys = public_memorials._memorial_onemin_available_keys(tuple(candidate_keys))
    if not keys:
        return {"status": "unavailable", "detail": "no_keys", "candidate_key_count": len(candidate_keys)}
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
            transcribed = product_service._onemin_speech_to_text(api_key=api_key, audio_path=audio_path, language="de")
            ai_record = dict(transcribed.get("aiRecord") or {}) if isinstance(transcribed.get("aiRecord"), dict) else {}
            ai_detail = dict(ai_record.get("aiRecordDetail") or {}) if isinstance(ai_record.get("aiRecordDetail"), dict) else {}
            text = _benchmark_transcript_text(
                product_service._extract_transcript_text(ai_detail.get("responseObject"))
                or product_service._extract_transcript_text(ai_detail.get("resultObject"))
            )
            elapsed_ms = (time.perf_counter() - started) * 1000.0
            return _attach_score({
                "status": "known_bad" if public_memorials._is_known_bad_memorial_subtitle_transcript(text) else ("ok" if text else "empty"),
                "text": text,
                "ms": round(elapsed_ms, 1),
            }, spec, text_mode=text_mode)
        except Exception as exc:
            errors.append(str(_sanitize_provider_error_detail(str(exc))))
    return {
        "status": "error",
        "detail": _sanitize_provider_error_detail(errors[:3]),
        "sampled_keys": len(keys),
        "candidate_key_count": len(candidate_keys),
        "sample_strategy": "primary_plus_spread_fallbacks",
    }


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
            "transcriber": "",
            "detail": str(exc.detail),
        }, spec, text_mode=text_mode)
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    text = public_memorials._repair_memorial_transcript_text(result.get("transcript_text"))
    return _attach_score({
        "status": result.get("transcription_status"),
        "text": text,
        "ms": round(elapsed_ms, 1),
        "transcriber": result.get("transcriber", ""),
        "detail": result.get("detail", ""),
    }, spec, text_mode=text_mode)


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
    )
    result["fixture_invalid"] = True
    return result


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


def _build_report(*, rows: list[dict[str, object]], availability: dict[str, object], text_mode: str | None = None) -> dict[str, object]:
    ranking = _rank_providers(rows)
    public_text_mode = _benchmark_text_mode(text_mode)
    fixture_blockers = sorted(
        {
            str(code)
            for row in rows
            for code in list(dict(row.get("fixture_quality") or {}).get("failed_codes") or [])
            if str(code)
        }
    )
    return {
        "contract_name": "ea.memorial_stt_provider_benchmark",
        "status": _benchmark_status(ranking),
        "scoring": {
            "pass_rule": "usable transcript + required tokens present + token_f1 >= sample min + WER <= sample max",
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
        "fixture_quality_status": "pass" if not fixture_blockers else "blocked",
        "fixture_quality_failed_codes": fixture_blockers,
        "availability": availability,
        "provider_ranking": ranking,
        "rows": rows,
    }


def _exit_code_for_report(report: dict[str, object], *, require_production_eligible: bool) -> int:
    if require_production_eligible and str(report.get("status") or "") != "pass":
        return 2
    return 0


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
    parser.add_argument("--captured-candidate-sample", default="real_room_retry_candidate")
    parser.add_argument("--captured-candidate-expected-text", default="")
    parser.add_argument("--captured-candidate-required-token", action="append", default=[])
    parser.add_argument("--captured-candidate-speaker-consent", default="")
    parser.add_argument(
        "--captured-candidate-origin",
        default="Captured Manfred memorial STT error bundle with operator-supplied ground-truth transcript.",
    )
    parser.add_argument("--captured-candidate-allow-external-root", action="store_true")
    args = parser.parse_args()
    text_mode = _benchmark_text_mode(args.text_mode)
    env_file_report = {"files": [], "loaded_names": [], "loaded_count": 0}
    if not bool(args.no_local_env):
        env_file_report = _load_provider_env_files(tuple(args.env_file or DEFAULT_PROVIDER_ENV_FILES))

    samples: list[dict[str, Any]] = []
    base_specs = _fixture_specs()
    if args.captured_candidate_bundle_dir is not None:
        base_specs.append(
            _external_captured_candidate_spec(
                bundle_dir=args.captured_candidate_bundle_dir,
                sample=str(args.captured_candidate_sample),
                expected_text=str(args.captured_candidate_expected_text),
                required_tokens=[str(item) for item in list(args.captured_candidate_required_token or [])],
                speaker_consent=str(args.captured_candidate_speaker_consent),
                origin=str(args.captured_candidate_origin),
                allow_external_root=bool(args.captured_candidate_allow_external_root),
            )
        )
    for spec in base_specs:
        if spec["sample"] == "technical_retry":
            continue
        base_variant = "synthetic" if bool(dict(spec.get("provenance") or {}).get("synthetic")) else "captured"
        samples.append({**spec, "variant": base_variant, "payload": spec["payload"]})
        samples.append({**spec, "sample": f"{spec['sample']}_hostile", "variant": "hostile", "payload": _hostile(spec["payload"])})
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
    }
    rows = []
    for spec in samples:
        payload = bytes(spec["payload"])
        fixture_quality = dict(spec.get("fixture_quality") or {})
        if fixture_quality.get("status") != "pass":
            blocked_result = _fixture_invalid_result(spec, text_mode=text_mode)
            shadow = dict(blocked_result)
            onemin_sample = dict(blocked_result)
            full_runtime = dict(blocked_result)
        else:
            shadow = _run_shadow(payload, spec, text_mode=text_mode)
            onemin_sample = _run_onemin_sample(payload, spec, text_mode=text_mode)
            full_runtime = _run_full_runtime(payload, spec, text_mode=text_mode)
        rows.append(
            {
                "sample": spec["sample"],
                "variant": spec["variant"],
                "fixture": spec["file"],
                "fixture_sha256": spec["fixture_sha256"],
                "fixture_quality": fixture_quality,
                "provenance": spec["provenance"],
                "shadow": shadow,
                "onemin_sample": onemin_sample,
                "full_runtime": full_runtime,
            }
        )
    report = _build_report(rows=rows, availability=availability, text_mode=text_mode)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return _exit_code_for_report(report, require_production_eligible=bool(args.require_production_eligible))


if __name__ == "__main__":
    raise SystemExit(main())
