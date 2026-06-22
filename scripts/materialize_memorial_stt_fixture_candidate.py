#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
import sys
import wave
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MAX_AUDIO_BYTES = 25 * 1024 * 1024
DEFAULT_MAX_AUDIO_DURATION_SECONDS = 120.0


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
    return value if value > 0 else DEFAULT_MAX_AUDIO_DURATION_SECONDS


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _sha256_text(value: str) -> str:
    return hashlib.sha256(str(value or "").encode("utf-8")).hexdigest()


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
    effective_max_duration_seconds = float(max_duration_seconds or _default_max_audio_duration_seconds())
    failures: list[str] = []
    if payload and (len(payload) < 12 or payload[:4] != b"RIFF" or payload[8:12] != b"WAVE"):
        failures.append("audio_not_wav")
    if duration_seconds <= 0:
        failures.append("audio_duration_missing")
    if min_duration_seconds and duration_seconds < min_duration_seconds:
        failures.append("audio_too_short_for_expected_text")
    if duration_seconds > effective_max_duration_seconds:
        failures.append("audio_duration_implausible")
    return {
        "status": "pass" if not failures else "blocked",
        "failed_codes": failures,
        "audio_duration_seconds": duration_seconds,
        "expected_min_duration_seconds": min_duration_seconds,
        "max_duration_seconds": effective_max_duration_seconds,
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


def _load_input_wav(input_path: Path, *, max_audio_bytes: int) -> tuple[bytes, list[str]]:
    if not input_path.is_file():
        return b"", ["input_wav_missing"]
    try:
        byte_count = int(input_path.stat().st_size)
    except OSError:
        return b"", ["input_wav_stat_failed"]
    if byte_count > max_audio_bytes:
        return b"", ["input_wav_too_large"]
    try:
        return input_path.read_bytes(), []
    except OSError:
        return b"", ["input_wav_read_failed"]


def _text_payload(text: str, *, text_mode: str) -> dict[str, object]:
    normalized = " ".join(str(text or "").split()).strip()
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
    sample: str,
    expected_text: str,
    required_tokens: list[str],
    speaker_consent: str,
    origin: str,
    allowed_purpose: str,
    retention: str,
    accent: str,
    fixture_file: str,
    text_mode: str = "redacted",
    allow_external_root: bool = False,
    bundle_root: Path | None = None,
    max_audio_bytes: int | None = None,
    max_audio_duration_seconds: float | None = None,
) -> dict[str, object]:
    bundle_dir = bundle_dir.expanduser()
    resolved_bundle_root = (bundle_root or _default_bundle_root()).expanduser()
    text_mode = "full" if str(text_mode or "").strip().lower() == "full" else "redacted"
    failures: list[str] = []
    if not sample.strip():
        failures.append("sample_missing")
    if not expected_text.strip():
        failures.append("expected_text_missing")
    if not required_tokens:
        failures.append("required_tokens_missing")
    if not speaker_consent.strip():
        failures.append("speaker_consent_missing")
    if not allow_external_root and not _is_relative_to(bundle_dir, resolved_bundle_root):
        failures.append("bundle_not_under_memorial_stt_error_root")
    input_path = bundle_dir / "input.wav"
    effective_max_audio_bytes = int(max_audio_bytes or _default_max_audio_bytes())
    payload, input_failures = _load_input_wav(input_path, max_audio_bytes=effective_max_audio_bytes)
    failures.extend(input_failures)
    effective_max_audio_duration_seconds = float(max_audio_duration_seconds or _default_max_audio_duration_seconds())
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
    }
    failures.extend(str(item) for item in list(quality.get("failed_codes") or []) if str(item))
    required_token_payloads = [
        _text_payload(token, text_mode=text_mode)
        for token in required_tokens
        if str(token or "").strip()
    ]
    metadata = _load_error_metadata(bundle_dir)
    status = "pass" if not failures else "blocked"
    promotion_gate = {
        "status": "pending_captured_candidate_benchmark" if status == "pass" else "blocked",
        "required_receipt": ".codex-studio/published/memorial_stt_provider_benchmark_captured_candidate.generated.json",
        "required_rule": "captured candidate must pass full-runtime STT scoring against operator-confirmed ground truth before fixture-manifest promotion",
        "may_update_fixture_manifest": False,
        "next_action": "run_captured_candidate_benchmark_before_fixture_manifest"
        if status == "pass"
        else "fix_candidate_failed_codes_before_benchmark",
    }
    return {
        "contract_name": "ea.memorial_stt_fixture_candidate",
        "status": status,
        "failed_codes": sorted(set(failures)),
        "candidate_scope": "audio_quality_and_provenance_only",
        "promotion_gate": promotion_gate,
        "bundle": {
            "root": "[memorial_stt_error_root]" if _is_relative_to(bundle_dir, resolved_bundle_root) else "[external_root]",
            "id": bundle_dir.name,
            "has_error_json": bool(metadata),
            "event_type": str(metadata.get("event_type") or metadata.get("issue_type") or ""),
            "reason": str(metadata.get("reason") or metadata.get("classification") or ""),
        },
        "audio": {
            "input_file": "input.wav",
            "sha256": _sha256_bytes(payload) if payload else "",
            "bytes": len(payload),
            "max_bytes": effective_max_audio_bytes,
            "duration_seconds": quality.get("audio_duration_seconds"),
            "expected_min_duration_seconds": quality.get("expected_min_duration_seconds"),
            "max_duration_seconds": quality.get("max_duration_seconds"),
        },
        "fixture_quality": quality,
        "candidate_manifest_entry": {
            "sample": sample.strip(),
            "file": fixture_file.strip() or f"{sample.strip()}_captured.wav",
            "origin": origin.strip(),
            "speaker_consent": speaker_consent.strip(),
            "allowed_purpose": allowed_purpose.strip(),
            "retention": retention.strip(),
            "synthetic": False,
            "language": "de",
            "accent": accent.strip(),
            "expected_text": _text_payload(expected_text, text_mode=text_mode),
            "required_tokens": required_token_payloads,
            "sha256": _sha256_bytes(payload) if payload else "",
        },
        "text_mode": text_mode,
        "raw_text_fields": text_mode == "full",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Materialize a governed candidate from a private memorial STT error bundle.")
    parser.add_argument("--bundle-dir", required=True, type=Path)
    parser.add_argument("--sample", required=True)
    parser.add_argument("--expected-text", required=True)
    parser.add_argument("--required-token", action="append", default=[])
    parser.add_argument("--speaker-consent", required=True)
    parser.add_argument(
        "--origin",
        default="Captured Manfred memorial STT error bundle with operator-supplied ground-truth transcript.",
    )
    parser.add_argument("--allowed-purpose", default="memorial_stt_regression_and_provider_bakeoff")
    parser.add_argument("--retention", default="private_repo_captured_regression_fixture")
    parser.add_argument("--accent", default="Austrian German")
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
        sample=str(args.sample),
        expected_text=str(args.expected_text),
        required_tokens=[str(item) for item in list(args.required_token or [])],
        speaker_consent=str(args.speaker_consent),
        origin=str(args.origin),
        allowed_purpose=str(args.allowed_purpose),
        retention=str(args.retention),
        accent=str(args.accent),
        fixture_file=str(args.fixture_file),
        text_mode=str(args.text_mode),
        allow_external_root=bool(args.allow_external_root),
        bundle_root=args.bundle_root,
        max_audio_bytes=args.max_audio_bytes,
        max_audio_duration_seconds=args.max_audio_seconds,
    )
    output = args.output or _default_output()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload.get("status") == "pass" else 2


if __name__ == "__main__":
    raise SystemExit(main())
