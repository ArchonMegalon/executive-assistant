#!/usr/bin/env python3
from __future__ import annotations

import argparse
import errno
import hashlib
import io
import json
import math
import os
import re
import secrets
import stat
import unicodedata
import wave
from datetime import UTC, datetime, timedelta
from pathlib import Path

try:
    from scripts.source_state_head import resolve_source_state_head
    from scripts.source_state_head import resolve_source_worktree_fingerprint
except ModuleNotFoundError:  # pragma: no cover - script execution path
    from source_state_head import resolve_source_state_head
    from source_state_head import resolve_source_worktree_fingerprint


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MAX_AUDIO_BYTES = 25 * 1024 * 1024
DEFAULT_MAX_AUDIO_DURATION_SECONDS = 120.0
DEFAULT_MAX_GROUND_TRUTH_REVIEW_BYTES = 64 * 1024
CANDIDATE_CONTRACT_VERSION = 3
CANDIDATE_BINDING_CONTRACT = "ea.memorial_stt_fixture_candidate_binding.v2"
GROUND_TRUTH_REVIEW_CONTRACT = "ea.memorial_stt_operator_ground_truth_review.v2"
GROUND_TRUTH_REVIEW_BINDING_CONTRACT = "ea.memorial_stt_operator_ground_truth_review_binding.v2"
CANONICALIZATION = "json_utf8_sorted_keys_compact_v1"
APPROVED_SPEAKER_CONSENT = "operator_attested_for_private_stt_regression"
APPROVED_ALLOWED_PURPOSE = "memorial_stt_regression_and_provider_bakeoff"
APPROVED_RETENTION_VALUES = frozenset(
    {
        "private_captured_regression_candidate",
        "private_repo_captured_regression_fixture",
    }
)
PROVIDER_UPLOAD_LANES = ("full_runtime", "shadow", "onemin_sample")
RESERVED_CANDIDATE_SAMPLES = frozenset({"technical_retry"})
SAFE_CANDIDATE_SAMPLE_PATTERN = re.compile(r"[a-z0-9][a-z0-9_-]{0,63}")
SAFE_BUNDLE_ID_PATTERN = re.compile(r"[a-z0-9][a-z0-9_-]{0,95}")
SAFE_FIXTURE_FILE_PATTERN = re.compile(r"[a-z0-9][a-z0-9_.-]{0,95}\.wav")
APPROVED_CAPTURE_ORIGIN = "captured_operator_manfred_memorial_stt_error_bundle"
APPROVED_LANGUAGE = "de"
APPROVED_ACCENT = "Austrian German"
ALLOWED_ERROR_EVENT_CODES = frozenset({"realtime_audio_turn"})
ALLOWED_ERROR_REASON_CODES = frozenset(
    {
        "empty_transcript",
        "generic",
        "generic_fallback_answer",
        "known_bad_transcript",
        "provider_error",
        "timeout",
        "unavailable",
    }
)
MAX_REVIEW_AGE = timedelta(hours=72)
MAX_REVIEW_FUTURE_SKEW = timedelta(minutes=5)
GROUND_TRUTH_REVIEW_FIELDS = frozenset(
    {
        "contract_name",
        "status",
        "reviewed_at",
        "reviewer_authority",
        "audio_sha256",
        "bundle_id",
        "sample",
        "expected_text",
        "required_tokens",
        "speaker_consent",
        "allowed_purpose",
        "retention",
        "language",
        "accent",
        "provider_upload_authorization",
    }
)
SAFE_ATOMIC_OUTPUT_PREFLIGHT_FAILURE_CODES = frozenset(
    {
        "full_text_repo_output_forbidden",
        "output_parent_identity_changed",
        "output_parent_not_directory",
        "output_parent_unsafe",
        "output_repo_boundary_unverifiable",
        "output_target_name_invalid",
        "output_target_stat_failed",
        "output_target_unsafe",
        "output_temp_reservation_failed",
    }
)


def _default_bundle_root() -> Path:
    configured = str(os.getenv("EA_MEMORIAL_STT_ERROR_LOG_DIR") or "").strip()
    return Path(configured).expanduser() if configured else ROOT / ".codex-studio" / "published" / "memorial_stt_errors"


def _default_output() -> Path:
    configured = str(os.getenv("EA_MEMORIAL_STT_FIXTURE_CANDIDATE_OUTPUT") or "").strip()
    return Path(configured).expanduser() if configured else ROOT / ".codex-studio/published/memorial_stt_fixture_candidate.generated.json"


def _default_max_audio_bytes() -> int:
    configured = str(os.getenv("EA_MEMORIAL_STT_FIXTURE_CANDIDATE_MAX_AUDIO_BYTES") or "").strip()
    if not configured:
        return DEFAULT_MAX_AUDIO_BYTES
    try:
        value = int(configured)
    except ValueError:
        return DEFAULT_MAX_AUDIO_BYTES
    return value if value > 0 else DEFAULT_MAX_AUDIO_BYTES


def _default_max_audio_duration_seconds() -> float:
    configured = str(os.getenv("EA_MEMORIAL_STT_FIXTURE_CANDIDATE_MAX_AUDIO_SECONDS") or "").strip()
    if not configured:
        return DEFAULT_MAX_AUDIO_DURATION_SECONDS
    try:
        value = float(configured)
    except ValueError:
        return DEFAULT_MAX_AUDIO_DURATION_SECONDS
    return (
        value
        if math.isfinite(value) and 0 < value <= DEFAULT_MAX_AUDIO_DURATION_SECONDS
        else DEFAULT_MAX_AUDIO_DURATION_SECONDS
    )


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _sha256_text(value: str) -> str:
    return hashlib.sha256(str(value or "").encode("utf-8")).hexdigest()


def _canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _canonical_sha256(value: object) -> str:
    return _sha256_bytes(_canonical_json_bytes(value))


def _normalized_text(value: object) -> str:
    return " ".join(str(value or "").split()).strip()


def _lexical_tokens(value: object) -> list[str]:
    normalized = unicodedata.normalize("NFKD", str(value or "").casefold().replace("ß", "ss"))
    stripped = "".join(character for character in normalized if not unicodedata.combining(character))
    return re.findall(r"[a-z0-9]+", stripped)


def _required_token_contract_failures(
    *,
    expected_text: object,
    required_tokens: object,
    prefix: str,
) -> list[str]:
    failures: list[str] = []
    if type(required_tokens) is not list:
        return [f"{prefix}_required_tokens_type_invalid"]
    expected_lexical_tokens = set(_lexical_tokens(expected_text))
    if not expected_lexical_tokens:
        failures.append(f"{prefix}_expected_text_lexical_tokens_missing")
    if not required_tokens:
        failures.append(f"{prefix}_required_tokens_missing")
    for index, token_phrase in enumerate(required_tokens):
        if type(token_phrase) is not str:
            failures.append(f"{prefix}_required_token_type_invalid:{index}")
            continue
        normalized_phrase = _normalized_text(token_phrase)
        phrase_components = _lexical_tokens(normalized_phrase)
        if not normalized_phrase or not phrase_components:
            failures.append(f"{prefix}_required_token_lexical_tokens_missing:{index}")
            continue
        if any(component not in expected_lexical_tokens for component in phrase_components):
            failures.append(f"{prefix}_required_token_not_in_expected_text:{index}")
    return failures


def _validate_raw_review_schema(review: dict[str, object]) -> list[str]:
    failures: list[str] = []
    unknown_fields = sorted(set(review) - set(GROUND_TRUTH_REVIEW_FIELDS))
    missing_fields = sorted(set(GROUND_TRUTH_REVIEW_FIELDS) - set(review))
    if unknown_fields:
        failures.append("ground_truth_review_unknown_fields")
    if missing_fields:
        failures.append("ground_truth_review_schema_fields_missing")
    for field in GROUND_TRUTH_REVIEW_FIELDS - {"required_tokens", "provider_upload_authorization"}:
        if field in review and type(review.get(field)) is not str:
            failures.append(f"ground_truth_review_{field}_type_invalid")
    failures.extend(
        _required_token_contract_failures(
            expected_text=review.get("expected_text"),
            required_tokens=review.get("required_tokens"),
            prefix="ground_truth_review",
        )
    )
    authorization = review.get("provider_upload_authorization")
    if (
        type(authorization) is not dict
        or set(authorization) != set(PROVIDER_UPLOAD_LANES)
        or any(type(authorization.get(lane)) is not bool for lane in PROVIDER_UPLOAD_LANES)
    ):
        failures.append("ground_truth_review_provider_upload_authorization_type_invalid")
    return failures


def _review_freshness_failures(value: object, *, now: datetime | None = None) -> list[str]:
    reviewed_at = str(value or "")
    try:
        parsed = datetime.fromisoformat(reviewed_at.replace("Z", "+00:00"))
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError("timezone_missing")
        parsed = parsed.astimezone(UTC)
    except (TypeError, ValueError, OverflowError):
        return ["ground_truth_review_reviewed_at_invalid"]
    reference = (now or datetime.now(UTC)).astimezone(UTC)
    if parsed - reference > MAX_REVIEW_FUTURE_SKEW:
        return ["ground_truth_review_reviewed_at_future"]
    if reference - parsed > MAX_REVIEW_AGE:
        return ["ground_truth_review_reviewed_at_stale"]
    return []


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _pcm_wav_duration_from_payload(payload: bytes) -> float:
    if len(payload) < 44 or payload[:4] != b"RIFF" or payload[8:12] != b"WAVE":
        return 0.0
    position = 12
    byte_rate = 0
    block_align = 0
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
                return 0.0
        elif chunk_id == b"data":
            available = max(0, len(payload) - chunk_payload_start)
            data_size = available if chunk_size == 0xFFFFFFFF else min(chunk_size, available)
            break
        if chunk_size == 0xFFFFFFFF:
            break
        position = chunk_payload_start + chunk_size + (chunk_size % 2)
    if data_size <= 0 or byte_rate <= 0 or block_align <= 0:
        return 0.0
    usable_data_size = data_size - (data_size % block_align)
    if usable_data_size <= 0:
        return 0.0
    return round(usable_data_size / float(byte_rate), 3)


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
    return round(max(0.8, token_count * 0.28), 3)


def _fixture_quality(
    *,
    payload: bytes,
    expected_text: str,
    max_duration_seconds: float | None = None,
) -> dict[str, object]:
    duration_seconds = _wav_duration_seconds(payload)
    min_duration_seconds = _expected_min_duration_seconds(expected_text)
    try:
        requested_max_duration_seconds = float(
            max_duration_seconds if max_duration_seconds is not None else _default_max_audio_duration_seconds()
        )
    except (TypeError, ValueError, OverflowError):
        requested_max_duration_seconds = float("nan")
    max_duration_invalid = (
        not math.isfinite(requested_max_duration_seconds)
        or requested_max_duration_seconds <= 0
        or requested_max_duration_seconds > DEFAULT_MAX_AUDIO_DURATION_SECONDS
    )
    effective_max_duration_seconds = (
        DEFAULT_MAX_AUDIO_DURATION_SECONDS
        if max_duration_invalid
        else requested_max_duration_seconds
    )
    wav_format = _pcm_wav_format(payload)
    failures: list[str] = []
    if max_duration_invalid:
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
    if duration_seconds > 0 and duration_seconds < 0.8:
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


def _load_error_metadata(bundle_dir: Path) -> dict[str, object]:
    metadata_path = bundle_dir / "error.json"
    if not metadata_path.is_file():
        return {}
    try:
        payload = json.loads(metadata_path.read_text(encoding="utf-8"))
    except Exception:
        return {"metadata_error": "invalid_error_json"}
    return payload if isinstance(payload, dict) else {}


def _safe_private_error_metadata(metadata: dict[str, object]) -> dict[str, object]:
    raw_event = _normalized_text(metadata.get("event_type") or metadata.get("issue_type")).lower()
    raw_reason = _normalized_text(metadata.get("reason") or metadata.get("classification")).lower()
    return {
        "event_type_code": raw_event if raw_event in ALLOWED_ERROR_EVENT_CODES else ("other" if raw_event else ""),
        "event_type_sha256": _sha256_text(raw_event) if raw_event else "",
        "reason_code": raw_reason if raw_reason in ALLOWED_ERROR_REASON_CODES else ("other" if raw_reason else ""),
        "reason_sha256": _sha256_text(raw_reason) if raw_reason else "",
    }


def _load_input_wav(input_path: Path, *, max_audio_bytes: int) -> tuple[bytes, list[str]]:
    try:
        effective_max_audio_bytes = int(max_audio_bytes)
    except (TypeError, ValueError, OverflowError):
        return b"", ["max_audio_bytes_invalid"]
    if effective_max_audio_bytes <= 0 or effective_max_audio_bytes > DEFAULT_MAX_AUDIO_BYTES:
        return b"", ["max_audio_bytes_invalid"]
    try:
        if input_path.is_symlink():
            return b"", ["input_wav_symlink_forbidden"]
    except OSError:
        return b"", ["input_wav_stat_failed"]
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(input_path, flags)
    except FileNotFoundError:
        return b"", ["input_wav_missing"]
    except OSError:
        return b"", ["input_wav_open_failed"]
    try:
        file_stat = os.fstat(descriptor)
        if not stat.S_ISREG(file_stat.st_mode):
            return b"", ["input_wav_not_regular_file"]
        byte_count = int(file_stat.st_size)
        if byte_count <= 0:
            return b"", ["input_wav_empty"]
        if byte_count > effective_max_audio_bytes:
            return b"", ["input_wav_too_large"]
        chunks: list[bytes] = []
        remaining = byte_count
        while remaining > 0:
            chunk = os.read(descriptor, min(remaining, 64 * 1024))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        payload = b"".join(chunks)
        if len(payload) != byte_count:
            return b"", ["input_wav_short_read"]
        return payload, []
    except OSError:
        return b"", ["input_wav_read_failed"]
    finally:
        os.close(descriptor)


def _load_private_ground_truth_review(
    path: Path,
    *,
    max_bytes: int = DEFAULT_MAX_GROUND_TRUTH_REVIEW_BYTES,
) -> tuple[dict[str, object], list[str]]:
    path = _absolute_path(path)
    try:
        effective_max_bytes = int(max_bytes)
    except (TypeError, ValueError, OverflowError):
        return {}, ["ground_truth_review_max_bytes_invalid"]
    if effective_max_bytes <= 0 or effective_max_bytes > DEFAULT_MAX_GROUND_TRUTH_REVIEW_BYTES:
        return {}, ["ground_truth_review_max_bytes_invalid"]
    if not path.name or path.name in {".", ".."}:
        return {}, ["ground_truth_review_path_invalid"]
    parent_descriptor = -1
    try:
        parent_descriptor, _parent_identities = _open_directory_no_symlinks(path.parent)
    except FileNotFoundError:
        return {}, ["ground_truth_review_missing"]
    except OSError as exc:
        if exc.errno in {errno.ELOOP, errno.ENOTDIR}:
            return {}, ["ground_truth_review_symlink_forbidden"]
        return {}, ["ground_truth_review_parent_open_failed"]
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path.name, flags, dir_fd=parent_descriptor)
    except FileNotFoundError:
        os.close(parent_descriptor)
        return {}, ["ground_truth_review_missing"]
    except OSError as exc:
        os.close(parent_descriptor)
        if exc.errno in {errno.ELOOP, errno.ENOTDIR}:
            return {}, ["ground_truth_review_symlink_forbidden"]
        return {}, ["ground_truth_review_open_failed"]
    os.close(parent_descriptor)
    try:
        file_stat = os.fstat(descriptor)
        if not stat.S_ISREG(file_stat.st_mode):
            return {}, ["ground_truth_review_not_regular_file"]
        if stat.S_IMODE(file_stat.st_mode) != 0o600:
            return {}, ["ground_truth_review_mode_must_be_0600"]
        if int(file_stat.st_nlink) != 1:
            return {}, ["ground_truth_review_link_count_must_be_one"]
        if int(file_stat.st_uid) != int(os.geteuid()):
            return {}, ["ground_truth_review_owner_must_match_euid"]
        inside_repo = _opened_descriptor_is_within_root(descriptor, ROOT)
        if inside_repo is None:
            return {}, ["ground_truth_review_repo_boundary_unverifiable"]
        if inside_repo:
            return {}, ["ground_truth_review_must_be_outside_repo"]
        if file_stat.st_size <= 0:
            return {}, ["ground_truth_review_empty"]
        if file_stat.st_size > effective_max_bytes:
            return {}, ["ground_truth_review_too_large"]
        chunks: list[bytes] = []
        remaining = int(file_stat.st_size)
        while remaining > 0:
            chunk = os.read(descriptor, min(remaining, 64 * 1024))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        raw = b"".join(chunks)
        if len(raw) != file_stat.st_size:
            return {}, ["ground_truth_review_short_read"]
    finally:
        os.close(descriptor)
    try:
        parsed = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {}, ["ground_truth_review_invalid_json"]
    if not isinstance(parsed, dict):
        return {}, ["ground_truth_review_invalid_object"]
    return dict(parsed), []


def _normalized_review(review: dict[str, object]) -> dict[str, object]:
    raw_required_tokens = review.get("required_tokens")
    required_tokens = [
        _normalized_text(item)
        for item in list(raw_required_tokens if isinstance(raw_required_tokens, list) else [])
        if _normalized_text(item)
    ]
    raw_provider_authorization = review.get("provider_upload_authorization")
    provider_authorization = (
        {
            str(key): value if isinstance(value, bool) else None
            for key, value in raw_provider_authorization.items()
        }
        if isinstance(raw_provider_authorization, dict)
        else {}
    )
    return {
        "contract_name": _normalized_text(review.get("contract_name")),
        "status": _normalized_text(review.get("status")).lower(),
        "reviewed_at": _normalized_text(review.get("reviewed_at")),
        "reviewer_authority": _normalized_text(review.get("reviewer_authority")),
        "audio_sha256": _normalized_text(review.get("audio_sha256")).lower(),
        "bundle_id": _normalized_text(review.get("bundle_id")),
        "sample": _normalized_text(review.get("sample")),
        "expected_text": _normalized_text(review.get("expected_text")),
        "required_tokens": required_tokens,
        "speaker_consent": _normalized_text(review.get("speaker_consent")),
        "allowed_purpose": _normalized_text(review.get("allowed_purpose")),
        "retention": _normalized_text(review.get("retention")),
        "language": _normalized_text(review.get("language")),
        "accent": _normalized_text(review.get("accent")),
        "provider_upload_authorization": provider_authorization,
    }


def _review_binding_payload(review: dict[str, object]) -> dict[str, object]:
    expected_text = _normalized_text(review.get("expected_text"))
    required_tokens = [str(item) for item in list(review.get("required_tokens") or [])]
    return {
        "contract_name": GROUND_TRUTH_REVIEW_BINDING_CONTRACT,
        "status": str(review.get("status") or ""),
        "reviewed_at": str(review.get("reviewed_at") or ""),
        "reviewer_authority": str(review.get("reviewer_authority") or ""),
        "audio_sha256": str(review.get("audio_sha256") or ""),
        "bundle_id": str(review.get("bundle_id") or ""),
        "sample": str(review.get("sample") or ""),
        "expected_text_sha256": _sha256_text(expected_text),
        "required_token_sha256": [_sha256_text(token) for token in required_tokens],
        "speaker_consent": str(review.get("speaker_consent") or ""),
        "allowed_purpose": str(review.get("allowed_purpose") or ""),
        "retention": str(review.get("retention") or ""),
        "language": str(review.get("language") or ""),
        "accent": str(review.get("accent") or ""),
        "provider_upload_authorization": dict(review.get("provider_upload_authorization") or {}),
    }


def _validate_review(
    review: dict[str, object],
    *,
    audio_sha256: str,
    bundle_id: str,
    now: datetime | None = None,
) -> list[str]:
    failures: list[str] = []
    if review.get("contract_name") != GROUND_TRUTH_REVIEW_CONTRACT:
        failures.append("ground_truth_review_contract_invalid")
    if review.get("status") != "approved":
        failures.append("ground_truth_review_not_approved")
    if review.get("reviewer_authority") != "memorial_operator":
        failures.append("ground_truth_review_reviewer_authority_invalid")
    if review.get("speaker_consent") != APPROVED_SPEAKER_CONSENT:
        failures.append("ground_truth_review_speaker_consent_invalid")
    if review.get("allowed_purpose") != APPROVED_ALLOWED_PURPOSE:
        failures.append("ground_truth_review_allowed_purpose_invalid")
    if review.get("retention") not in APPROVED_RETENTION_VALUES:
        failures.append("ground_truth_review_retention_invalid")
    if review.get("language") != APPROVED_LANGUAGE:
        failures.append("ground_truth_review_language_invalid")
    if review.get("accent") != APPROVED_ACCENT:
        failures.append("ground_truth_review_accent_invalid")
    provider_authorization = review.get("provider_upload_authorization")
    if not isinstance(provider_authorization, dict):
        provider_authorization = {}
    if set(provider_authorization) != set(PROVIDER_UPLOAD_LANES) or any(
        not isinstance(provider_authorization.get(lane), bool)
        for lane in PROVIDER_UPLOAD_LANES
    ):
        failures.append("ground_truth_review_provider_upload_authorization_invalid")
    elif provider_authorization.get("full_runtime") is not True:
        failures.append("ground_truth_review_full_runtime_upload_not_authorized")
    failures.extend(_review_freshness_failures(review.get("reviewed_at"), now=now))
    for field in (
        "reviewed_at",
        "reviewer_authority",
        "audio_sha256",
        "bundle_id",
        "sample",
        "expected_text",
        "speaker_consent",
        "allowed_purpose",
        "retention",
        "language",
        "accent",
    ):
        if not str(review.get(field) or "").strip():
            failures.append(f"ground_truth_review_{field}_missing")
    failures.extend(
        _required_token_contract_failures(
            expected_text=review.get("expected_text"),
            required_tokens=review.get("required_tokens"),
            prefix="ground_truth_review",
        )
    )
    if audio_sha256 and review.get("audio_sha256") != audio_sha256:
        failures.append("ground_truth_review_audio_sha256_mismatch")
    if review.get("bundle_id") and review.get("bundle_id") != bundle_id:
        failures.append("ground_truth_review_bundle_id_mismatch")
    return failures


def _validate_candidate_sample(sample: str) -> list[str]:
    failures: list[str] = []
    if not SAFE_CANDIDATE_SAMPLE_PATTERN.fullmatch(str(sample or "")):
        failures.append("candidate_sample_invalid")
    if sample in RESERVED_CANDIDATE_SAMPLES:
        failures.append("candidate_sample_reserved")
    return failures


def _safe_reviewed_at(value: object) -> str:
    reviewed_at = _normalized_text(value)
    try:
        parsed = datetime.fromisoformat(reviewed_at.replace("Z", "+00:00"))
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            return "invalid"
    except ValueError:
        return "invalid"
    return reviewed_at


def _text_payload(text: str, *, text_mode: str) -> dict[str, object]:
    normalized = _normalized_text(text)
    payload: dict[str, object] = {
        "text_chars": len(normalized),
        "text_sha256": _sha256_text(normalized),
    }
    if text_mode == "full":
        payload["text"] = normalized
    else:
        payload["text_redacted"] = True
    return payload


def build_fixture_candidate(
    *,
    bundle_dir: Path,
    ground_truth_review_path: Path,
    origin: str,
    fixture_file: str,
    text_mode: str = "redacted",
    allow_external_root: bool = False,
    bundle_root: Path | None = None,
    max_audio_bytes: int | None = None,
    max_audio_duration_seconds: float | None = None,
    max_ground_truth_review_bytes: int = DEFAULT_MAX_GROUND_TRUTH_REVIEW_BYTES,
    review_now: datetime | None = None,
) -> dict[str, object]:
    bundle_dir = bundle_dir.expanduser()
    resolved_bundle_root = (bundle_root or _default_bundle_root()).expanduser()
    text_mode = "full" if str(text_mode or "").strip().lower() == "full" else "redacted"
    failures: list[str] = []
    if not allow_external_root and not _is_relative_to(bundle_dir, resolved_bundle_root):
        failures.append("bundle_not_under_memorial_stt_error_root")
    input_path = bundle_dir / "input.wav"
    try:
        effective_max_audio_bytes = int(
            max_audio_bytes if max_audio_bytes is not None else _default_max_audio_bytes()
        )
    except (TypeError, ValueError, OverflowError):
        effective_max_audio_bytes = _default_max_audio_bytes()
        failures.append("max_audio_bytes_invalid")
    if effective_max_audio_bytes <= 0 or effective_max_audio_bytes > DEFAULT_MAX_AUDIO_BYTES:
        effective_max_audio_bytes = _default_max_audio_bytes()
        failures.append("max_audio_bytes_invalid")
    payload, input_failures = _load_input_wav(input_path, max_audio_bytes=effective_max_audio_bytes)
    failures.extend(input_failures)
    audio_sha256 = _sha256_bytes(payload) if payload else ""
    raw_review, review_load_failures = _load_private_ground_truth_review(
        ground_truth_review_path,
        max_bytes=max_ground_truth_review_bytes,
    )
    failures.extend(review_load_failures)
    failures.extend(_validate_raw_review_schema(raw_review))
    review = _normalized_review(raw_review)
    failures.extend(
        _validate_review(
            review,
            audio_sha256=audio_sha256,
            bundle_id=bundle_dir.name,
            now=review_now,
        )
    )
    sample = str(review.get("sample") or "")
    failures.extend(_validate_candidate_sample(sample))
    bundle_id = bundle_dir.name
    if not SAFE_BUNDLE_ID_PATTERN.fullmatch(bundle_id):
        failures.append("bundle_id_invalid")
    expected_text = str(review.get("expected_text") or "")
    required_tokens = [str(item) for item in list(review.get("required_tokens") or [])]
    speaker_consent = str(review.get("speaker_consent") or "")
    allowed_purpose = str(review.get("allowed_purpose") or "")
    retention = str(review.get("retention") or "")
    language = str(review.get("language") or "")
    accent = str(review.get("accent") or "")
    provider_upload_authorization = dict(review.get("provider_upload_authorization") or {})
    requested_origin = _normalized_text(origin)
    requested_fixture_file = _normalized_text(fixture_file) or f"{sample}_captured.wav"
    if (
        not SAFE_FIXTURE_FILE_PATTERN.fullmatch(requested_fixture_file)
        or Path(requested_fixture_file).name != requested_fixture_file
        or requested_fixture_file != f"{sample}_captured.wav"
    ):
        failures.append("fixture_file_invalid")
    if requested_origin != APPROVED_CAPTURE_ORIGIN:
        failures.append("candidate_origin_invalid")
    safe_bundle_id = bundle_id if SAFE_BUNDLE_ID_PATTERN.fullmatch(bundle_id) else "invalid_bundle_id"
    safe_sample = (
        sample
        if SAFE_CANDIDATE_SAMPLE_PATTERN.fullmatch(sample) and sample not in RESERVED_CANDIDATE_SAMPLES
        else "invalid_candidate_sample"
    )
    safe_fixture_file = (
        requested_fixture_file
        if SAFE_FIXTURE_FILE_PATTERN.fullmatch(requested_fixture_file)
        and Path(requested_fixture_file).name == requested_fixture_file
        and requested_fixture_file == f"{sample}_captured.wav"
        else "invalid_candidate.wav"
    )
    safe_speaker_consent = speaker_consent if speaker_consent == APPROVED_SPEAKER_CONSENT else "invalid"
    safe_allowed_purpose = allowed_purpose if allowed_purpose == APPROVED_ALLOWED_PURPOSE else "invalid"
    safe_retention = retention if retention in APPROVED_RETENTION_VALUES else "invalid"
    safe_language = language if language == APPROVED_LANGUAGE else "invalid"
    safe_accent = accent if accent == APPROVED_ACCENT else "invalid"
    safe_provider_upload_authorization = (
        provider_upload_authorization
        if set(provider_upload_authorization) == set(PROVIDER_UPLOAD_LANES)
        and all(isinstance(provider_upload_authorization.get(lane), bool) for lane in PROVIDER_UPLOAD_LANES)
        else {lane: False for lane in PROVIDER_UPLOAD_LANES}
    )
    try:
        effective_max_audio_duration_seconds = float(
            max_audio_duration_seconds
            if max_audio_duration_seconds is not None
            else _default_max_audio_duration_seconds()
        )
    except (TypeError, ValueError, OverflowError):
        effective_max_audio_duration_seconds = DEFAULT_MAX_AUDIO_DURATION_SECONDS
        failures.append("max_audio_duration_invalid")
    if (
        not math.isfinite(effective_max_audio_duration_seconds)
        or effective_max_audio_duration_seconds <= 0
        or effective_max_audio_duration_seconds > DEFAULT_MAX_AUDIO_DURATION_SECONDS
    ):
        effective_max_audio_duration_seconds = DEFAULT_MAX_AUDIO_DURATION_SECONDS
        failures.append("max_audio_duration_invalid")
    quality = _fixture_quality(
        payload=payload,
        expected_text=expected_text,
        max_duration_seconds=effective_max_audio_duration_seconds,
    ) if payload else {
        "status": "blocked",
        "failed_codes": ["audio_missing"],
        "audio_duration_seconds": 0.0,
        "expected_min_duration_seconds": _expected_min_duration_seconds(expected_text),
        "max_duration_seconds": effective_max_audio_duration_seconds,
        "wav_format": _pcm_wav_format(payload),
    }
    failures.extend(str(item) for item in list(quality.get("failed_codes") or []) if str(item))
    required_token_payloads = [
        _text_payload(token, text_mode=text_mode)
        for token in required_tokens
        if str(token or "").strip()
    ]
    metadata = _load_error_metadata(bundle_dir)
    safe_metadata = _safe_private_error_metadata(metadata)
    review_binding_payload = _review_binding_payload(review)
    review_binding_sha256 = _canonical_sha256(review_binding_payload)
    status = "pass" if not failures else "blocked"
    failed_codes = sorted(set(failures))
    promotion_gate = {
        "status": "pending_captured_candidate_benchmark" if status == "pass" else "blocked",
        "required_receipt": ".codex-studio/published/memorial_stt_provider_benchmark_captured_candidate.generated.json",
        "required_rule": "captured candidate must pass full-runtime STT scoring against operator-confirmed ground truth before fixture-manifest promotion",
        "may_update_fixture_manifest": False,
        "next_action": "run_captured_candidate_benchmark_before_fixture_manifest"
        if status == "pass"
        else "fix_candidate_failed_codes_before_benchmark",
    }
    candidate_binding_payload = {
        "contract_name": CANDIDATE_BINDING_CONTRACT,
        "audio_sha256": audio_sha256,
        "bundle_id": safe_bundle_id,
        "sample": safe_sample,
        "fixture_file": safe_fixture_file,
        "origin": APPROVED_CAPTURE_ORIGIN if requested_origin == APPROVED_CAPTURE_ORIGIN else "invalid",
        "expected_text_sha256": _sha256_text(expected_text),
        "required_token_sha256": [_sha256_text(token) for token in required_tokens],
        "speaker_consent": safe_speaker_consent,
        "allowed_purpose": safe_allowed_purpose,
        "retention": safe_retention,
        "language": safe_language,
        "accent": safe_accent,
        "fixture_quality": quality,
        "privacy_mode": text_mode,
        "operator_ground_truth_review_binding_sha256": review_binding_sha256,
        "provider_upload_authorization": safe_provider_upload_authorization,
        "status": status,
        "failed_codes": failed_codes,
    }
    return {
        "contract_name": "ea.memorial_stt_fixture_candidate",
        "contract_version": CANDIDATE_CONTRACT_VERSION,
        "generated_at": _utc_now(),
        "generated_by": "scripts/materialize_memorial_stt_fixture_candidate.py",
        "source_git_head": resolve_source_state_head(ROOT),
        "head_semantics": "source_state",
        "source_state_fingerprint": resolve_source_worktree_fingerprint(ROOT),
        "source_state_fingerprint_semantics": "worktree_source_files_sha256_excluding_generated_only_paths",
        "status": status,
        "failed_codes": failed_codes,
        "candidate_scope": "audio_quality_provenance_and_bound_ground_truth",
        "promotion_gate": promotion_gate,
        "bundle": {
            "root": "[memorial_stt_error_root]" if _is_relative_to(bundle_dir, resolved_bundle_root) else "[external_root]",
            "id": safe_bundle_id,
            "id_sha256": _sha256_text(bundle_id),
            "has_error_json": bool(metadata),
            **safe_metadata,
        },
        "audio": {
            "input_file": "input.wav",
            "sha256": audio_sha256,
            "bytes": len(payload),
            "max_bytes": effective_max_audio_bytes,
            "duration_seconds": quality.get("audio_duration_seconds"),
            "expected_min_duration_seconds": quality.get("expected_min_duration_seconds"),
            "max_duration_seconds": quality.get("max_duration_seconds"),
        },
        "fixture_quality": quality,
        "candidate_manifest_entry": {
            "sample": safe_sample,
            "file": safe_fixture_file,
            "origin": APPROVED_CAPTURE_ORIGIN if requested_origin == APPROVED_CAPTURE_ORIGIN else "invalid",
            "speaker_consent": safe_speaker_consent,
            "allowed_purpose": safe_allowed_purpose,
            "retention": safe_retention,
            "synthetic": False,
            "language": safe_language,
            "accent": safe_accent,
            "provider_upload_authorization": safe_provider_upload_authorization,
            "expected_text": _text_payload(expected_text, text_mode=text_mode),
            "required_tokens": required_token_payloads,
            "sha256": audio_sha256,
        },
        "operator_ground_truth_review": {
            "contract_name": GROUND_TRUTH_REVIEW_BINDING_CONTRACT,
            "status": "approved" if review.get("status") == "approved" else "invalid",
            "reviewed_at": _safe_reviewed_at(review.get("reviewed_at")),
            "reviewer_authority": (
                "memorial_operator"
                if review.get("reviewer_authority") == "memorial_operator"
                else "invalid"
            ),
            "sha256": review_binding_sha256,
        },
        "candidate_binding": {
            "contract_name": CANDIDATE_BINDING_CONTRACT,
            "canonicalization": CANONICALIZATION,
            "sha256": _canonical_sha256(candidate_binding_payload),
            "payload": candidate_binding_payload,
        },
        "privacy_mode": text_mode,
        "text_mode": text_mode,
        "raw_text_fields": text_mode == "full",
    }


def _redacted_candidate_for_stdout(payload: dict[str, object]) -> dict[str, object]:
    safe = json.loads(json.dumps(payload, ensure_ascii=False, allow_nan=False))
    entry = dict(safe.get("candidate_manifest_entry") or {})
    expected = dict(entry.get("expected_text") or {})
    expected.pop("text", None)
    expected["text_redacted"] = True
    entry["expected_text"] = expected
    redacted_tokens: list[dict[str, object]] = []
    for item in list(entry.get("required_tokens") or []):
        row = dict(item or {})
        row.pop("text", None)
        row["text_redacted"] = True
        redacted_tokens.append(row)
    entry["required_tokens"] = redacted_tokens
    safe["candidate_manifest_entry"] = entry
    safe["stdout_redacted"] = True
    return safe


def _absolute_path(path: Path) -> Path:
    return Path(os.path.abspath(path.expanduser()))


def _directory_open_flags() -> int:
    return os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)


def _descriptor_identity(descriptor: int) -> tuple[int, int]:
    descriptor_stat = os.fstat(descriptor)
    return int(descriptor_stat.st_dev), int(descriptor_stat.st_ino)


def _open_directory_no_symlinks(path: Path) -> tuple[int, tuple[tuple[int, int], ...]]:
    absolute_path = _absolute_path(path)
    if not absolute_path.is_absolute() or not absolute_path.anchor:
        raise OSError(errno.EINVAL, "directory_path_not_absolute")
    descriptor = os.open(absolute_path.anchor, _directory_open_flags())
    identities: list[tuple[int, int]] = []
    try:
        root_stat = os.fstat(descriptor)
        if not stat.S_ISDIR(root_stat.st_mode):
            raise OSError(errno.ENOTDIR, "directory_anchor_not_directory")
        identities.append((int(root_stat.st_dev), int(root_stat.st_ino)))
        for component in absolute_path.parts[1:]:
            next_descriptor = os.open(
                component,
                _directory_open_flags(),
                dir_fd=descriptor,
            )
            try:
                component_stat = os.fstat(next_descriptor)
                if not stat.S_ISDIR(component_stat.st_mode):
                    raise OSError(errno.ENOTDIR, "path_component_not_directory")
            except Exception:
                os.close(next_descriptor)
                raise
            os.close(descriptor)
            descriptor = next_descriptor
            identities.append((int(component_stat.st_dev), int(component_stat.st_ino)))
        return descriptor, tuple(identities)
    except Exception:
        os.close(descriptor)
        raise


def _opened_descriptor_path(descriptor: int) -> Path | None:
    try:
        raw_path = os.readlink(f"/proc/self/fd/{descriptor}")
    except OSError:
        return None
    if not raw_path.startswith("/") or raw_path.endswith(" (deleted)"):
        return None
    return Path(os.path.normpath(raw_path))


def _opened_descriptor_is_within_root(descriptor: int, root: Path) -> bool | None:
    root_descriptor = -1
    try:
        root_descriptor, _root_identities = _open_directory_no_symlinks(root)
        opened_path = _opened_descriptor_path(descriptor)
        opened_root = _opened_descriptor_path(root_descriptor)
        if opened_path is None or opened_root is None:
            return None
        try:
            opened_path.relative_to(opened_root)
            return True
        except ValueError:
            return False
    except OSError:
        return None
    finally:
        if root_descriptor >= 0:
            os.close(root_descriptor)


def _verify_atomic_output_directory(reservation: dict[str, object]) -> None:
    directory_descriptor = _reservation_descriptor(reservation, "directory_descriptor")
    expected_identity = reservation.get("directory_identity")
    if directory_descriptor < 0 or expected_identity != _descriptor_identity(directory_descriptor):
        raise RuntimeError("output_parent_identity_changed")
    if reservation.get("contains_full_text") is True:
        repo_root = reservation.get("repo_root")
        if not isinstance(repo_root, Path):
            raise RuntimeError("output_repo_boundary_unverifiable")
        inside_repo = _opened_descriptor_is_within_root(directory_descriptor, repo_root)
        if inside_repo is None:
            raise RuntimeError("output_repo_boundary_unverifiable")
        if inside_repo:
            raise RuntimeError("full_text_repo_output_forbidden")


def _prepare_atomic_json_output(
    path: Path,
    *,
    contains_full_text: bool,
    repo_root: Path = ROOT,
) -> dict[str, object]:
    path = _absolute_path(path)
    if (
        not path.name
        or path.name in {".", ".."}
        or not re.fullmatch(r"[A-Za-z0-9._-]{1,160}", path.name)
    ):
        raise RuntimeError("output_target_name_invalid")
    try:
        directory_descriptor, directory_identities = _open_directory_no_symlinks(path.parent)
    except OSError as exc:
        raise RuntimeError("output_parent_unsafe") from exc
    temp_descriptor = -1
    temp_name = ""
    try:
        directory_stat = os.fstat(directory_descriptor)
        if not stat.S_ISDIR(directory_stat.st_mode):
            raise RuntimeError("output_parent_not_directory")
        directory_identity = (int(directory_stat.st_dev), int(directory_stat.st_ino))
        if not directory_identities or directory_identities[-1] != directory_identity:
            raise RuntimeError("output_parent_identity_changed")
        if contains_full_text:
            inside_repo = _opened_descriptor_is_within_root(directory_descriptor, repo_root)
            if inside_repo is None:
                raise RuntimeError("output_repo_boundary_unverifiable")
            if inside_repo:
                raise RuntimeError("full_text_repo_output_forbidden")
        try:
            target_stat = os.stat(path.name, dir_fd=directory_descriptor, follow_symlinks=False)
        except FileNotFoundError:
            target_stat = None
        except OSError as exc:
            raise RuntimeError("output_target_stat_failed") from exc
        if target_stat is not None and not stat.S_ISREG(target_stat.st_mode):
            raise RuntimeError("output_target_unsafe")
        mode = 0o600 if contains_full_text else 0o644
        for _attempt in range(32):
            temp_name = f".{path.name}.tmp-{os.getpid()}-{secrets.token_hex(8)}"
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
            try:
                temp_descriptor = os.open(temp_name, flags, mode, dir_fd=directory_descriptor)
                break
            except FileExistsError:
                continue
        if temp_descriptor < 0:
            raise RuntimeError("output_temp_reservation_failed")
        os.fchmod(temp_descriptor, mode)
        return {
            "path": path,
            "directory_descriptor": directory_descriptor,
            "temp_descriptor": temp_descriptor,
            "temp_name": temp_name,
            "target_name": path.name,
            "directory_identity": directory_identity,
            "contains_full_text": contains_full_text,
            "repo_root": _absolute_path(repo_root),
        }
    except Exception:
        if temp_descriptor >= 0:
            try:
                os.close(temp_descriptor)
            except OSError:
                pass
        if temp_name:
            try:
                os.unlink(temp_name, dir_fd=directory_descriptor)
            except OSError:
                pass
        os.close(directory_descriptor)
        raise


def _reservation_descriptor(reservation: dict[str, object], key: str) -> int:
    value = reservation.get(key)
    return value if type(value) is int else -1


def _abort_atomic_json_output(reservation: dict[str, object]) -> None:
    temp_descriptor = _reservation_descriptor(reservation, "temp_descriptor")
    directory_descriptor = _reservation_descriptor(reservation, "directory_descriptor")
    temp_name = str(reservation.get("temp_name") or "")
    if temp_descriptor >= 0:
        try:
            os.close(temp_descriptor)
        except OSError:
            pass
        reservation["temp_descriptor"] = -1
    if directory_descriptor >= 0 and temp_name:
        try:
            os.unlink(temp_name, dir_fd=directory_descriptor)
        except FileNotFoundError:
            pass
        except OSError:
            pass
    if directory_descriptor >= 0:
        try:
            os.close(directory_descriptor)
        except OSError:
            pass
        reservation["directory_descriptor"] = -1


def _commit_atomic_json_output(reservation: dict[str, object], payload: dict[str, object]) -> None:
    rendered = (json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")
    temp_descriptor = _reservation_descriptor(reservation, "temp_descriptor")
    directory_descriptor = _reservation_descriptor(reservation, "directory_descriptor")
    temp_name = str(reservation.get("temp_name") or "")
    target_name = str(reservation.get("target_name") or "")
    if temp_descriptor < 0 or directory_descriptor < 0 or not temp_name or not target_name:
        raise RuntimeError("output_reservation_invalid")
    try:
        _verify_atomic_output_directory(reservation)
        offset = 0
        while offset < len(rendered):
            written = os.write(temp_descriptor, rendered[offset:])
            if written <= 0:
                raise RuntimeError("output_write_failed")
            offset += written
        os.fsync(temp_descriptor)
        _verify_atomic_output_directory(reservation)
        os.close(temp_descriptor)
        reservation["temp_descriptor"] = -1
        os.replace(
            temp_name,
            target_name,
            src_dir_fd=directory_descriptor,
            dst_dir_fd=directory_descriptor,
        )
        reservation["temp_name"] = ""
        os.fsync(directory_descriptor)
        os.close(directory_descriptor)
        reservation["directory_descriptor"] = -1
    except Exception:
        _abort_atomic_json_output(reservation)
        raise


def _write_receipt(path: Path, payload: dict[str, object], *, contains_full_text: bool) -> None:
    reservation = _prepare_atomic_json_output(path, contains_full_text=contains_full_text)
    try:
        _commit_atomic_json_output(reservation, payload)
    finally:
        _abort_atomic_json_output(reservation)


def _safe_atomic_output_preflight_failure_code(exc: BaseException) -> str:
    code = exc.args[0] if exc.args and type(exc.args[0]) is str else ""
    return code if code in SAFE_ATOMIC_OUTPUT_PREFLIGHT_FAILURE_CODES else "output_preflight_failed"


def main() -> int:
    parser = argparse.ArgumentParser(description="Materialize a governed candidate from a private memorial STT error bundle.")
    parser.add_argument("--bundle-dir", required=True, type=Path)
    parser.add_argument(
        "--ground-truth-review",
        required=True,
        type=Path,
        help="Private external 0600 non-symlink operator ground-truth review JSON.",
    )
    parser.add_argument(
        "--origin",
        default=APPROVED_CAPTURE_ORIGIN,
    )
    parser.add_argument("--fixture-file", default="")
    parser.add_argument("--text-mode", choices=("redacted", "full"), default="redacted")
    parser.add_argument("--allow-external-root", action="store_true")
    parser.add_argument("--bundle-root", type=Path, default=None)
    parser.add_argument("--max-audio-bytes", type=int, default=None)
    parser.add_argument("--max-audio-seconds", type=float, default=None)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()
    payload = build_fixture_candidate(
        bundle_dir=args.bundle_dir,
        ground_truth_review_path=args.ground_truth_review,
        origin=str(args.origin),
        fixture_file=str(args.fixture_file),
        text_mode=str(args.text_mode),
        allow_external_root=bool(args.allow_external_root),
        bundle_root=args.bundle_root,
        max_audio_bytes=args.max_audio_bytes,
        max_audio_duration_seconds=args.max_audio_seconds,
    )
    output = args.output or _default_output()
    try:
        output_reservation = _prepare_atomic_json_output(
            output,
            contains_full_text=str(args.text_mode) == "full",
        )
    except Exception as exc:
        blocked = {
            "contract_name": "ea.memorial_stt_fixture_candidate",
            "contract_version": CANDIDATE_CONTRACT_VERSION,
            "status": "blocked",
            "failed_codes": [_safe_atomic_output_preflight_failure_code(exc)],
            "stdout_redacted": True,
        }
        print(json.dumps(blocked, ensure_ascii=False, indent=2, allow_nan=False))
        return 2
    try:
        try:
            _commit_atomic_json_output(output_reservation, payload)
        except Exception:
            blocked = {
                "contract_name": "ea.memorial_stt_fixture_candidate",
                "contract_version": CANDIDATE_CONTRACT_VERSION,
                "status": "blocked",
                "failed_codes": ["output_commit_failed"],
                "stdout_redacted": True,
            }
            print(json.dumps(blocked, ensure_ascii=False, indent=2, allow_nan=False))
            return 2
    finally:
        _abort_atomic_json_output(output_reservation)
    print(json.dumps(_redacted_candidate_for_stdout(payload), ensure_ascii=False, indent=2, allow_nan=False))
    return 0 if payload.get("status") == "pass" else 2


if __name__ == "__main__":
    raise SystemExit(main())
