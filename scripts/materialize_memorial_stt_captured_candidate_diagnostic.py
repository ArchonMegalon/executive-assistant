#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import secrets
import stat
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

try:
    from scripts.source_state_head import resolve_source_state_head
    from scripts.source_state_head import resolve_source_worktree_fingerprint
except ModuleNotFoundError:  # pragma: no cover - script execution path
    from source_state_head import resolve_source_state_head
    from source_state_head import resolve_source_worktree_fingerprint


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CANDIDATE_RECEIPT = ROOT / ".codex-studio/published/memorial_stt_fixture_candidate.generated.json"
DEFAULT_BENCHMARK_RECEIPT = ROOT / ".codex-studio/published/memorial_stt_provider_benchmark_captured_candidate.generated.json"
DEFAULT_OUTPUT = ROOT / ".codex-studio/published/memorial_stt_captured_candidate_diagnostic.generated.json"
TRACKED_FIXTURE_MANIFEST = ROOT / "tests/fixtures/memorial/stt_fixture_manifest.json"

CONTRACT_NAME = "ea.memorial_stt_captured_candidate_diagnostic"
CONTRACT_VERSION = 2
GENERATED_BY = "scripts/materialize_memorial_stt_captured_candidate_diagnostic.py"
CANDIDATE_CONTRACT_NAME = "ea.memorial_stt_fixture_candidate"
CANDIDATE_CONTRACT_VERSION = 3
CANDIDATE_GENERATED_BY = "scripts/materialize_memorial_stt_fixture_candidate.py"
CANDIDATE_BINDING_CONTRACT_NAME = "ea.memorial_stt_fixture_candidate_binding.v2"
GROUND_TRUTH_REVIEW_CONTRACT_NAME = "ea.memorial_stt_operator_ground_truth_review.v2"
GROUND_TRUTH_REVIEW_BINDING_CONTRACT_NAME = "ea.memorial_stt_operator_ground_truth_review_binding.v2"
BENCHMARK_CONTRACT_NAME = "ea.memorial_stt_provider_benchmark"
BENCHMARK_GENERATED_BY = "scripts/benchmark_memorial_stt_providers.py"
TRANSFORMATION_CONTRACT_NAME = "ea.memorial_stt_audio_transformation_receipt.v1"
PROVIDER_ERROR_DETAIL_CONTRACT_NAME = "ea.memorial_stt_provider_error_detail.v1"
INPUT_BINDING_CONTRACT_NAME = "ea.memorial_stt_captured_candidate_diagnostic_input_binding.v1"
CANONICALIZATION = "json_utf8_sorted_keys_compact_v1"
CANDIDATE_SCOPE = "audio_quality_provenance_and_bound_ground_truth"
ALLOWED_PURPOSE = "memorial_stt_regression_and_provider_bakeoff"
AUTHORIZED_SPEAKER_CONSENT = "operator_attested_for_private_stt_regression"
AUTHORIZED_RETENTIONS = frozenset(
    {"private_captured_regression_candidate", "private_repo_captured_regression_fixture"}
)
AUTHORIZED_REVIEWER_AUTHORITY = "memorial_operator"
AUTHORIZED_LANGUAGE = "de"
AUTHORIZED_ACCENT = "Austrian German"
AUTHORIZED_ORIGIN = "captured_operator_manfred_memorial_stt_error_bundle"
FULL_RUNTIME_TRANSCRIBER = "cartesia/ink-whisper+enhanced_wav"
FULL_RUNTIME_TRANSCRIBER_SHA256 = hashlib.sha256(FULL_RUNTIME_TRANSCRIBER.encode("utf-8")).hexdigest()
GOVERNED_MIN_TOKEN_F1 = 0.55
GOVERNED_MAX_WER = 0.55
GOVERNED_MAX_AUDIO_DURATION_SECONDS = 120.0
GOVERNED_MAX_AUDIO_BYTES = 25 * 1024 * 1024
MAX_SOURCE_RECEIPT_BYTES = 4 * 1024 * 1024
HEAD_SEMANTICS = "source_state"
FINGERPRINT_SEMANTICS = "worktree_source_files_sha256_excluding_generated_only_paths"
MAX_EVIDENCE_AGE_SECONDS = 259_200
MAX_FUTURE_SKEW_SECONDS = 300
_SHA256_RE = re.compile(r"[0-9a-f]{64}")
_SAFE_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}")
_SAFE_CANDIDATE_SAMPLE_RE = re.compile(r"[a-z0-9][a-z0-9_-]{0,63}")
_SAFE_BUNDLE_ID_RE = re.compile(r"[a-z0-9][a-z0-9_-]{0,95}")
_SAFE_CODE_RE = re.compile(r"[a-z][a-z0-9_]{0,127}")
_ALLOWED_PROVIDER_STATUSES = frozenset(
    {
        "ok",
        "success",
        "transcribed",
        "error",
        "http_error",
        "unavailable",
        "fixture_invalid",
        "not_authorized",
        "known_bad",
        "empty",
        "unknown",
    }
)
_SUCCESSFUL_PROVIDER_STATUSES = frozenset({"ok", "success", "transcribed"})
_TRANSCRIBER_FAMILIES = frozenset({"cartesia", "onemin", "blipai", "memorial", "unknown"})
_PROVIDER_RESULT_KEYS = {
    "status",
    "passed",
    "usable",
    "intent_correct",
    "token_f1",
    "min_token_f1",
    "wer",
    "max_wer",
    "ms",
    "transcriber",
    "expected_text_chars",
    "actual_text_chars",
    "expected_text_sha256",
    "actual_text_sha256",
    "required_token_count",
    "required_token_sha256",
    "text_mode",
    "text_redacted",
    "provider_evidence_status",
    "provider_evidence_failed_codes",
    "detail",
    "scored_text_source",
    "candidate_key_count",
    "sampled_keys",
    "sample_strategy",
    "fixture_invalid",
}
_PROVIDER_RESULT_REQUIRED_KEYS = {
    "status",
    "passed",
    "usable",
    "intent_correct",
    "token_f1",
    "min_token_f1",
    "wer",
    "max_wer",
    "expected_text_chars",
    "actual_text_chars",
    "expected_text_sha256",
    "actual_text_sha256",
    "required_token_count",
    "required_token_sha256",
    "text_mode",
    "text_redacted",
    "provider_evidence_status",
    "provider_evidence_failed_codes",
}
_TRACKED_PROVIDER_UPLOAD_AUTHORIZATION = {
    "full_runtime": True,
    "shadow": True,
    "onemin_sample": True,
}
_RANKED_PROVIDERS = ("full_runtime", "shadow", "onemin_sample")
_ROW_KEYS = {
    "sample",
    "variant",
    "fixture",
    "fixture_sha256",
    "source_fixture_sha256",
    "fixture_quality",
    "source_fixture_quality",
    "transformation",
    "provenance",
    "captured_candidate_binding",
    "provider_upload_authorization",
    "shadow",
    "onemin_sample",
    "full_runtime",
}
_TRACKED_PROVENANCE_KEYS = {
    "origin",
    "speaker_consent",
    "allowed_purpose",
    "retention",
    "synthetic",
    "accent",
    "provider_upload_authorization",
}
_CANDIDATE_PROVENANCE_KEYS = _TRACKED_PROVENANCE_KEYS | {
    "external_bundle",
    "bundle_root",
    "bundle_id",
    "candidate_receipt_sha256",
    "candidate_binding_contract_name",
    "candidate_binding_sha256",
    "operator_ground_truth_review_binding_sha256",
}
_RANKING_KEYS = {
    "provider",
    "passed_samples",
    "sample_count",
    "scored_samples",
    "intent_correct_samples",
    "avg_token_f1",
    "avg_wer",
    "avg_latency_ms",
    "production_eligible",
}
_PROVIDER_ERROR_CATEGORIES = {
    "http_error",
    "insufficient_credits",
    "provider_error",
    "timeout",
}
_PROVIDER_ERROR_CODES = {
    "provider_error",
    "provider_http_error",
    "provider_timeout",
    "onemin_http_error",
}
_PROVIDER_ERROR_CODE_RE = re.compile(
    r"(?:onemin|cartesia|blipai|memorial)_[a-z_]+_http_[0-9]+"
)
_EXPECTED_SCORING = {
    "pass_rule": "usable transcript + required tokens present + token_f1 >= sample min + WER <= sample max",
    "raw_provider_transcript_scored": True,
    "semantic_repair_applied": False,
    "fixture_quality_rule": "ground-truth fixtures must be long enough to contain their expected transcript before provider accuracy is scored",
    "known_bad_non_empty_text_is_not_enough": True,
    "production_eligible_rule": "provider must pass every ground-truth benchmark sample and hostile variant",
    "text_mode": "redacted",
    "raw_transcript_fields": False,
    "redacted_text_fields": True,
    "redacted_receipt_rule": (
        "Default receipts store transcript hashes, lengths, and token hashes instead of raw expected/actual text. "
        "Set EA_MEMORIAL_STT_BENCHMARK_TEXT_MODE=full or pass --text-mode full for operator-local raw transcript diagnostics."
    ),
}


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"invalid_json_constant:{value}")


def _load_json_bytes(raw: bytes) -> dict[str, Any]:
    try:
        payload = json.loads(raw.decode("utf-8"), parse_constant=_reject_json_constant)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _load_json_with_entry(path: Path) -> tuple[dict[str, Any], dict[str, object]]:
    """Read, hash, and parse one regular file snapshot without following symlinks."""
    entry: dict[str, object] = {"path": _display_path(path), "exists": False}
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError:
        return {}, entry
    try:
        file_stat = os.fstat(descriptor)
        if (
            not stat.S_ISREG(file_stat.st_mode)
            or file_stat.st_size <= 0
            or file_stat.st_size > MAX_SOURCE_RECEIPT_BYTES
        ):
            return {}, entry
        chunks: list[bytes] = []
        remaining = int(file_stat.st_size)
        while remaining > 0:
            chunk = os.read(descriptor, min(remaining, 65_536))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        raw = b"".join(chunks)
        if len(raw) != file_stat.st_size:
            return {}, entry
    except OSError:
        return {}, entry
    finally:
        os.close(descriptor)
    entry.update({"exists": True, "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()})
    return _load_json_bytes(raw), entry


def _mapping(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _sequence(value: object) -> list[object]:
    return list(value) if isinstance(value, list) else []


def _strings(value: object) -> list[str]:
    return [item.strip() for item in _sequence(value) if isinstance(item, str) and item.strip()]


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _canonical_sha256(value: object) -> str:
    return _sha256_text(_canonical_json(value))


def _display_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT.resolve()).as_posix()
    except (OSError, ValueError):
        return "[external_path]"


def _valid_sha256(value: object) -> bool:
    return isinstance(value, str) and _SHA256_RE.fullmatch(value) is not None


def _safe_id(value: object) -> bool:
    return isinstance(value, str) and _SAFE_ID_RE.fullmatch(value) is not None


def _safe_bounded_text(value: object, *, max_chars: int = 128) -> bool:
    return (
        isinstance(value, str)
        and value == value.strip()
        and 0 < len(value) <= max_chars
        and all(character.isprintable() and character not in "\r\n" for character in value)
    )


def _strict_int(value: object, *, minimum: int = 0) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        return None
    return value


def _strict_failure_codes(
    value: object,
    *,
    prefix: str,
    issues: list[str],
    require_empty: bool,
    require_sorted: bool = False,
) -> list[str]:
    if not isinstance(value, list) or any(
        not isinstance(item, str) or _SAFE_CODE_RE.fullmatch(item) is None for item in value
    ):
        issues.append(f"{prefix}_failed_codes_invalid")
        return []
    codes = list(value)
    if len(set(codes)) != len(codes):
        issues.append(f"{prefix}_failed_codes_duplicated")
    if require_sorted and codes != sorted(codes):
        issues.append(f"{prefix}_failed_codes_not_sorted")
    if require_empty and codes:
        issues.append(f"{prefix}_failed_codes_not_empty")
    return codes


def _expected_min_duration_seconds(expected_text: str) -> float:
    token_count = len(re.findall(r"[\w]+", expected_text, flags=re.UNICODE))
    return round(max(0.8, token_count * 0.28), 3) if token_count else 0.0


def _tracked_benchmark_specs(*, issues: list[str]) -> dict[tuple[str, str], dict[str, object]]:
    """Load the governed tracked-row bindings without returning any source text."""
    manifest, entry = _load_json_with_entry(TRACKED_FIXTURE_MANIFEST)
    if not manifest or entry.get("exists") is not True:
        issues.append("tracked_fixture_manifest_missing_or_invalid")
        return {}
    if not _exact_keys(
        manifest,
        {
            "contract_name",
            "contract_version",
            "default_language",
            "retention_policy",
            "fixtures",
        },
    ):
        issues.append("tracked_fixture_manifest_shape_invalid")
    if (
        manifest.get("contract_name") != "ea.memorial_stt_fixture_manifest"
        or manifest.get("contract_version") != 1
        or manifest.get("default_language") != AUTHORIZED_LANGUAGE
    ):
        issues.append("tracked_fixture_manifest_contract_invalid")
    raw_fixtures = manifest.get("fixtures")
    if not isinstance(raw_fixtures, list) or not raw_fixtures:
        issues.append("tracked_fixture_manifest_entries_invalid")
        return {}

    specs: dict[tuple[str, str], dict[str, object]] = {}
    seen_samples: set[str] = set()
    expected_entry_keys = {
        "sample",
        "file",
        "origin",
        "speaker_consent",
        "allowed_purpose",
        "retention",
        "synthetic",
        "language",
        "accent",
        "expected_text",
        "required_tokens",
        "min_token_f1",
        "max_wer",
        "sha256",
        "generation",
    }
    for index, raw_entry in enumerate(raw_fixtures):
        if not isinstance(raw_entry, dict):
            issues.append("tracked_fixture_manifest_entry_type_invalid")
            continue
        fixture = dict(raw_entry)
        if not _exact_keys(fixture, expected_entry_keys):
            issues.append("tracked_fixture_manifest_entry_shape_invalid")
        sample = fixture.get("sample")
        file_name = fixture.get("file")
        expected_text = fixture.get("expected_text")
        raw_tokens = fixture.get("required_tokens")
        source_sha256 = fixture.get("sha256")
        if (
            not isinstance(sample, str)
            or _SAFE_CANDIDATE_SAMPLE_RE.fullmatch(sample) is None
            or sample in seen_samples
        ):
            issues.append("tracked_fixture_manifest_sample_invalid_or_duplicated")
            continue
        seen_samples.add(sample)
        if sample == "technical_retry":
            continue
        if (
            not isinstance(file_name, str)
            or not file_name
            or Path(file_name).name != file_name
            or re.fullmatch(r"[a-z0-9_.-]+\.wav", file_name) is None
        ):
            issues.append("tracked_fixture_manifest_file_invalid")
            continue
        if not isinstance(expected_text, str) or not expected_text.strip():
            issues.append("tracked_fixture_manifest_expected_text_invalid")
            continue
        if (
            not isinstance(raw_tokens, list)
            or not raw_tokens
            or any(not isinstance(token, str) or not token.strip() for token in raw_tokens)
        ):
            issues.append("tracked_fixture_manifest_required_tokens_invalid")
            continue
        if not _valid_sha256(source_sha256):
            issues.append("tracked_fixture_manifest_sha256_invalid")
            continue
        min_token_f1 = _float(fixture.get("min_token_f1"))
        max_wer = _float(fixture.get("max_wer"))
        if (
            min_token_f1 is None
            or not 0.0 <= min_token_f1 <= 1.0
            or max_wer is None
            or not 0.0 <= max_wer <= 1.0
        ):
            issues.append("tracked_fixture_manifest_threshold_invalid")
            continue
        if (
            fixture.get("synthetic") is not True
            or fixture.get("language") != AUTHORIZED_LANGUAGE
            or fixture.get("allowed_purpose") != ALLOWED_PURPOSE
        ):
            issues.append("tracked_fixture_manifest_governance_invalid")
            continue
        normalized_expected = expected_text.strip()
        normalized_tokens = [" ".join(token.split()).strip() for token in raw_tokens]
        provenance = {
            "origin": "governed_synthetic_stt_fixture",
            "speaker_consent": "synthetic_fixture_no_human_speaker",
            "allowed_purpose": ALLOWED_PURPOSE,
            "retention": "repo_synthetic_regression_fixture",
            "synthetic": True,
            "accent": "synthetic",
            "provider_upload_authorization": dict(_TRACKED_PROVIDER_UPLOAD_AUTHORIZATION),
        }
        common: dict[str, object] = {
            "fixture": file_name,
            "source_fixture_sha256": source_sha256,
            "expected_text_sha256": _sha256_text(normalized_expected),
            "expected_text_chars": len(normalized_expected),
            "required_token_sha256": [_sha256_text(token) for token in normalized_tokens],
            "min_token_f1": min_token_f1,
            "max_wer": max_wer,
            "expected_min_duration_seconds": _expected_min_duration_seconds(normalized_expected),
            "provider_upload_authorization": dict(_TRACKED_PROVIDER_UPLOAD_AUTHORIZATION),
            "provenance": provenance,
            "captured_candidate_binding": {},
            "candidate": False,
        }
        specs[(sample, "synthetic")] = {
            **common,
            "sample": sample,
            "variant": "synthetic",
            "transformation_id": "identity_v1",
        }
        specs[(f"{sample}_hostile", "hostile")] = {
            **common,
            "sample": f"{sample}_hostile",
            "variant": "hostile",
            "transformation_id": "hostile_room_v1",
        }
    if not specs:
        issues.append("tracked_fixture_manifest_no_benchmark_rows")
    return specs


def _hashed_strings(values: list[str]) -> list[str]:
    return [_sha256_text(value) for value in values if isinstance(value, str)]


_AUTHORIZATION_KEYS = {"full_runtime", "shadow", "onemin_sample"}


def _validate_upload_authorization(
    value: object,
    *,
    prefix: str,
    issues: list[str],
) -> dict[str, Any]:
    authorization = _mapping(value)
    if not _exact_keys(authorization, _AUTHORIZATION_KEYS):
        issues.append(f"{prefix}_provider_upload_authorization_shape_invalid")
    if any(not isinstance(authorization.get(key), bool) for key in _AUTHORIZATION_KEYS):
        issues.append(f"{prefix}_provider_upload_authorization_type_invalid")
    if authorization.get("full_runtime") is not True:
        issues.append(f"{prefix}_full_runtime_upload_not_authorized")
    return authorization


def _float(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    parsed = float(value)
    return parsed if math.isfinite(parsed) else None


def _close(left: object, right: object, *, tolerance: float = 0.001) -> bool:
    left_value = _float(left)
    right_value = _float(right)
    return left_value is not None and right_value is not None and abs(left_value - right_value) <= tolerance


def _parse_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    try:
        parsed = datetime.fromisoformat(text[:-1] + "+00:00" if text.endswith("Z") else text)
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(UTC)


def _timestamp_issues(
    *,
    prefix: str,
    value: object,
    observed_at: datetime,
    issues: list[str],
) -> datetime | None:
    parsed = _parse_timestamp(value)
    if parsed is None:
        issues.append(f"{prefix}_generated_at_invalid_or_timezone_missing")
        return None
    if parsed > observed_at + timedelta(seconds=MAX_FUTURE_SKEW_SECONDS):
        issues.append(f"{prefix}_generated_at_future")
    if observed_at - parsed > timedelta(seconds=MAX_EVIDENCE_AGE_SECONDS):
        issues.append(f"{prefix}_generated_at_stale")
    return parsed


def _exact_keys(value: dict[str, Any], expected: set[str]) -> bool:
    return set(value) == expected


def _raw_text_exposed(value: object) -> bool:
    if isinstance(value, dict):
        for key, child in value.items():
            normalized_key = str(key).strip().lower()
            if normalized_key in {
                "text",
                "actual_text",
                "raw_text",
                "transcript",
                "raw_transcript",
                "provider_transcript",
                "expected_transcript",
                "utterance",
                "prompt",
                "ground_truth",
                "operator_full_text_debug",
            }:
                return True
            if "transcript" in normalized_key and normalized_key not in {
                "raw_transcript_fields",
                "raw_provider_transcript_scored",
            }:
                return True
            if normalized_key == "expected_text" and isinstance(child, str):
                return True
            if normalized_key == "required_tokens" and any(isinstance(item, str) for item in _sequence(child)):
                return True
            if _raw_text_exposed(child):
                return True
    elif isinstance(value, list):
        return any(_raw_text_exposed(child) for child in value)
    return False


def _validate_source_envelope(
    payload: dict[str, Any],
    *,
    prefix: str,
    contract_name: str,
    generated_by: str,
    observed_at: datetime,
    current_head: str,
    current_fingerprint: str,
    issues: list[str],
    contract_version: int | None = None,
) -> datetime | None:
    if payload.get("contract_name") != contract_name:
        issues.append(f"{prefix}_contract_mismatch")
    if contract_version is not None and payload.get("contract_version") != contract_version:
        issues.append(f"{prefix}_contract_version_mismatch")
    if payload.get("generated_by") != generated_by:
        issues.append(f"{prefix}_generated_by_mismatch")
    generated = _timestamp_issues(
        prefix=prefix,
        value=payload.get("generated_at"),
        observed_at=observed_at,
        issues=issues,
    )
    if payload.get("head_semantics") != HEAD_SEMANTICS:
        issues.append(f"{prefix}_head_semantics_mismatch")
    if payload.get("source_git_head") != current_head:
        issues.append(f"{prefix}_source_git_head_not_current")
    if payload.get("source_state_fingerprint_semantics") != FINGERPRINT_SEMANTICS:
        issues.append(f"{prefix}_source_state_fingerprint_semantics_mismatch")
    if payload.get("source_state_fingerprint") != current_fingerprint:
        issues.append(f"{prefix}_source_state_fingerprint_not_current")
    return generated


def _candidate_values(candidate: dict[str, Any]) -> dict[str, Any]:
    bundle = _mapping(candidate.get("bundle"))
    audio = _mapping(candidate.get("audio"))
    entry = _mapping(candidate.get("candidate_manifest_entry"))
    expected_text = _mapping(entry.get("expected_text"))
    token_rows = _sequence(entry.get("required_tokens"))
    token_hashes = [
        str(_mapping(token).get("text_sha256") or "")
        for token in token_rows
        if isinstance(token, dict)
    ]
    review = _mapping(candidate.get("operator_ground_truth_review"))
    authorization = _mapping(entry.get("provider_upload_authorization"))
    return {
        "status": str(candidate.get("status") or ""),
        "failed_codes": list(candidate.get("failed_codes"))
        if isinstance(candidate.get("failed_codes"), list)
        else [],
        "audio_sha256": str(audio.get("sha256") or ""),
        "audio_duration_seconds": audio.get("duration_seconds"),
        "bundle_root": str(bundle.get("root") or ""),
        "bundle_id": str(bundle.get("id") or ""),
        "sample": str(entry.get("sample") or ""),
        "fixture_file": str(entry.get("file") or ""),
        "origin": str(entry.get("origin") or ""),
        "expected_text_chars": expected_text.get("text_chars"),
        "expected_text_sha256": str(expected_text.get("text_sha256") or ""),
        "required_token_sha256": token_hashes,
        "speaker_consent": str(entry.get("speaker_consent") or ""),
        "allowed_purpose": str(entry.get("allowed_purpose") or ""),
        "retention": str(entry.get("retention") or ""),
        "language": str(entry.get("language") or ""),
        "accent": str(entry.get("accent") or ""),
        "fixture_quality": _mapping(candidate.get("fixture_quality")),
        "privacy_mode": str(candidate.get("text_mode") or ""),
        "provider_upload_authorization": authorization,
        "operator_ground_truth_review_binding_sha256": str(review.get("sha256") or ""),
    }


def _ground_truth_review_payload(candidate: dict[str, Any], values: dict[str, Any]) -> dict[str, object]:
    review = _mapping(candidate.get("operator_ground_truth_review"))
    return {
        "contract_name": GROUND_TRUTH_REVIEW_BINDING_CONTRACT_NAME,
        "status": str(review.get("status") or ""),
        "reviewed_at": str(review.get("reviewed_at") or ""),
        "reviewer_authority": str(review.get("reviewer_authority") or ""),
        "audio_sha256": values["audio_sha256"],
        "bundle_id": values["bundle_id"],
        "sample": values["sample"],
        "expected_text_sha256": values["expected_text_sha256"],
        "required_token_sha256": list(values["required_token_sha256"]),
        "speaker_consent": values["speaker_consent"],
        "allowed_purpose": values["allowed_purpose"],
        "retention": values["retention"],
        "language": values["language"],
        "accent": values["accent"],
        "provider_upload_authorization": values["provider_upload_authorization"],
    }


def _candidate_binding_payload(candidate: dict[str, Any], values: dict[str, Any]) -> dict[str, object]:
    return {
        "contract_name": CANDIDATE_BINDING_CONTRACT_NAME,
        "status": values["status"],
        "failed_codes": sorted(values["failed_codes"]),
        "audio_sha256": values["audio_sha256"],
        "bundle_id": values["bundle_id"],
        "sample": values["sample"],
        "fixture_file": values["fixture_file"],
        "origin": values["origin"],
        "expected_text_sha256": values["expected_text_sha256"],
        "required_token_sha256": list(values["required_token_sha256"]),
        "speaker_consent": values["speaker_consent"],
        "allowed_purpose": values["allowed_purpose"],
        "retention": values["retention"],
        "language": values["language"],
        "accent": values["accent"],
        "fixture_quality": values["fixture_quality"],
        "privacy_mode": values["privacy_mode"],
        "provider_upload_authorization": values["provider_upload_authorization"],
        "operator_ground_truth_review_binding_sha256": values[
            "operator_ground_truth_review_binding_sha256"
        ],
    }


def _validate_candidate(
    candidate: dict[str, Any],
    *,
    observed_at: datetime,
    current_head: str,
    current_fingerprint: str,
    issues: list[str],
) -> tuple[dict[str, Any], datetime | None]:
    expected_top_keys = {
        "contract_name",
        "contract_version",
        "generated_at",
        "generated_by",
        "source_git_head",
        "head_semantics",
        "source_state_fingerprint",
        "source_state_fingerprint_semantics",
        "status",
        "failed_codes",
        "candidate_scope",
        "promotion_gate",
        "bundle",
        "audio",
        "fixture_quality",
        "candidate_manifest_entry",
        "operator_ground_truth_review",
        "candidate_binding",
        "privacy_mode",
        "text_mode",
        "raw_text_fields",
    }
    if not _exact_keys(candidate, expected_top_keys):
        issues.append("candidate_shape_invalid")
    generated_at = _validate_source_envelope(
        candidate,
        prefix="candidate",
        contract_name=CANDIDATE_CONTRACT_NAME,
        contract_version=CANDIDATE_CONTRACT_VERSION,
        generated_by=CANDIDATE_GENERATED_BY,
        observed_at=observed_at,
        current_head=current_head,
        current_fingerprint=current_fingerprint,
        issues=issues,
    )
    values = _candidate_values(candidate)
    candidate_failed_codes = _strict_failure_codes(
        candidate.get("failed_codes"),
        prefix="candidate",
        issues=issues,
        require_empty=candidate.get("status") == "pass",
        require_sorted=True,
    )
    values["failed_codes"] = candidate_failed_codes
    if candidate.get("status") != "pass" or candidate_failed_codes:
        issues.append("candidate_status_not_pass")
    if candidate.get("candidate_scope") != CANDIDATE_SCOPE:
        issues.append("candidate_scope_mismatch")
    if (
        candidate.get("text_mode") != "redacted"
        or candidate.get("privacy_mode") != "redacted"
        or candidate.get("raw_text_fields") is not False
    ):
        issues.append("candidate_redaction_contract_invalid")
    if _raw_text_exposed(candidate):
        issues.append("candidate_raw_text_exposed")
    authorization = _validate_upload_authorization(
        _mapping(candidate.get("candidate_manifest_entry")).get("provider_upload_authorization"),
        prefix="candidate",
        issues=issues,
    )
    values["provider_upload_authorization"] = authorization
    promotion_gate = _mapping(candidate.get("promotion_gate"))
    expected_promotion_gate = {
        "status": "pending_captured_candidate_benchmark",
        "required_receipt": ".codex-studio/published/memorial_stt_provider_benchmark_captured_candidate.generated.json",
        "required_rule": "captured candidate must pass full-runtime STT scoring against operator-confirmed ground truth before fixture-manifest promotion",
        "may_update_fixture_manifest": False,
        "next_action": "run_captured_candidate_benchmark_before_fixture_manifest",
    }
    if promotion_gate != expected_promotion_gate:
        issues.append("candidate_promotion_gate_invalid")

    bundle = _mapping(candidate.get("bundle"))
    audio = _mapping(candidate.get("audio"))
    entry = _mapping(candidate.get("candidate_manifest_entry"))
    expected_text = _mapping(entry.get("expected_text"))
    token_rows = _sequence(entry.get("required_tokens"))
    quality = _mapping(candidate.get("fixture_quality"))
    if not _exact_keys(
        bundle,
        {
            "root",
            "id",
            "id_sha256",
            "has_error_json",
            "event_type_code",
            "event_type_sha256",
            "reason_code",
            "reason_sha256",
        },
    ):
        issues.append("candidate_bundle_shape_invalid")
    if not isinstance(bundle.get("root"), str) or bundle.get("root") not in {
        "[memorial_stt_error_root]",
        "[external_root]",
    }:
        issues.append("candidate_bundle_root_invalid")
    if not isinstance(bundle.get("has_error_json"), bool):
        issues.append("candidate_bundle_has_error_json_invalid")
    if bundle.get("id_sha256") != _sha256_text(values["bundle_id"]):
        issues.append("candidate_bundle_id_sha256_mismatch")
    event_code = bundle.get("event_type_code")
    reason_code = bundle.get("reason_code")
    if not isinstance(event_code, str) or event_code not in {
        "",
        "other",
        "realtime_audio_turn",
    } or not isinstance(reason_code, str) or reason_code not in {
        "",
        "other",
        "empty_transcript",
        "generic",
        "generic_fallback_answer",
        "known_bad_transcript",
        "provider_error",
        "timeout",
        "unavailable",
    }:
        issues.append("candidate_bundle_metadata_invalid")
    for code, digest, prefix in (
        (event_code, bundle.get("event_type_sha256"), "event_type"),
        (reason_code, bundle.get("reason_sha256"), "reason"),
    ):
        if (code == "" and digest != "") or (
            isinstance(code, str) and code != "" and digest != _sha256_text(code)
        ):
            issues.append(f"candidate_bundle_{prefix}_binding_invalid")
    if not _exact_keys(
        audio,
        {
            "input_file",
            "sha256",
            "bytes",
            "max_bytes",
            "duration_seconds",
            "expected_min_duration_seconds",
            "max_duration_seconds",
        },
    ):
        issues.append("candidate_audio_shape_invalid")
    if audio.get("input_file") != "input.wav":
        issues.append("candidate_audio_input_file_invalid")
    audio_bytes = _strict_int(audio.get("bytes"), minimum=1)
    max_audio_bytes = _strict_int(audio.get("max_bytes"), minimum=1)
    if (
        audio_bytes is None
        or max_audio_bytes is None
        or max_audio_bytes > GOVERNED_MAX_AUDIO_BYTES
        or audio_bytes > max_audio_bytes
    ):
        issues.append("candidate_audio_byte_limits_invalid")
    candidate_quality_keys = {
        "status",
        "failed_codes",
        "audio_duration_seconds",
        "expected_min_duration_seconds",
        "max_duration_seconds",
    }
    if not _exact_keys(quality, candidate_quality_keys | {"wav_format"}):
        issues.append("candidate_fixture_quality_shape_invalid")
    quality_failed_codes = _strict_failure_codes(
        quality.get("failed_codes"),
        prefix="candidate_fixture_quality",
        issues=issues,
        require_empty=quality.get("status") == "pass",
    )
    if not isinstance(values["bundle_id"], str) or _SAFE_BUNDLE_ID_RE.fullmatch(values["bundle_id"]) is None:
        issues.append("candidate_bundle_id_invalid")
    if (
        not isinstance(values["sample"], str)
        or _SAFE_CANDIDATE_SAMPLE_RE.fullmatch(values["sample"]) is None
        or values["sample"] == "technical_retry"
    ):
        issues.append("candidate_sample_invalid")
    if not _valid_sha256(values["audio_sha256"]):
        issues.append("candidate_audio_sha256_invalid")
    if audio.get("expected_min_duration_seconds") != quality.get("expected_min_duration_seconds"):
        issues.append("candidate_audio_expected_min_duration_quality_mismatch")
    if audio.get("max_duration_seconds") != quality.get("max_duration_seconds"):
        issues.append("candidate_audio_max_duration_quality_mismatch")
    if entry.get("sha256") != values["audio_sha256"]:
        issues.append("candidate_manifest_audio_sha256_mismatch")
    if not _valid_sha256(values["expected_text_sha256"]):
        issues.append("candidate_expected_text_sha256_invalid")
    if expected_text.get("text_redacted") is not True or "text" in expected_text:
        issues.append("candidate_expected_text_not_redacted")
    if not _exact_keys(expected_text, {"text_chars", "text_sha256", "text_redacted"}) or _strict_int(
        expected_text.get("text_chars"), minimum=1
    ) is None:
        issues.append("candidate_expected_text_shape_invalid")
    if not token_rows or len(token_rows) != len(values["required_token_sha256"]):
        issues.append("candidate_required_token_rows_invalid")
    for token in token_rows:
        token_payload = _mapping(token)
        if (
            not _exact_keys(token_payload, {"text_chars", "text_sha256", "text_redacted"})
            or _strict_int(token_payload.get("text_chars"), minimum=1) is None
            or not _valid_sha256(token_payload.get("text_sha256"))
            or token_payload.get("text_redacted") is not True
            or "text" in token_payload
        ):
            issues.append("candidate_required_token_not_redacted_or_unbound")
            break
    if not all(_valid_sha256(value) for value in values["required_token_sha256"]):
        issues.append("candidate_required_token_sha256_invalid")
    if values["speaker_consent"] != AUTHORIZED_SPEAKER_CONSENT:
        issues.append("candidate_speaker_consent_not_authorized")
    if values["allowed_purpose"] != ALLOWED_PURPOSE:
        issues.append("candidate_allowed_purpose_mismatch")
    if values["retention"] not in AUTHORIZED_RETENTIONS:
        issues.append("candidate_retention_not_authorized")
    if values["language"] != AUTHORIZED_LANGUAGE:
        issues.append("candidate_language_not_authorized")
    if values["accent"] != AUTHORIZED_ACCENT:
        issues.append("candidate_accent_not_authorized")
    if quality.get("status") != "pass" or quality_failed_codes:
        issues.append("candidate_fixture_quality_not_pass")
    binding_payload_for_quality = _mapping(_mapping(candidate.get("candidate_binding")).get("payload"))
    if quality != binding_payload_for_quality.get("fixture_quality"):
        # The exact comparison below also catches this; this branch gives a useful blocker code.
        issues.append("candidate_fixture_quality_binding_mismatch")
    if not _close(audio.get("duration_seconds"), quality.get("audio_duration_seconds")):
        issues.append("candidate_audio_duration_quality_mismatch")
    duration = _float(quality.get("audio_duration_seconds"))
    expected_min_duration = _float(quality.get("expected_min_duration_seconds"))
    max_duration = _float(quality.get("max_duration_seconds"))
    if (
        duration is None
        or duration <= 0
        or expected_min_duration is None
        or expected_min_duration <= 0
        or max_duration is None
        or max_duration <= 0
        or max_duration > GOVERNED_MAX_AUDIO_DURATION_SECONDS
        or duration < expected_min_duration
        or duration > max_duration
        or expected_min_duration > max_duration
    ):
        issues.append("candidate_fixture_quality_duration_policy_invalid")
    wav_format = _mapping(quality.get("wav_format"))
    if (
        not _exact_keys(
            wav_format,
            {"audio_format", "channels", "sample_rate_hz", "sample_width_bytes"},
        )
        or _strict_int(wav_format.get("audio_format"), minimum=1) != 1
        or _strict_int(wav_format.get("channels"), minimum=1) != 1
        or _strict_int(wav_format.get("sample_rate_hz"), minimum=1) is None
        or _strict_int(wav_format.get("sample_width_bytes"), minimum=1) != 2
    ):
        issues.append("candidate_fixture_quality_wav_format_invalid")

    if not _exact_keys(
        entry,
        {
            "sample",
            "file",
            "origin",
            "speaker_consent",
            "allowed_purpose",
            "retention",
            "synthetic",
            "language",
            "accent",
            "expected_text",
            "required_tokens",
            "sha256",
            "provider_upload_authorization",
        },
    ):
        issues.append("candidate_manifest_entry_shape_invalid")
    if entry.get("synthetic") is not False:
        issues.append("candidate_manifest_entry_synthetic_invalid")
    fixture_file = entry.get("file")
    if (
        not isinstance(fixture_file, str)
        or not fixture_file
        or Path(fixture_file).name != fixture_file
        or fixture_file != f"{values['sample']}_captured.wav"
        or re.fullmatch(r"[a-z0-9_.-]+\.wav", fixture_file) is None
    ):
        issues.append("candidate_manifest_entry_file_invalid")
    if entry.get("origin") != AUTHORIZED_ORIGIN:
        issues.append("candidate_manifest_entry_origin_invalid")
    entry_authorization = _validate_upload_authorization(
        entry.get("provider_upload_authorization"),
        prefix="candidate_manifest_entry",
        issues=issues,
    )
    if entry_authorization != authorization:
        issues.append("candidate_manifest_entry_authorization_mismatch")

    review = _mapping(candidate.get("operator_ground_truth_review"))
    if not _exact_keys(
        review,
        {"contract_name", "status", "reviewed_at", "reviewer_authority", "sha256"},
    ):
        issues.append("candidate_ground_truth_review_shape_invalid")
    if review.get("contract_name") != GROUND_TRUTH_REVIEW_BINDING_CONTRACT_NAME:
        issues.append("candidate_ground_truth_review_contract_mismatch")
    if review.get("status") != "approved" or review.get("reviewer_authority") != AUTHORIZED_REVIEWER_AUTHORITY:
        issues.append("candidate_ground_truth_review_not_approved")
    review_time = _timestamp_issues(
        prefix="candidate_ground_truth_review",
        value=review.get("reviewed_at"),
        observed_at=observed_at,
        issues=issues,
    )
    if generated_at and review_time and review_time > generated_at + timedelta(seconds=MAX_FUTURE_SKEW_SECONDS):
        issues.append("candidate_ground_truth_review_after_candidate")
    expected_review_sha = _canonical_sha256(_ground_truth_review_payload(candidate, values))
    if review.get("sha256") != expected_review_sha:
        issues.append("candidate_ground_truth_review_binding_mismatch")

    binding = _mapping(candidate.get("candidate_binding"))
    if not _exact_keys(binding, {"contract_name", "canonicalization", "sha256", "payload"}):
        issues.append("candidate_binding_shape_invalid")
    if binding.get("contract_name") != CANDIDATE_BINDING_CONTRACT_NAME:
        issues.append("candidate_binding_contract_mismatch")
    if binding.get("canonicalization") != CANONICALIZATION:
        issues.append("candidate_binding_canonicalization_mismatch")
    expected_binding_payload = _candidate_binding_payload(candidate, values)
    if binding.get("payload") != expected_binding_payload:
        issues.append("candidate_binding_payload_mismatch")
    expected_binding_sha = _canonical_sha256(expected_binding_payload)
    if binding.get("sha256") != expected_binding_sha:
        issues.append("candidate_binding_sha256_mismatch")
    if values["operator_ground_truth_review_binding_sha256"] != expected_review_sha:
        issues.append("candidate_binding_ground_truth_review_mismatch")
    values.update(
        {
            "candidate_binding_sha256": expected_binding_sha,
            "candidate_binding_contract_name": CANDIDATE_BINDING_CONTRACT_NAME,
            "operator_ground_truth_review": review,
            "candidate_generated_at": str(candidate.get("generated_at") or ""),
        }
    )
    return values, generated_at


def _provider_failure_codes(result: dict[str, Any]) -> list[str]:
    codes: list[str] = []
    if result.get("fixture_invalid") is True:
        codes.append("fixture_invalid")
    if result.get("usable") is False:
        codes.append("transcript_unusable")
    if result.get("intent_correct") is False:
        codes.append("required_tokens_missing")
    token_f1 = _float(result.get("token_f1"))
    min_token_f1 = _float(result.get("min_token_f1"))
    if token_f1 is not None and min_token_f1 is not None and token_f1 < min_token_f1:
        codes.append("token_f1_below_min")
    wer = _float(result.get("wer"))
    max_wer = _float(result.get("max_wer"))
    if wer is not None and max_wer is not None and wer > max_wer:
        codes.append("wer_above_max")
    status = str(result.get("status") or "")
    if status in {"error", "http_error", "unavailable", "fixture_invalid"}:
        codes.append(f"provider_{status}")
    if status not in _ALLOWED_PROVIDER_STATUSES:
        codes.append("provider_status_invalid")
    if result.get("passed") is True and codes:
        codes.append("provider_pass_contradiction")
    return list(dict.fromkeys(codes))


def _provider_summary(result: dict[str, Any]) -> dict[str, object]:
    status = result.get("status")
    transcriber = _mapping(result.get("transcriber"))
    expected_text_sha256 = result.get("expected_text_sha256")
    actual_text_sha256 = result.get("actual_text_sha256")
    raw_token_hashes = result.get("required_token_sha256")
    token_hashes = (
        list(raw_token_hashes)
        if isinstance(raw_token_hashes, list)
        and all(_valid_sha256(item) for item in raw_token_hashes)
        else []
    )
    return {
        "status": status
        if isinstance(status, str) and status in _ALLOWED_PROVIDER_STATUSES
        else "[invalid]",
        "passed": result.get("passed") is True,
        "usable": result.get("usable") is True,
        "intent_correct": result.get("intent_correct") is True,
        "fixture_invalid": result.get("fixture_invalid") is True,
        "token_f1": _float(result.get("token_f1")),
        "governed_min_token_f1": GOVERNED_MIN_TOKEN_F1,
        "wer": _float(result.get("wer")),
        "governed_max_wer": GOVERNED_MAX_WER,
        "ms": _float(result.get("ms")),
        "transcriber": {
            "family": transcriber.get("family")
            if isinstance(transcriber.get("family"), str)
            and transcriber.get("family") in _TRANSCRIBER_FAMILIES
            else "unknown",
            "identifier_sha256": transcriber.get("identifier_sha256")
            if _valid_sha256(transcriber.get("identifier_sha256"))
            else "",
        },
        "expected_text_chars": _strict_int(result.get("expected_text_chars"), minimum=1),
        "actual_text_chars": _strict_int(result.get("actual_text_chars"), minimum=0),
        "expected_text_sha256": expected_text_sha256 if _valid_sha256(expected_text_sha256) else "",
        "actual_text_sha256": actual_text_sha256 if _valid_sha256(actual_text_sha256) else "",
        "required_token_count": _strict_int(result.get("required_token_count"), minimum=1),
        "required_token_sha256": token_hashes,
        "text_mode": "redacted" if result.get("text_mode") == "redacted" else "[invalid]",
        "text_redacted": result.get("text_redacted") is True,
        "failure_codes": _provider_failure_codes(result),
    }


def _validate_provider_error_value(
    value: object,
    *,
    prefix: str,
    field: str,
    issues: list[str],
) -> None:
    if value == "":
        return
    detail = _mapping(value)
    if (
        not _exact_keys(detail, {"contract_name", "category", "code", "detail_sha256"})
        or detail.get("contract_name") != PROVIDER_ERROR_DETAIL_CONTRACT_NAME
        or not isinstance(detail.get("category"), str)
        or detail.get("category") not in _PROVIDER_ERROR_CATEGORIES
        or not isinstance(detail.get("code"), str)
        or (
            detail.get("code") not in _PROVIDER_ERROR_CODES
            and _PROVIDER_ERROR_CODE_RE.fullmatch(str(detail.get("code") or "")) is None
        )
        or not _valid_sha256(detail.get("detail_sha256"))
    ):
        issues.append(f"{prefix}_{field}_invalid")


def _validate_provider_binding(
    result: dict[str, Any],
    *,
    provider: str,
    expected_text_sha256: str,
    expected_text_chars: int | None,
    required_token_sha256: list[str],
    authorized: bool,
    require_pass: bool,
    issues: list[str],
    governed_min_token_f1: float | None = None,
    governed_max_wer: float | None = None,
) -> None:
    prefix = f"benchmark_{provider}"
    if not _PROVIDER_RESULT_REQUIRED_KEYS.issubset(result) or not set(result).issubset(
        _PROVIDER_RESULT_KEYS
    ):
        issues.append(f"{prefix}_shape_invalid")
    status = result.get("status")
    if not isinstance(status, str) or status not in _ALLOWED_PROVIDER_STATUSES:
        issues.append(f"{prefix}_status_invalid")
    for field in ("passed", "usable", "intent_correct"):
        if not isinstance(result.get(field), bool):
            issues.append(f"{prefix}_{field}_type_invalid")
    if "fixture_invalid" in result and not isinstance(result.get("fixture_invalid"), bool):
        issues.append(f"{prefix}_fixture_invalid_type_invalid")
    if result.get("expected_text_sha256") != expected_text_sha256:
        issues.append(f"{prefix}_expected_text_binding_mismatch")
    raw_required_hashes = result.get("required_token_sha256")
    if not isinstance(raw_required_hashes, list) or raw_required_hashes != required_token_sha256:
        issues.append(f"{prefix}_required_token_binding_mismatch")
    if result.get("required_token_count") != len(required_token_sha256):
        issues.append(f"{prefix}_required_token_count_mismatch")
    if not _valid_sha256(result.get("actual_text_sha256")):
        issues.append(f"{prefix}_actual_text_sha256_invalid")
    result_expected_text_chars = _strict_int(result.get("expected_text_chars"), minimum=1)
    if result_expected_text_chars is None:
        issues.append(f"{prefix}_expected_text_chars_invalid")
    elif expected_text_chars is not None and result_expected_text_chars != expected_text_chars:
        issues.append(f"{prefix}_expected_text_chars_binding_mismatch")
    if _strict_int(result.get("actual_text_chars"), minimum=0) is None:
        issues.append(f"{prefix}_actual_text_chars_invalid")
    raw_transcriber = result.get("transcriber")
    transcriber = _mapping(raw_transcriber)
    if raw_transcriber is not None and (
        not _exact_keys(transcriber, {"family", "identifier_sha256"})
        or not isinstance(transcriber.get("family"), str)
        or transcriber.get("family") not in _TRANSCRIBER_FAMILIES
        or (
            transcriber.get("identifier_sha256") != ""
            and not _valid_sha256(transcriber.get("identifier_sha256"))
        )
    ):
        issues.append(f"{prefix}_transcriber_invalid")
    if require_pass and (
        transcriber.get("family") != "cartesia"
        or transcriber.get("identifier_sha256") != FULL_RUNTIME_TRANSCRIBER_SHA256
    ):
        issues.append(f"{prefix}_transcriber_invalid")
    if result.get("text_mode") != "redacted" or result.get("text_redacted") is not True:
        issues.append(f"{prefix}_redaction_binding_invalid")
    if _raw_text_exposed(result):
        issues.append(f"{prefix}_raw_text_exposed")
    for field in ("detail",):
        if field in result:
            _validate_provider_error_value(
                result.get(field),
                prefix=prefix,
                field=field,
                issues=issues,
            )
    if "scored_text_source" in result and (
        not isinstance(result.get("scored_text_source"), str)
        or result.get("scored_text_source") not in {"none", "primary_transcript_text"}
    ):
        issues.append(f"{prefix}_scored_text_source_invalid")
    for field in ("candidate_key_count", "sampled_keys"):
        if field in result and _strict_int(result.get(field), minimum=0) is None:
            issues.append(f"{prefix}_{field}_invalid")
    if "sample_strategy" in result and result.get("sample_strategy") != (
        "primary_plus_spread_fallbacks"
    ):
        issues.append(f"{prefix}_sample_strategy_invalid")
    token_f1 = _float(result.get("token_f1"))
    min_token_f1 = _float(result.get("min_token_f1"))
    wer = _float(result.get("wer"))
    max_wer = _float(result.get("max_wer"))
    latency_ms = _float(result.get("ms"))
    if token_f1 is None or not 0.0 <= token_f1 <= 1.0:
        issues.append(f"{prefix}_token_f1_invalid")
    if min_token_f1 is None or not 0.0 <= min_token_f1 <= 1.0:
        issues.append(f"{prefix}_min_token_f1_invalid")
    if (
        governed_min_token_f1 is not None
        and (min_token_f1 is None or min_token_f1 < governed_min_token_f1)
    ):
        issues.append(f"{prefix}_min_token_f1_policy_mismatch")
    if wer is None or wer < 0.0:
        issues.append(f"{prefix}_wer_invalid")
    if max_wer is None or max_wer < 0.0:
        issues.append(f"{prefix}_max_wer_invalid")
    if (
        governed_max_wer is not None
        and (max_wer is None or max_wer > governed_max_wer)
    ):
        issues.append(f"{prefix}_max_wer_policy_mismatch")
    if (require_pass or "ms" in result) and (latency_ms is None or latency_ms < 0.0):
        issues.append(f"{prefix}_latency_invalid")
    evidence_status = result.get("provider_evidence_status")
    evidence_failed_codes = _strict_failure_codes(
        result.get("provider_evidence_failed_codes"),
        prefix=f"{prefix}_provider_evidence",
        issues=issues,
        require_empty=evidence_status == "eligible",
        require_sorted=True,
    )
    if not isinstance(evidence_status, str) or evidence_status not in {"eligible", "blocked"}:
        issues.append(f"{prefix}_provider_evidence_status_invalid")
    passed = result.get("passed") is True
    successful = isinstance(status, str) and status in _SUCCESSFUL_PROVIDER_STATUSES
    fixture_invalid = result.get("fixture_invalid") is True
    if fixture_invalid:
        if (
            status != "fixture_invalid"
            or passed
            or evidence_status != "blocked"
            or not evidence_failed_codes
        ):
            issues.append(f"{prefix}_fixture_invalid_evidence_state_invalid")
    elif authorized:
        if status == "not_authorized":
            issues.append(f"{prefix}_authorization_status_contradiction")
        if successful:
            if evidence_status != "eligible" or evidence_failed_codes:
                issues.append(f"{prefix}_successful_evidence_state_invalid")
        elif evidence_status != "blocked" or not evidence_failed_codes or passed:
            issues.append(f"{prefix}_failed_evidence_state_invalid")
    else:
        if (
            status != "not_authorized"
            or passed
            or evidence_status != "blocked"
            or evidence_failed_codes != ["provider_upload_not_authorized"]
        ):
            issues.append(f"{prefix}_unauthorized_evidence_state_invalid")
    if (status == "fixture_invalid") is not fixture_invalid:
        issues.append(f"{prefix}_fixture_invalid_state_mismatch")
    expected_pass = bool(
        authorized
        and successful
        and evidence_status == "eligible"
        and not evidence_failed_codes
        and result.get("usable") is True
        and result.get("intent_correct") is True
        and not fixture_invalid
        and token_f1 is not None
        and min_token_f1 is not None
        and token_f1 >= min_token_f1
        and wer is not None
        and max_wer is not None
        and wer <= max_wer
    )
    if result.get("passed") is not expected_pass:
        issues.append(f"{prefix}_pass_contradiction")
    if result.get("actual_text_sha256") == expected_text_sha256 and (
        result_expected_text_chars != _strict_int(result.get("actual_text_chars"), minimum=0)
        or token_f1 is None
        or not _close(token_f1, 1.0, tolerance=1e-9)
        or wer is None
        or not _close(wer, 0.0, tolerance=1e-9)
        or result.get("usable") is not True
        or result.get("intent_correct") is not True
    ):
        issues.append(f"{prefix}_identical_text_metric_contradiction")
    if require_pass and (
        not passed
        or not expected_pass
        or not successful
        or transcriber.get("family") != "cartesia"
        or transcriber.get("identifier_sha256") != FULL_RUNTIME_TRANSCRIBER_SHA256
        or result.get("scored_text_source") != "primary_transcript_text"
    ):
        issues.append(f"{prefix}_not_pass")


def _validate_row_quality(
    quality: dict[str, Any],
    *,
    prefix: str,
    issues: list[str],
) -> list[str]:
    required_keys = {"status", "failed_codes", "audio_duration_seconds", "expected_min_duration_seconds"}
    if not _exact_keys(quality, required_keys | {"max_duration_seconds", "wav_format"}):
        issues.append(f"{prefix}_shape_invalid")
    failed_codes = _strict_failure_codes(
        quality.get("failed_codes"),
        prefix=prefix,
        issues=issues,
        require_empty=quality.get("status") == "pass",
    )
    duration = _float(quality.get("audio_duration_seconds"))
    expected_min_duration = _float(quality.get("expected_min_duration_seconds"))
    max_duration = _float(quality.get("max_duration_seconds")) if "max_duration_seconds" in quality else None
    if quality.get("status") != "pass" or failed_codes:
        issues.append(f"{prefix}_not_pass")
    if (
        duration is None
        or duration <= 0
        or expected_min_duration is None
        or expected_min_duration <= 0
        or duration < expected_min_duration
        or duration > GOVERNED_MAX_AUDIO_DURATION_SECONDS
        or max_duration is None
        or max_duration <= 0
        or max_duration > GOVERNED_MAX_AUDIO_DURATION_SECONDS
        or duration > max_duration
        or expected_min_duration > max_duration
    ):
        issues.append(f"{prefix}_duration_policy_invalid")
    wav_format = _mapping(quality.get("wav_format"))
    if (
        not _exact_keys(
            wav_format,
            {"audio_format", "channels", "sample_rate_hz", "sample_width_bytes"},
        )
        or _strict_int(wav_format.get("audio_format"), minimum=1) != 1
        or _strict_int(wav_format.get("channels"), minimum=1) != 1
        or _strict_int(wav_format.get("sample_rate_hz"), minimum=1) is None
        or _strict_int(wav_format.get("sample_width_bytes"), minimum=1) != 2
    ):
        issues.append(f"{prefix}_wav_format_invalid")
    return failed_codes


def _validate_transformation(
    transformation: dict[str, Any],
    *,
    row: dict[str, Any],
    candidate_values: dict[str, Any],
    expected_id: str,
    issues: list[str],
) -> dict[str, Any]:
    if not _exact_keys(transformation, {"contract_name", "canonicalization", "sha256", "payload"}):
        issues.append(f"benchmark_{expected_id}_transformation_shape_invalid")
    if transformation.get("contract_name") != TRANSFORMATION_CONTRACT_NAME:
        issues.append(f"benchmark_{expected_id}_transformation_contract_mismatch")
    if transformation.get("canonicalization") != CANONICALIZATION:
        issues.append(f"benchmark_{expected_id}_transformation_canonicalization_mismatch")
    payload = _mapping(transformation.get("payload"))
    expected_keys = {
        "contract_name",
        "transformation_id",
        "transformation_version",
        "source_audio_sha256",
        "output_audio_sha256",
        "source_duration_seconds",
        "output_duration_seconds",
        "duration_preserved",
        "parameters",
    }
    if not _exact_keys(payload, expected_keys):
        issues.append(f"benchmark_{expected_id}_transformation_payload_shape_invalid")
    if payload.get("contract_name") != TRANSFORMATION_CONTRACT_NAME:
        issues.append(f"benchmark_{expected_id}_transformation_payload_contract_mismatch")
    if payload.get("transformation_id") != expected_id or payload.get("transformation_version") != 1:
        issues.append(f"benchmark_{expected_id}_transformation_identity_mismatch")
    expected_parameters: dict[str, object] = (
        {}
        if expected_id == "identity_v1"
        else {
            "gain": 1.18,
            "echo_delay_ms": 76,
            "echo_mix": 0.22,
            "noise_cycle_pcm16": [132, -132, 66, -66],
            "speed_factor": 1.0,
        }
    )
    if payload.get("parameters") != expected_parameters:
        issues.append(f"benchmark_{expected_id}_transformation_parameters_invalid")
    if expected_id == "hostile_room_v1":
        parameters = _mapping(payload.get("parameters"))
        noise_cycle = parameters.get("noise_cycle_pcm16")
        if (
            not _close(parameters.get("gain"), 1.18, tolerance=1e-9)
            or _strict_int(parameters.get("echo_delay_ms"), minimum=1) != 76
            or not _close(parameters.get("echo_mix"), 0.22, tolerance=1e-9)
            or not isinstance(noise_cycle, list)
            or any(isinstance(item, bool) or not isinstance(item, int) for item in noise_cycle)
            or noise_cycle != [132, -132, 66, -66]
            or not _close(parameters.get("speed_factor"), 1.0, tolerance=1e-9)
        ):
            issues.append("benchmark_hostile_room_v1_transformation_parameter_types_invalid")
    try:
        expected_sha = _canonical_sha256(payload)
    except (TypeError, ValueError):
        expected_sha = ""
    if transformation.get("sha256") != expected_sha or not _valid_sha256(expected_sha):
        issues.append(f"benchmark_{expected_id}_transformation_sha256_mismatch")
    source_sha = str(row.get("source_fixture_sha256") or "")
    actual_sha = str(row.get("fixture_sha256") or "")
    if payload.get("source_audio_sha256") != source_sha:
        issues.append(f"benchmark_{expected_id}_transformation_source_mismatch")
    if payload.get("output_audio_sha256") != actual_sha:
        issues.append(f"benchmark_{expected_id}_transformation_output_mismatch")
    if not _close(payload.get("source_duration_seconds"), candidate_values["audio_duration_seconds"]):
        issues.append(f"benchmark_{expected_id}_transformation_source_duration_mismatch")
    quality = _mapping(row.get("fixture_quality"))
    if not _close(payload.get("output_duration_seconds"), quality.get("audio_duration_seconds")):
        issues.append(f"benchmark_{expected_id}_transformation_output_duration_mismatch")
    source_duration = _float(payload.get("source_duration_seconds"))
    output_duration = _float(payload.get("output_duration_seconds"))
    if source_duration is None or source_duration <= 0 or output_duration is None or output_duration <= 0:
        issues.append(f"benchmark_{expected_id}_transformation_duration_invalid")
    duration_preserved = (
        source_duration is not None
        and output_duration is not None
        and abs(source_duration - output_duration) <= 0.001
    )
    if payload.get("duration_preserved") is not duration_preserved:
        issues.append(f"benchmark_{expected_id}_duration_preserved_overclaim")
    if expected_id == "identity_v1" and not duration_preserved:
        issues.append("benchmark_identity_transformation_changed_duration")
    if expected_id == "identity_v1" and source_sha != actual_sha:
        issues.append("benchmark_identity_transformation_changed_audio")
    if expected_id == "hostile_room_v1" and source_sha == actual_sha:
        issues.append("benchmark_hostile_transformation_did_not_change_audio")
    return {
        "contract_name": TRANSFORMATION_CONTRACT_NAME
        if transformation.get("contract_name") == TRANSFORMATION_CONTRACT_NAME
        else "[invalid]",
        "transformation_id": expected_id
        if payload.get("transformation_id") == expected_id
        else "[invalid]",
        "transformation_version": 1 if payload.get("transformation_version") == 1 else None,
        "source_audio_sha256": payload.get("source_audio_sha256")
        if _valid_sha256(payload.get("source_audio_sha256"))
        else "",
        "output_audio_sha256": payload.get("output_audio_sha256")
        if _valid_sha256(payload.get("output_audio_sha256"))
        else "",
        "source_duration_seconds": _float(payload.get("source_duration_seconds")),
        "output_duration_seconds": _float(payload.get("output_duration_seconds")),
        "duration_preserved": payload.get("duration_preserved") is True,
        "sha256": transformation.get("sha256") if _valid_sha256(transformation.get("sha256")) else "",
    }


def _candidate_associated_row(
    row: dict[str, Any],
    candidate_values: dict[str, Any],
    *,
    candidate_receipt_sha256: str,
) -> bool:
    provenance = _mapping(row.get("provenance"))
    row_binding = _mapping(row.get("captured_candidate_binding"))
    transformation_payload = _mapping(_mapping(row.get("transformation")).get("payload"))
    sample = str(candidate_values.get("sample") or "")
    source_audio_sha256 = candidate_values.get("audio_sha256")
    bundle_id = candidate_values.get("bundle_id")
    candidate_binding_sha256 = candidate_values.get("candidate_binding_sha256")
    review_binding_sha256 = candidate_values.get("operator_ground_truth_review_binding_sha256")
    markers = (
        provenance.get("external_bundle") is True,
        bool(sample) and row.get("sample") in {sample, f"{sample}_hostile"},
        bool(source_audio_sha256) and row.get("source_fixture_sha256") == source_audio_sha256,
        bool(source_audio_sha256) and row.get("fixture_sha256") == source_audio_sha256,
        bool(bundle_id) and provenance.get("bundle_id") == bundle_id,
        bool(candidate_receipt_sha256)
        and provenance.get("candidate_receipt_sha256") == candidate_receipt_sha256,
        bool(candidate_binding_sha256)
        and provenance.get("candidate_binding_sha256") == candidate_binding_sha256,
        bool(review_binding_sha256)
        and provenance.get("operator_ground_truth_review_binding_sha256") == review_binding_sha256,
        bool(candidate_receipt_sha256)
        and row_binding.get("candidate_receipt_sha256") == candidate_receipt_sha256,
        bool(candidate_binding_sha256)
        and row_binding.get("candidate_binding_sha256") == candidate_binding_sha256,
        bool(review_binding_sha256)
        and row_binding.get("operator_ground_truth_review_binding_sha256") == review_binding_sha256,
        bool(source_audio_sha256) and row_binding.get("source_audio_sha256") == source_audio_sha256,
        bool(bundle_id) and row_binding.get("bundle_id") == bundle_id,
        bool(sample) and row_binding.get("sample") == sample,
        bool(source_audio_sha256)
        and transformation_payload.get("source_audio_sha256") == source_audio_sha256,
        bool(source_audio_sha256)
        and transformation_payload.get("output_audio_sha256") == source_audio_sha256,
    )
    return any(markers)


def _validate_external_row(
    row: dict[str, Any],
    *,
    candidate_values: dict[str, Any],
    candidate_receipt_sha256: str,
    expected_sample: str,
    expected_variant: str,
    expected_transformation_id: str,
    issues: list[str],
) -> dict[str, object]:
    row_prefix = f"benchmark_{expected_variant}_row"
    if not _exact_keys(
        row,
        {
            "sample",
            "variant",
            "fixture",
            "fixture_sha256",
            "source_fixture_sha256",
            "fixture_quality",
            "source_fixture_quality",
            "transformation",
            "provenance",
            "captured_candidate_binding",
            "provider_upload_authorization",
            "shadow",
            "onemin_sample",
            "full_runtime",
        },
    ):
        issues.append(f"{row_prefix}_shape_invalid")
    if row.get("sample") != expected_sample or row.get("variant") != expected_variant:
        issues.append(f"{row_prefix}_identity_mismatch")
    if row.get("fixture") != "input.wav":
        issues.append(f"{row_prefix}_fixture_mismatch")
    source_sha = str(row.get("source_fixture_sha256") or "")
    actual_sha = str(row.get("fixture_sha256") or "")
    if source_sha != candidate_values["audio_sha256"]:
        issues.append(f"{row_prefix}_source_fixture_mismatch")
    if not _valid_sha256(actual_sha):
        issues.append(f"{row_prefix}_actual_fixture_sha256_invalid")
    if expected_variant == "captured" and actual_sha != source_sha:
        issues.append("benchmark_captured_actual_fixture_not_identity")
    if expected_variant == "hostile" and actual_sha == source_sha:
        issues.append("benchmark_hostile_actual_fixture_not_transformed")

    provenance = _mapping(row.get("provenance"))
    if not _exact_keys(
        provenance,
        {
            "origin",
            "speaker_consent",
            "allowed_purpose",
            "retention",
            "synthetic",
            "accent",
            "external_bundle",
            "bundle_root",
            "bundle_id",
            "candidate_receipt_sha256",
            "candidate_binding_contract_name",
            "candidate_binding_sha256",
            "operator_ground_truth_review_binding_sha256",
            "provider_upload_authorization",
        },
    ):
        issues.append(f"{row_prefix}_provenance_shape_invalid")
    if provenance.get("external_bundle") is not True or provenance.get("synthetic") is not False:
        issues.append(f"{row_prefix}_external_provenance_invalid")
    expected_provenance = {
        "origin": AUTHORIZED_ORIGIN,
        "bundle_root": candidate_values["bundle_root"],
        "bundle_id": candidate_values["bundle_id"],
        "speaker_consent": candidate_values["speaker_consent"],
        "allowed_purpose": candidate_values["allowed_purpose"],
        "retention": candidate_values["retention"],
        "accent": candidate_values["accent"],
        "candidate_receipt_sha256": candidate_receipt_sha256,
        "candidate_binding_contract_name": CANDIDATE_BINDING_CONTRACT_NAME,
        "candidate_binding_sha256": candidate_values["candidate_binding_sha256"],
        "operator_ground_truth_review_binding_sha256": candidate_values[
            "operator_ground_truth_review_binding_sha256"
        ],
        "provider_upload_authorization": candidate_values["provider_upload_authorization"],
    }
    for key, expected in expected_provenance.items():
        if provenance.get(key) != expected:
            issues.append(f"{row_prefix}_provenance_{key}_mismatch")
    if "language" in provenance and provenance.get("language") != candidate_values["language"]:
        issues.append(f"{row_prefix}_provenance_language_mismatch")
    row_authorization = _validate_upload_authorization(
        row.get("provider_upload_authorization"),
        prefix=row_prefix,
        issues=issues,
    )
    if row_authorization != candidate_values["provider_upload_authorization"]:
        issues.append(f"{row_prefix}_provider_upload_authorization_mismatch")
    expected_row_binding = {
        "candidate_receipt_sha256": candidate_receipt_sha256,
        "candidate_binding_contract_name": CANDIDATE_BINDING_CONTRACT_NAME,
        "candidate_binding_sha256": candidate_values["candidate_binding_sha256"],
        "operator_ground_truth_review_binding_sha256": candidate_values[
            "operator_ground_truth_review_binding_sha256"
        ],
        "source_audio_sha256": candidate_values["audio_sha256"],
        "bundle_id": candidate_values["bundle_id"],
        "sample": candidate_values["sample"],
        "provider_upload_authorization": candidate_values["provider_upload_authorization"],
    }
    if _mapping(row.get("captured_candidate_binding")) != expected_row_binding:
        issues.append(f"{row_prefix}_captured_candidate_binding_mismatch")

    quality = _mapping(row.get("fixture_quality"))
    quality_failed_codes = _validate_row_quality(
        quality,
        prefix=f"{row_prefix}_fixture_quality",
        issues=issues,
    )
    if not _close(
        quality.get("expected_min_duration_seconds"),
        _mapping(candidate_values.get("fixture_quality")).get("expected_min_duration_seconds"),
    ):
        issues.append(f"{row_prefix}_fixture_quality_expected_duration_mismatch")
    source_quality = _mapping(row.get("source_fixture_quality"))
    _validate_row_quality(
        source_quality,
        prefix=f"{row_prefix}_source_fixture_quality",
        issues=issues,
    )
    if not _close(source_quality.get("audio_duration_seconds"), candidate_values["audio_duration_seconds"]):
        issues.append(f"{row_prefix}_source_fixture_quality_duration_mismatch")
    transformation_summary = _validate_transformation(
        _mapping(row.get("transformation")),
        row=row,
        candidate_values=candidate_values,
        expected_id=expected_transformation_id,
        issues=issues,
    )
    providers: dict[str, object] = {}
    authorization = _mapping(candidate_values.get("provider_upload_authorization"))
    for provider in ("full_runtime", "onemin_sample", "shadow"):
        result = _mapping(row.get(provider))
        _validate_provider_binding(
            result,
            provider=f"{expected_variant}_{provider}",
            expected_text_sha256=candidate_values["expected_text_sha256"],
            expected_text_chars=_strict_int(candidate_values.get("expected_text_chars"), minimum=1),
            required_token_sha256=list(candidate_values["required_token_sha256"]),
            authorized=authorization.get(provider) is True,
            require_pass=provider == "full_runtime",
            issues=issues,
            governed_min_token_f1=GOVERNED_MIN_TOKEN_F1,
            governed_max_wer=GOVERNED_MAX_WER,
        )
        if authorization.get(provider) is False and (
            result.get("status") != "not_authorized"
            or result.get("passed") is not False
            or result.get("provider_evidence_status") != "blocked"
            or "provider_upload_not_authorized"
            not in (
                result.get("provider_evidence_failed_codes")
                if isinstance(result.get("provider_evidence_failed_codes"), list)
                else []
            )
        ):
            issues.append(f"benchmark_{expected_variant}_{provider}_unauthorized_upload_evidence_invalid")
        providers[provider] = _provider_summary(result)
    return {
        "sample_sha256": _sha256_text(expected_sample),
        "variant": expected_variant,
        "source_fixture_sha256": source_sha if _valid_sha256(source_sha) else "",
        "actual_fixture_sha256": actual_sha if _valid_sha256(actual_sha) else "",
        "fixture_quality": {
            "status": "pass" if quality.get("status") == "pass" else "blocked",
            "failed_code_sha256": _hashed_strings(
                list(quality.get("failed_codes")) if isinstance(quality.get("failed_codes"), list) else []
            ),
            "audio_duration_seconds": _float(quality.get("audio_duration_seconds")),
            "expected_min_duration_seconds": _float(quality.get("expected_min_duration_seconds")),
        },
        "provenance": {
            "external_bundle": provenance.get("external_bundle") is True,
            "synthetic": provenance.get("synthetic") is True,
            "speaker_consent_authorized": provenance.get("speaker_consent") == AUTHORIZED_SPEAKER_CONSENT,
            "allowed_purpose_authorized": provenance.get("allowed_purpose") == ALLOWED_PURPOSE,
            "retention_authorized": provenance.get("retention") in AUTHORIZED_RETENTIONS,
            "language_authorized": provenance.get("language", candidate_values["language"])
            == AUTHORIZED_LANGUAGE,
            "accent_sha256": _sha256_text(str(provenance.get("accent")))
            if _safe_bounded_text(provenance.get("accent"), max_chars=64)
            else "",
            "candidate_receipt_sha256": provenance.get("candidate_receipt_sha256")
            if _valid_sha256(provenance.get("candidate_receipt_sha256"))
            else "",
            "candidate_binding_sha256": provenance.get("candidate_binding_sha256")
            if _valid_sha256(provenance.get("candidate_binding_sha256"))
            else "",
            "operator_ground_truth_review_binding_sha256": provenance.get(
                "operator_ground_truth_review_binding_sha256"
            )
            if _valid_sha256(provenance.get("operator_ground_truth_review_binding_sha256"))
            else "",
            "provider_upload_authorization": {
                key: _mapping(candidate_values.get("provider_upload_authorization")).get(key) is True
                for key in sorted(_AUTHORIZATION_KEYS)
            },
        },
        "transformation": transformation_summary,
        "providers": providers,
        "row_failure_codes": _provider_failure_codes(_mapping(row.get("full_runtime")))
        + (["fixture_quality_failed"] if quality_failed_codes else []),
    }


def _governed_benchmark_row_specs(
    *,
    candidate_values: dict[str, Any],
    candidate_receipt_sha256: str,
    issues: list[str],
) -> dict[tuple[str, str], dict[str, object]]:
    specs = _tracked_benchmark_specs(issues=issues)
    sample = str(candidate_values.get("sample") or "")
    if not sample:
        issues.append("benchmark_candidate_row_spec_missing")
        return specs
    authorization = _mapping(candidate_values.get("provider_upload_authorization"))
    captured_binding = {
        "candidate_receipt_sha256": candidate_receipt_sha256,
        "candidate_binding_contract_name": CANDIDATE_BINDING_CONTRACT_NAME,
        "candidate_binding_sha256": candidate_values.get("candidate_binding_sha256", ""),
        "operator_ground_truth_review_binding_sha256": candidate_values.get(
            "operator_ground_truth_review_binding_sha256", ""
        ),
        "source_audio_sha256": candidate_values.get("audio_sha256", ""),
        "bundle_id": candidate_values.get("bundle_id", ""),
        "sample": sample,
        "provider_upload_authorization": authorization,
    }
    provenance = {
        "origin": AUTHORIZED_ORIGIN,
        "speaker_consent": candidate_values.get("speaker_consent", ""),
        "allowed_purpose": candidate_values.get("allowed_purpose", ""),
        "retention": candidate_values.get("retention", ""),
        "synthetic": False,
        "accent": candidate_values.get("accent", ""),
        "external_bundle": True,
        "bundle_root": candidate_values.get("bundle_root", ""),
        "bundle_id": candidate_values.get("bundle_id", ""),
        "candidate_receipt_sha256": candidate_receipt_sha256,
        "candidate_binding_contract_name": CANDIDATE_BINDING_CONTRACT_NAME,
        "candidate_binding_sha256": candidate_values.get("candidate_binding_sha256", ""),
        "operator_ground_truth_review_binding_sha256": candidate_values.get(
            "operator_ground_truth_review_binding_sha256", ""
        ),
        "provider_upload_authorization": authorization,
    }
    quality = _mapping(candidate_values.get("fixture_quality"))
    common: dict[str, object] = {
        "fixture": "input.wav",
        "source_fixture_sha256": candidate_values.get("audio_sha256", ""),
        "expected_text_sha256": candidate_values.get("expected_text_sha256", ""),
        "expected_text_chars": candidate_values.get("expected_text_chars"),
        "required_token_sha256": list(candidate_values.get("required_token_sha256") or []),
        "min_token_f1": GOVERNED_MIN_TOKEN_F1,
        "max_wer": GOVERNED_MAX_WER,
        "expected_min_duration_seconds": quality.get("expected_min_duration_seconds"),
        "provider_upload_authorization": authorization,
        "provenance": provenance,
        "captured_candidate_binding": captured_binding,
        "candidate": True,
    }
    specs[(sample, "captured")] = {
        **common,
        "sample": sample,
        "variant": "captured",
        "transformation_id": "identity_v1",
    }
    specs[(f"{sample}_hostile", "hostile")] = {
        **common,
        "sample": f"{sample}_hostile",
        "variant": "hostile",
        "transformation_id": "hostile_room_v1",
    }
    return specs


def _validate_all_benchmark_rows(
    rows: list[dict[str, Any]],
    *,
    candidate_values: dict[str, Any],
    candidate_receipt_sha256: str,
    issues: list[str],
) -> None:
    specs = _governed_benchmark_row_specs(
        candidate_values=candidate_values,
        candidate_receipt_sha256=candidate_receipt_sha256,
        issues=issues,
    )
    identities = [(str(row.get("sample") or ""), str(row.get("variant") or "")) for row in rows]
    if len(set(identities)) != len(identities):
        issues.append("benchmark_row_identity_duplicated")
    if set(identities) != set(specs) or len(identities) != len(specs):
        issues.append("benchmark_governed_row_set_mismatch")

    for index, row in enumerate(rows):
        sample = str(row.get("sample") or "")
        variant = str(row.get("variant") or "")
        prefix = f"benchmark_row_{index}"
        if not _exact_keys(row, _ROW_KEYS):
            issues.append(f"{prefix}_shape_invalid")
        spec = specs.get((sample, variant))
        if spec is None:
            issues.append(f"{prefix}_identity_not_governed")
            continue
        if not _safe_id(sample) or variant not in {"captured", "synthetic", "hostile"}:
            issues.append(f"{prefix}_identity_invalid")
        if row.get("fixture") != spec.get("fixture"):
            issues.append(f"{prefix}_fixture_mismatch")
        source_sha = str(row.get("source_fixture_sha256") or "")
        actual_sha = str(row.get("fixture_sha256") or "")
        if source_sha != spec.get("source_fixture_sha256"):
            issues.append(f"{prefix}_source_fixture_sha256_mismatch")
        if not _valid_sha256(actual_sha):
            issues.append(f"{prefix}_fixture_sha256_invalid")
        if variant in {"captured", "synthetic"} and actual_sha != source_sha:
            issues.append(f"{prefix}_identity_fixture_sha256_mismatch")
        if variant == "hostile" and actual_sha == source_sha:
            issues.append(f"{prefix}_hostile_fixture_sha256_not_transformed")

        expected_provenance = _mapping(spec.get("provenance"))
        provenance = _mapping(row.get("provenance"))
        expected_provenance_keys = (
            _CANDIDATE_PROVENANCE_KEYS if spec.get("candidate") is True else _TRACKED_PROVENANCE_KEYS
        )
        if not _exact_keys(provenance, expected_provenance_keys) or provenance != expected_provenance:
            issues.append(f"{prefix}_provenance_invalid")
        authorization = _validate_upload_authorization(
            row.get("provider_upload_authorization"),
            prefix=prefix,
            issues=issues,
        )
        if authorization != spec.get("provider_upload_authorization"):
            issues.append(f"{prefix}_provider_upload_authorization_mismatch")
        if _mapping(row.get("captured_candidate_binding")) != spec.get(
            "captured_candidate_binding"
        ):
            issues.append(f"{prefix}_captured_candidate_binding_mismatch")

        source_quality = _mapping(row.get("source_fixture_quality"))
        actual_quality = _mapping(row.get("fixture_quality"))
        _validate_row_quality(
            source_quality,
            prefix=f"{prefix}_source_fixture_quality",
            issues=issues,
        )
        _validate_row_quality(
            actual_quality,
            prefix=f"{prefix}_actual_fixture_quality",
            issues=issues,
        )
        for quality_name, quality in (
            ("source", source_quality),
            ("actual", actual_quality),
        ):
            if not _close(
                quality.get("expected_min_duration_seconds"),
                spec.get("expected_min_duration_seconds"),
                tolerance=1e-9,
            ):
                issues.append(f"{prefix}_{quality_name}_expected_min_duration_mismatch")
            if not _close(
                quality.get("max_duration_seconds"),
                GOVERNED_MAX_AUDIO_DURATION_SECONDS,
                tolerance=1e-9,
            ):
                issues.append(f"{prefix}_{quality_name}_max_duration_mismatch")
        if variant in {"captured", "synthetic"} and actual_quality != source_quality:
            issues.append(f"{prefix}_identity_quality_mismatch")
        _validate_transformation(
            _mapping(row.get("transformation")),
            row=row,
            candidate_values={"audio_duration_seconds": source_quality.get("audio_duration_seconds")},
            expected_id=str(spec.get("transformation_id") or ""),
            issues=issues,
        )

        expected_text_sha256 = str(spec.get("expected_text_sha256") or "")
        expected_text_chars = _strict_int(spec.get("expected_text_chars"), minimum=1)
        required_token_sha256 = list(spec.get("required_token_sha256") or [])
        if (
            not _valid_sha256(expected_text_sha256)
            or expected_text_chars is None
            or not required_token_sha256
            or not all(_valid_sha256(value) for value in required_token_sha256)
        ):
            issues.append(f"{prefix}_governed_text_binding_invalid")
        for provider in _RANKED_PROVIDERS:
            _validate_provider_binding(
                _mapping(row.get(provider)),
                provider=f"row_{index}_{provider}",
                expected_text_sha256=expected_text_sha256,
                expected_text_chars=expected_text_chars,
                required_token_sha256=required_token_sha256,
                authorized=authorization.get(provider) is True,
                require_pass=provider == "full_runtime",
                issues=issues,
                governed_min_token_f1=GOVERNED_MIN_TOKEN_F1,
                governed_max_wer=GOVERNED_MAX_WER,
            )


def _validate_benchmark_availability(value: object, *, issues: list[str]) -> None:
    availability = _mapping(value)
    if not _exact_keys(
        availability,
        {"providers", "credential_environment", "governance_preflight"},
    ):
        issues.append("benchmark_availability_shape_invalid")

    providers = _mapping(availability.get("providers"))
    if not _exact_keys(providers, set(_RANKED_PROVIDERS)):
        issues.append("benchmark_availability_providers_shape_invalid")
    full_runtime = _mapping(providers.get("full_runtime"))
    if (
        not _exact_keys(full_runtime, {"configured", "credential_source"})
        or full_runtime.get("configured") is not True
        or not isinstance(full_runtime.get("credential_source"), str)
        or full_runtime.get("credential_source")
        not in {
            "direct_env",
            "inline_json_env",
            "credential_file_env",
            "default_credential_file",
        }
    ):
        issues.append("benchmark_availability_full_runtime_invalid")
    shadow = _mapping(providers.get("shadow"))
    if (
        not _exact_keys(shadow, {"configured", "provider_family"})
        or not isinstance(shadow.get("configured"), bool)
        or not isinstance(shadow.get("provider_family"), str)
        or shadow.get("provider_family") not in {"blipai", "unknown"}
    ):
        issues.append("benchmark_availability_shadow_invalid")
    onemin = _mapping(providers.get("onemin_sample"))
    key_count = _strict_int(onemin.get("key_count"), minimum=0)
    max_key_attempts = _strict_int(onemin.get("max_key_attempts"), minimum=0)
    if (
        not _exact_keys(onemin, {"configured", "key_count", "max_key_attempts"})
        or not isinstance(onemin.get("configured"), bool)
        or key_count is None
        or max_key_attempts is None
        or (onemin.get("configured") is True) is not (bool(key_count))
    ):
        issues.append("benchmark_availability_onemin_invalid")

    environment = _mapping(availability.get("credential_environment"))
    families = _mapping(environment.get("provider_families"))
    if (
        not _exact_keys(environment, {"file_count", "loaded_count", "provider_families"})
        or _strict_int(environment.get("file_count"), minimum=0) is None
        or _strict_int(environment.get("loaded_count"), minimum=0) is None
        or not _exact_keys(families, {"cartesia", "onemin", "blipai_shadow"})
        or any(not isinstance(families.get(key), bool) for key in families)
    ):
        issues.append("benchmark_availability_credential_environment_invalid")

    governance = _mapping(availability.get("governance_preflight"))
    if not _exact_keys(
        governance,
        {
            "blocked",
            "failed_codes",
            "external_candidate_failed_codes",
            "tracked_fixture_failed_codes",
            "captured_candidate_pair_count",
        },
    ):
        issues.append("benchmark_availability_governance_preflight_shape_invalid")
    for field in (
        "failed_codes",
        "external_candidate_failed_codes",
        "tracked_fixture_failed_codes",
    ):
        _strict_failure_codes(
            governance.get(field),
            prefix=f"benchmark_availability_{field}",
            issues=issues,
            require_empty=True,
            require_sorted=True,
        )
    if governance.get("blocked") is not False:
        issues.append("benchmark_availability_governance_preflight_blocked")
    if _strict_int(governance.get("captured_candidate_pair_count"), minimum=0) != 1:
        issues.append("benchmark_availability_candidate_pair_count_invalid")


def _expected_provider_ranking(rows: list[dict[str, Any]]) -> list[dict[str, object]]:
    summaries: list[dict[str, object]] = []
    for provider in _RANKED_PROVIDERS:
        results = [_mapping(row.get(provider)) for row in rows]
        passed_samples = sum(result.get("passed") is True for result in results)
        scored = [result for result in results if "token_f1" in result]
        token_values = [(_float(result.get("token_f1")) or 0.0) for result in scored]
        wer_values = [
            (_float(result.get("wer")) if _float(result.get("wer")) is not None else 1.0)
            for result in results
            if "wer" in result
        ]
        latencies = [
            value
            for result in results
            for value in [_float(result.get("ms"))]
            if value is not None and value > 0.0
        ]
        summaries.append(
            {
                "provider": provider,
                "passed_samples": passed_samples,
                "sample_count": len(results),
                "scored_samples": len(scored),
                "intent_correct_samples": sum(
                    result.get("intent_correct") is True for result in results
                ),
                "avg_token_f1": round(sum(token_values) / len(scored), 4) if scored else 0.0,
                "avg_wer": round(sum(wer_values) / len(wer_values), 4)
                if wer_values
                else 1.0,
                "avg_latency_ms": round(sum(latencies) / len(latencies), 1)
                if latencies
                else 0.0,
                "production_eligible": passed_samples == len(results) and bool(results),
            }
        )
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


def _validate_provider_ranking(
    value: object,
    *,
    rows: list[dict[str, Any]],
    issues: list[str],
) -> None:
    raw_ranking = value
    if not isinstance(raw_ranking, list) or any(not isinstance(item, dict) for item in raw_ranking):
        issues.append("benchmark_provider_ranking_shape_invalid")
        return
    ranking = [dict(item) for item in raw_ranking]
    providers = [item.get("provider") for item in ranking]
    safe_providers = [provider for provider in providers if isinstance(provider, str)]
    if (
        len(ranking) != len(_RANKED_PROVIDERS)
        or len(safe_providers) != len(providers)
        or set(safe_providers) != set(_RANKED_PROVIDERS)
        or len(set(safe_providers)) != len(safe_providers)
    ):
        issues.append("benchmark_provider_ranking_provider_set_invalid")
    for index, item in enumerate(ranking):
        if not _exact_keys(item, _RANKING_KEYS):
            issues.append(f"benchmark_provider_ranking_{index}_shape_invalid")
        for field in (
            "passed_samples",
            "sample_count",
            "scored_samples",
            "intent_correct_samples",
        ):
            if _strict_int(item.get(field), minimum=0) is None:
                issues.append(f"benchmark_provider_ranking_{index}_{field}_invalid")
        for field in ("avg_token_f1", "avg_wer", "avg_latency_ms"):
            number = _float(item.get(field))
            if number is None or number < 0.0:
                issues.append(f"benchmark_provider_ranking_{index}_{field}_invalid")
        if not isinstance(item.get("production_eligible"), bool):
            issues.append(f"benchmark_provider_ranking_{index}_production_eligible_invalid")
    if ranking != _expected_provider_ranking(rows):
        issues.append("benchmark_provider_ranking_not_derived_from_rows")


def _validate_benchmark(
    benchmark: dict[str, Any],
    *,
    observed_at: datetime,
    current_head: str,
    current_fingerprint: str,
    candidate_values: dict[str, Any],
    candidate_receipt_sha256: str,
    candidate_generated_at: datetime | None,
    issues: list[str],
) -> tuple[list[dict[str, object]], datetime | None]:
    if not _exact_keys(
        benchmark,
        {
            "contract_name",
            "generated_at",
            "generated_by",
            "source_git_head",
            "head_semantics",
            "source_state_fingerprint",
            "source_state_fingerprint_semantics",
            "captured_candidate_binding",
            "status",
            "scoring",
            "fixture_quality_status",
            "fixture_quality_failed_codes",
            "availability",
            "provider_ranking",
            "rows",
        },
    ):
        issues.append("benchmark_shape_invalid")
    generated_at = _validate_source_envelope(
        benchmark,
        prefix="benchmark",
        contract_name=BENCHMARK_CONTRACT_NAME,
        generated_by=BENCHMARK_GENERATED_BY,
        observed_at=observed_at,
        current_head=current_head,
        current_fingerprint=current_fingerprint,
        issues=issues,
    )
    if candidate_generated_at and generated_at and generated_at + timedelta(seconds=MAX_FUTURE_SKEW_SECONDS) < candidate_generated_at:
        issues.append("benchmark_predates_candidate")
    if benchmark.get("status") != "pass":
        issues.append("benchmark_status_not_pass")
    benchmark_quality_failed_codes = _strict_failure_codes(
        benchmark.get("fixture_quality_failed_codes"),
        prefix="benchmark_fixture_quality",
        issues=issues,
        require_empty=benchmark.get("fixture_quality_status") == "pass",
        require_sorted=True,
    )
    if benchmark.get("fixture_quality_status") != "pass" or benchmark_quality_failed_codes:
        issues.append("benchmark_fixture_quality_gate_not_pass")
    scoring = _mapping(benchmark.get("scoring"))
    if scoring != _EXPECTED_SCORING:
        issues.append("benchmark_scoring_contract_invalid")
    if (
        scoring.get("text_mode") != "redacted"
        or scoring.get("raw_transcript_fields") is not False
        or scoring.get("redacted_text_fields") is not True
    ):
        issues.append("benchmark_redaction_contract_invalid")
    _validate_benchmark_availability(benchmark.get("availability"), issues=issues)
    if _raw_text_exposed(benchmark):
        issues.append("benchmark_raw_text_exposed")

    expected_top_binding = {
        "candidate_receipt_sha256": candidate_receipt_sha256,
        "candidate_binding_contract_name": CANDIDATE_BINDING_CONTRACT_NAME,
        "candidate_binding_sha256": candidate_values.get("candidate_binding_sha256", ""),
        "operator_ground_truth_review_binding_sha256": candidate_values.get(
            "operator_ground_truth_review_binding_sha256", ""
        ),
        "source_audio_sha256": candidate_values.get("audio_sha256", ""),
        "bundle_id": candidate_values.get("bundle_id", ""),
        "sample": candidate_values.get("sample", ""),
        "provider_upload_authorization": candidate_values.get("provider_upload_authorization", {}),
    }
    top_binding = _mapping(benchmark.get("captured_candidate_binding"))
    if top_binding != expected_top_binding:
        issues.append("benchmark_captured_candidate_binding_mismatch")

    raw_rows = _sequence(benchmark.get("rows"))
    if not raw_rows or any(not isinstance(row, dict) for row in raw_rows):
        issues.append("benchmark_rows_missing_or_invalid")
    rows = [dict(row) for row in raw_rows if isinstance(row, dict)]
    _validate_all_benchmark_rows(
        rows,
        candidate_values=candidate_values,
        candidate_receipt_sha256=candidate_receipt_sha256,
        issues=issues,
    )
    associated = [
        row
        for row in rows
        if _candidate_associated_row(
            row,
            candidate_values,
            candidate_receipt_sha256=candidate_receipt_sha256,
        )
    ]
    expected_sample = str(candidate_values.get("sample") or "")
    expected_identities = {(expected_sample, "captured"), (f"{expected_sample}_hostile", "hostile")}
    identities = [(str(row.get("sample") or ""), str(row.get("variant") or "")) for row in associated]
    if len(associated) != 2 or set(identities) != expected_identities or len(set(identities)) != len(identities):
        issues.append("benchmark_external_candidate_rows_not_exact_pair")

    row_summaries: list[dict[str, object]] = []
    for expected_row_sample, expected_variant, transformation_id in (
        (expected_sample, "captured", "identity_v1"),
        (f"{expected_sample}_hostile", "hostile", "hostile_room_v1"),
    ):
        matches = [
            row
            for row in associated
            if row.get("sample") == expected_row_sample and row.get("variant") == expected_variant
        ]
        if len(matches) != 1:
            issues.append(f"benchmark_{expected_variant}_row_missing_or_duplicated")
            continue
        row_summaries.append(
            _validate_external_row(
                matches[0],
                candidate_values=candidate_values,
                candidate_receipt_sha256=candidate_receipt_sha256,
                expected_sample=expected_row_sample,
                expected_variant=expected_variant,
                expected_transformation_id=transformation_id,
                issues=issues,
            )
        )

    _validate_provider_ranking(benchmark.get("provider_ranking"), rows=rows, issues=issues)
    expected_ranking = _expected_provider_ranking(rows)
    full_runtime_summary = next(
        (item for item in expected_ranking if item.get("provider") == "full_runtime"),
        {},
    )
    if full_runtime_summary.get("production_eligible") is not True:
        issues.append("benchmark_full_runtime_not_production_eligible")
    return row_summaries, generated_at


def _candidate_summary(candidate: dict[str, Any], values: dict[str, Any]) -> dict[str, object]:
    audio = _mapping(candidate.get("audio"))
    expected_text = _mapping(_mapping(candidate.get("candidate_manifest_entry")).get("expected_text"))
    review = _mapping(candidate.get("operator_ground_truth_review"))
    return {
        "status": "pass" if candidate.get("status") == "pass" else "blocked",
        "candidate_scope": CANDIDATE_SCOPE if candidate.get("candidate_scope") == CANDIDATE_SCOPE else "[invalid]",
        "failed_code_sha256": _hashed_strings(
            list(candidate.get("failed_codes")) if isinstance(candidate.get("failed_codes"), list) else []
        ),
        "bundle_id_sha256": _sha256_text(str(values.get("bundle_id") or "")),
        "audio_sha256": values.get("audio_sha256") if _valid_sha256(values.get("audio_sha256")) else "",
        "audio_bytes": _strict_int(audio.get("bytes"), minimum=1),
        "audio_duration_seconds": _float(values.get("audio_duration_seconds")),
        "sample_sha256": _sha256_text(str(values.get("sample") or "")),
        "expected_text_chars": _strict_int(expected_text.get("text_chars"), minimum=1),
        "expected_text_sha256": values.get("expected_text_sha256")
        if _valid_sha256(values.get("expected_text_sha256"))
        else "",
        "required_token_sha256": [
            value for value in list(values.get("required_token_sha256") or []) if _valid_sha256(value)
        ],
        "speaker_consent_authorized": values.get("speaker_consent") == AUTHORIZED_SPEAKER_CONSENT,
        "allowed_purpose_authorized": values.get("allowed_purpose") == ALLOWED_PURPOSE,
        "retention_authorized": values.get("retention") in AUTHORIZED_RETENTIONS,
        "language_authorized": values.get("language") == AUTHORIZED_LANGUAGE,
        "accent_sha256": _sha256_text(str(values.get("accent")))
        if _safe_bounded_text(values.get("accent"), max_chars=64)
        else "",
        "privacy_mode": "redacted" if values.get("privacy_mode") == "redacted" else "[invalid]",
        "provider_upload_authorization": {
            key: _mapping(values.get("provider_upload_authorization")).get(key) is True
            for key in sorted(_AUTHORIZATION_KEYS)
        },
        "candidate_binding": {
            "contract_name": CANDIDATE_BINDING_CONTRACT_NAME,
            "sha256": values.get("candidate_binding_sha256")
            if _valid_sha256(values.get("candidate_binding_sha256"))
            else "",
        },
        "operator_ground_truth_review": {
            "contract_name": GROUND_TRUTH_REVIEW_BINDING_CONTRACT_NAME
            if review.get("contract_name") == GROUND_TRUTH_REVIEW_BINDING_CONTRACT_NAME
            else "[invalid]",
            "status": "approved" if review.get("status") == "approved" else "[invalid]",
            "reviewed_at": str(review.get("reviewed_at") or "")
            if _parse_timestamp(review.get("reviewed_at")) is not None
            else "",
            "reviewer_authority": AUTHORIZED_REVIEWER_AUTHORITY
            if review.get("reviewer_authority") == AUTHORIZED_REVIEWER_AUTHORITY
            else "[invalid]",
            "sha256": review.get("sha256") if _valid_sha256(review.get("sha256")) else "",
        },
        "raw_text_fields": candidate.get("raw_text_fields") is True,
    }


def build_diagnostic(
    *,
    candidate_receipt_path: Path = DEFAULT_CANDIDATE_RECEIPT,
    benchmark_receipt_path: Path = DEFAULT_BENCHMARK_RECEIPT,
    generated_at: str = "",
) -> dict[str, object]:
    candidate, candidate_entry = _load_json_with_entry(candidate_receipt_path)
    benchmark, benchmark_entry = _load_json_with_entry(benchmark_receipt_path)
    candidate_entry["path"] = "[candidate_receipt]"
    benchmark_entry["path"] = "[benchmark_receipt]"
    receipt_generated_at = generated_at or _utc_now()
    if _parse_timestamp(receipt_generated_at) is None:
        raise ValueError("diagnostic_generated_at_invalid_or_timezone_missing")
    observed = datetime.now(UTC)
    issues: list[str] = []
    _timestamp_issues(
        prefix="diagnostic",
        value=receipt_generated_at,
        observed_at=observed,
        issues=issues,
    )
    current_head = resolve_source_state_head(ROOT)
    current_fingerprint = resolve_source_worktree_fingerprint(ROOT)
    if not candidate:
        issues.append("candidate_receipt_missing_or_invalid")
    if not benchmark:
        issues.append("captured_benchmark_receipt_missing_or_invalid")

    candidate_values: dict[str, Any] = _candidate_values(candidate) if candidate else {}
    candidate_generated: datetime | None = None
    if candidate:
        candidate_values, candidate_generated = _validate_candidate(
            candidate,
            observed_at=observed,
            current_head=current_head,
            current_fingerprint=current_fingerprint,
            issues=issues,
        )
    candidate_receipt_sha256 = str(candidate_entry.get("sha256") or "")
    captured_rows: list[dict[str, object]] = []
    benchmark_generated: datetime | None = None
    if benchmark:
        captured_rows, benchmark_generated = _validate_benchmark(
            benchmark,
            observed_at=observed,
            current_head=current_head,
            current_fingerprint=current_fingerprint,
            candidate_values=candidate_values,
            candidate_receipt_sha256=candidate_receipt_sha256,
            candidate_generated_at=candidate_generated,
            issues=issues,
        )
    diagnostic_generated = _parse_timestamp(receipt_generated_at)
    if benchmark_generated and diagnostic_generated and diagnostic_generated + timedelta(seconds=MAX_FUTURE_SKEW_SECONDS) < benchmark_generated:
        issues.append("diagnostic_predates_benchmark")

    input_payload = {
        "contract_name": INPUT_BINDING_CONTRACT_NAME,
        "candidate_receipt_sha256": candidate_receipt_sha256,
        "benchmark_receipt_sha256": str(benchmark_entry.get("sha256") or ""),
        "candidate_binding_sha256": str(candidate_values.get("candidate_binding_sha256") or ""),
        "operator_ground_truth_review_binding_sha256": str(
            candidate_values.get("operator_ground_truth_review_binding_sha256") or ""
        ),
        "source_audio_sha256": str(candidate_values.get("audio_sha256") or ""),
        "source_git_head": current_head,
        "source_state_fingerprint": current_fingerprint,
    }
    input_binding_sha256 = _canonical_sha256(input_payload)
    input_binding = {
        "contract_name": INPUT_BINDING_CONTRACT_NAME,
        "canonicalization": CANONICALIZATION,
        "sha256": input_binding_sha256,
        "payload": input_payload,
    }
    unique_issues = sorted(set(issues))
    promotion_allowed = not unique_issues
    fixture_blockers = sorted(
        {
            code_sha256
            for row in captured_rows
            for code_sha256 in (
                _mapping(row.get("fixture_quality")).get("failed_code_sha256")
                if isinstance(_mapping(row.get("fixture_quality")).get("failed_code_sha256"), list)
                else []
            )
            if _valid_sha256(code_sha256)
        }
    )
    full_runtime_failed_rows = [
        {
            "sample_sha256": row.get("sample_sha256") if _valid_sha256(row.get("sample_sha256")) else "",
            "variant": str(row.get("variant") or ""),
            "failure_codes": list(row.get("row_failure_codes") or []),
        }
        for row in captured_rows
        if _mapping(_mapping(row.get("providers")).get("full_runtime")).get("passed") is not True
    ]
    return {
        "contract_name": CONTRACT_NAME,
        "contract_version": CONTRACT_VERSION,
        "generated_at": receipt_generated_at,
        "generated_by": GENERATED_BY,
        "source_git_head": current_head,
        "head_semantics": HEAD_SEMANTICS,
        "source_state_fingerprint": current_fingerprint,
        "source_state_fingerprint_semantics": FINGERPRINT_SEMANTICS,
        "status": "pass" if promotion_allowed else "blocked",
        "diagnostic_status": "ready" if candidate and benchmark else "incomplete",
        "promotion_allowed": promotion_allowed,
        "may_update_fixture_manifest": promotion_allowed,
        "issues": unique_issues,
        "input_binding": input_binding,
        "input_binding_sha256": input_binding_sha256,
        "candidate_receipt": candidate_entry,
        "benchmark_receipt": benchmark_entry,
        "candidate": _candidate_summary(candidate, candidate_values) if candidate else {},
        "benchmark_status": "pass" if benchmark.get("status") == "pass" else "blocked",
        "benchmark_fixture_quality_status": "pass"
        if benchmark.get("fixture_quality_status") == "pass"
        else "blocked",
        "captured_row_count": len(captured_rows),
        "captured_rows": captured_rows,
        "blocker_summary": {
            "validation_issue_codes": unique_issues,
            "fixture_quality_failed_code_sha256": fixture_blockers,
            "full_runtime_failed_rows": full_runtime_failed_rows,
        },
        "privacy": {
            "text_mode": "redacted"
            if _mapping(benchmark.get("scoring")).get("text_mode") == "redacted"
            else "[invalid]",
            "raw_transcript_fields": bool(_mapping(benchmark.get("scoring")).get("raw_transcript_fields")) if benchmark else False,
            "redacted_text_fields": _mapping(benchmark.get("scoring")).get("redacted_text_fields") is True if benchmark else False,
            "candidate_raw_text_fields": candidate.get("raw_text_fields") is True if candidate else False,
            "public_receipt_must_not_include_full_text": True,
        },
        "next_action": (
            "promote_captured_candidate_to_fixture_manifest"
            if promotion_allowed
            else "repair_and_regenerate_bound_candidate_or_benchmark_evidence"
        ),
    }


def materialize_diagnostic(
    *,
    output_path: Path = DEFAULT_OUTPUT,
    candidate_receipt_path: Path = DEFAULT_CANDIDATE_RECEIPT,
    benchmark_receipt_path: Path = DEFAULT_BENCHMARK_RECEIPT,
    generated_at: str = "",
) -> dict[str, object]:
    payload = build_diagnostic(
        candidate_receipt_path=candidate_receipt_path,
        benchmark_receipt_path=benchmark_receipt_path,
        generated_at=generated_at,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    rendered = (
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n"
    ).encode("utf-8")
    parent_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        parent_descriptor = os.open(output_path.parent, parent_flags)
    except OSError as exc:
        if output_path.is_symlink() or output_path.parent.is_symlink():
            raise RuntimeError("diagnostic_output_symlink_forbidden") from exc
        raise
    output_name = output_path.name
    temporary_name = f".{output_name}.{secrets.token_hex(12)}.tmp"
    descriptor: int | None = None
    temporary_exists = False
    try:
        try:
            destination_stat = os.stat(
                output_name,
                dir_fd=parent_descriptor,
                follow_symlinks=False,
            )
        except FileNotFoundError:
            destination_stat = None
        if destination_stat is not None and stat.S_ISLNK(destination_stat.st_mode):
            raise RuntimeError("diagnostic_output_symlink_forbidden")
        flags = (
            os.O_WRONLY
            | os.O_CREAT
            | os.O_EXCL
            | getattr(os, "O_NOFOLLOW", 0)
        )
        descriptor = os.open(temporary_name, flags, 0o600, dir_fd=parent_descriptor)
        temporary_exists = True
        os.fchmod(descriptor, 0o644)
        offset = 0
        while offset < len(rendered):
            written = os.write(descriptor, rendered[offset:])
            if written <= 0:
                raise OSError("diagnostic_output_short_write")
            offset += written
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = None
        try:
            destination_stat = os.stat(
                output_name,
                dir_fd=parent_descriptor,
                follow_symlinks=False,
            )
        except FileNotFoundError:
            destination_stat = None
        if destination_stat is not None and stat.S_ISLNK(destination_stat.st_mode):
            raise RuntimeError("diagnostic_output_symlink_forbidden")
        os.replace(
            temporary_name,
            output_name,
            src_dir_fd=parent_descriptor,
            dst_dir_fd=parent_descriptor,
        )
        temporary_exists = False
        os.fsync(parent_descriptor)
    finally:
        if descriptor is not None:
            os.close(descriptor)
        if temporary_exists:
            try:
                os.unlink(temporary_name, dir_fd=parent_descriptor)
            except FileNotFoundError:
                pass
        os.close(parent_descriptor)
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="Materialize a fail-closed redacted diagnostic for a captured STT candidate.")
    parser.add_argument("--candidate-receipt", type=Path, default=DEFAULT_CANDIDATE_RECEIPT)
    parser.add_argument("--benchmark-receipt", type=Path, default=DEFAULT_BENCHMARK_RECEIPT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--generated-at", default="")
    args = parser.parse_args()
    payload = materialize_diagnostic(
        output_path=args.output,
        candidate_receipt_path=args.candidate_receipt,
        benchmark_receipt_path=args.benchmark_receipt,
        generated_at=str(args.generated_at or ""),
    )
    print(
        json.dumps(
            {
                "contract_name": payload["contract_name"],
                "status": payload["status"],
                "promotion_allowed": payload["promotion_allowed"],
                "issue_codes": payload["issues"],
                "input_binding_sha256": payload["input_binding_sha256"],
                "receipt": "[diagnostic_receipt]",
            },
            ensure_ascii=False,
            sort_keys=True,
            allow_nan=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
