#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CANDIDATE_RECEIPT = ROOT / ".codex-studio/published/memorial_stt_fixture_candidate.generated.json"
DEFAULT_BENCHMARK_RECEIPT = ROOT / ".codex-studio/published/memorial_stt_provider_benchmark_captured_candidate.generated.json"
DEFAULT_OUTPUT = ROOT / ".codex-studio/published/memorial_stt_captured_candidate_diagnostic.generated.json"
CONTRACT_NAME = "ea.memorial_stt_captured_candidate_diagnostic"


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _load_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _display_path(path: Path) -> str:
    try:
        return path.relative_to(ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def _file_entry(path: Path) -> dict[str, object]:
    entry: dict[str, object] = {"path": _display_path(path), "exists": path.is_file()}
    if path.is_file():
        entry["bytes"] = path.stat().st_size
        entry["sha256"] = _sha256_file(path)
    return entry


def _float(value: object, default: float = 0.0) -> float:
    try:
        return float(str(value if value is not None else default).strip() or str(default))
    except (TypeError, ValueError):
        return default


def _int(value: object, default: int = 0) -> int:
    try:
        return int(float(str(value if value is not None else default).strip() or str(default)))
    except (TypeError, ValueError):
        return default


def _list(values: object) -> list[str]:
    return [str(item).strip() for item in list(values or []) if str(item).strip()]


def _provider_failure_codes(result: dict[str, object]) -> list[str]:
    if result.get("passed") is True:
        return []
    codes: list[str] = []
    if result.get("fixture_invalid") is True:
        codes.append("fixture_invalid")
    if result.get("usable") is False:
        codes.append("transcript_unusable")
    if result.get("intent_correct") is False:
        codes.append("required_tokens_missing")
    token_f1 = _float(result.get("token_f1"), 0.0)
    min_token_f1 = _float(result.get("min_token_f1"), 0.0)
    if token_f1 < min_token_f1:
        codes.append("token_f1_below_min")
    wer = _float(result.get("wer"), 1.0)
    max_wer = _float(result.get("max_wer"), 1.0)
    if wer > max_wer:
        codes.append("wer_above_max")
    expected_hash = str(result.get("expected_text_sha256") or "").strip()
    actual_hash = str(result.get("actual_text_sha256") or "").strip()
    if expected_hash and actual_hash and expected_hash != actual_hash:
        codes.append("transcript_hash_mismatch")
    status = str(result.get("status") or "").strip()
    if status in {"error", "http_error", "unavailable"}:
        codes.append(f"provider_{status}")
    return list(dict.fromkeys(codes))


def _provider_summary(result: dict[str, object]) -> dict[str, object]:
    return {
        "status": str(result.get("status") or ""),
        "passed": bool(result.get("passed") is True),
        "usable": bool(result.get("usable") is True),
        "intent_correct": bool(result.get("intent_correct") is True),
        "token_f1": _float(result.get("token_f1"), 0.0),
        "min_token_f1": _float(result.get("min_token_f1"), 0.0),
        "wer": _float(result.get("wer"), 1.0),
        "max_wer": _float(result.get("max_wer"), 1.0),
        "ms": _float(result.get("ms"), 0.0),
        "transcriber": str(result.get("transcriber") or ""),
        "expected_text_chars": _int(result.get("expected_text_chars"), 0),
        "actual_text_chars": _int(result.get("actual_text_chars"), 0),
        "expected_text_sha256": str(result.get("expected_text_sha256") or ""),
        "actual_text_sha256": str(result.get("actual_text_sha256") or ""),
        "required_token_count": _int(result.get("required_token_count"), 0),
        "required_token_sha256": _list(result.get("required_token_sha256")),
        "text_mode": str(result.get("text_mode") or ""),
        "text_redacted": bool(result.get("text_redacted") is True),
        "failure_codes": _provider_failure_codes(result),
    }


def _captured_rows(benchmark: dict[str, Any]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for row in list(benchmark.get("rows") or []):
        if not isinstance(row, dict):
            continue
        provenance = dict(row.get("provenance") or {})
        if provenance.get("external_bundle") is not True:
            continue
        fixture_quality = dict(row.get("fixture_quality") or {})
        providers = {
            "full_runtime": _provider_summary(dict(row.get("full_runtime") or {})),
            "onemin_sample": _provider_summary(dict(row.get("onemin_sample") or {})),
            "shadow": _provider_summary(dict(row.get("shadow") or {})),
        }
        full_runtime_failures = {
            str(code)
            for code in list(dict(providers.get("full_runtime") or {}).get("failure_codes") or [])
            if str(code)
        }
        all_provider_failures = sorted(
            {
                str(code)
                for summary in providers.values()
                for code in list(summary.get("failure_codes") or [])
                if str(code)
            }
        )
        row_failures = sorted(
            full_runtime_failures
            | {str(code) for code in list(fixture_quality.get("failed_codes") or []) if str(code)}
        )
        rows.append(
            {
                "sample": str(row.get("sample") or ""),
                "variant": str(row.get("variant") or ""),
                "fixture": str(row.get("fixture") or ""),
                "fixture_sha256": str(row.get("fixture_sha256") or ""),
                "fixture_quality": {
                    "status": str(fixture_quality.get("status") or ""),
                    "failed_codes": _list(fixture_quality.get("failed_codes")),
                    "audio_duration_seconds": _float(fixture_quality.get("audio_duration_seconds"), 0.0),
                    "expected_min_duration_seconds": _float(fixture_quality.get("expected_min_duration_seconds"), 0.0),
                },
                "provenance": {
                    "external_bundle": True,
                    "bundle_root": str(provenance.get("bundle_root") or ""),
                    "bundle_id": str(provenance.get("bundle_id") or ""),
                    "synthetic": bool(provenance.get("synthetic") is True),
                    "speaker_consent": str(provenance.get("speaker_consent") or ""),
                    "allowed_purpose": str(provenance.get("allowed_purpose") or ""),
                    "retention": str(provenance.get("retention") or ""),
                    "accent": str(provenance.get("accent") or ""),
                },
                "providers": providers,
                "row_failure_codes": row_failures,
                "all_provider_failure_codes": all_provider_failures,
            }
        )
    return rows


def _candidate_summary(candidate: dict[str, Any]) -> dict[str, object]:
    entry = dict(candidate.get("candidate_manifest_entry") or {})
    expected_text = dict(entry.get("expected_text") or {})
    promotion_gate = dict(candidate.get("promotion_gate") or {})
    audio = dict(candidate.get("audio") or {})
    return {
        "status": str(candidate.get("status") or ""),
        "candidate_scope": str(candidate.get("candidate_scope") or ""),
        "failed_codes": _list(candidate.get("failed_codes")),
        "bundle_id": str(dict(candidate.get("bundle") or {}).get("id") or ""),
        "audio_sha256": str(audio.get("sha256") or ""),
        "audio_bytes": _int(audio.get("bytes"), 0),
        "audio_duration_seconds": _float(audio.get("duration_seconds"), 0.0),
        "expected_min_duration_seconds": _float(audio.get("expected_min_duration_seconds"), 0.0),
        "sample": str(entry.get("sample") or ""),
        "fixture_file": str(entry.get("file") or ""),
        "expected_text_chars": _int(expected_text.get("text_chars"), 0),
        "expected_text_sha256": str(expected_text.get("text_sha256") or ""),
        "required_token_sha256": [
            str(dict(token).get("text_sha256") or "")
            for token in list(entry.get("required_tokens") or [])
            if isinstance(token, dict)
        ],
        "raw_text_fields": bool(candidate.get("raw_text_fields")),
        "promotion_gate": {
            "status": str(promotion_gate.get("status") or ""),
            "required_receipt": str(promotion_gate.get("required_receipt") or ""),
            "may_update_fixture_manifest": bool(promotion_gate.get("may_update_fixture_manifest") is True),
            "next_action": str(promotion_gate.get("next_action") or ""),
        },
    }


def build_diagnostic(
    *,
    candidate_receipt_path: Path = DEFAULT_CANDIDATE_RECEIPT,
    benchmark_receipt_path: Path = DEFAULT_BENCHMARK_RECEIPT,
    generated_at: str = "",
) -> dict[str, object]:
    candidate = _load_json(candidate_receipt_path)
    benchmark = _load_json(benchmark_receipt_path)
    issues: list[str] = []
    if not candidate:
        issues.append("candidate_receipt_missing_or_invalid")
    if not benchmark:
        issues.append("captured_benchmark_receipt_missing_or_invalid")
    captured_rows = _captured_rows(benchmark) if benchmark else []
    if benchmark and not captured_rows:
        issues.append("captured_candidate_rows_missing")
    fixture_blockers = sorted(
        {
            str(code)
            for row in captured_rows
            for code in list(dict(row.get("fixture_quality") or {}).get("failed_codes") or [])
            if str(code)
        }
    )
    full_runtime_failures = [
        row
        for row in captured_rows
        if dict(dict(row.get("providers") or {}).get("full_runtime") or {}).get("passed") is not True
    ]
    row_failure_codes = sorted(
        {
            str(code)
            for row in captured_rows
            for code in list(row.get("row_failure_codes") or [])
            if str(code)
        }
    )
    promotion_allowed = bool(captured_rows) and not fixture_blockers and not full_runtime_failures and not issues
    if full_runtime_failures:
        issues.append("captured_candidate_full_runtime_failed")
    if fixture_blockers:
        issues.append("captured_candidate_fixture_quality_blocked")
    next_action = "promote_captured_candidate_to_fixture_manifest"
    if not candidate:
        next_action = "materialize_memorial_stt_fixture_candidate"
    elif not benchmark:
        next_action = "run_captured_candidate_benchmark_before_fixture_manifest"
    elif fixture_blockers:
        next_action = "replace_capture_with_plausible_wav_or_shorter_ground_truth"
    elif full_runtime_failures and any("transcript_hash_mismatch" in list(row.get("row_failure_codes") or []) for row in captured_rows):
        next_action = "rerun_operator_local_full_text_benchmark_or_correct_ground_truth_transcript"
    elif full_runtime_failures:
        next_action = "inspect_captured_candidate_provider_failure"
    return {
        "contract_name": CONTRACT_NAME,
        "generated_at": generated_at or _utc_now(),
        "status": "pass" if promotion_allowed else "blocked",
        "diagnostic_status": "ready" if candidate and benchmark else "incomplete",
        "promotion_allowed": promotion_allowed,
        "may_update_fixture_manifest": promotion_allowed,
        "issues": sorted(set(issues)),
        "candidate_receipt": _file_entry(candidate_receipt_path),
        "benchmark_receipt": _file_entry(benchmark_receipt_path),
        "candidate": _candidate_summary(candidate) if candidate else {},
        "benchmark_status": str(benchmark.get("status") or "") if benchmark else "",
        "benchmark_fixture_quality_status": str(benchmark.get("fixture_quality_status") or "") if benchmark else "",
        "captured_row_count": len(captured_rows),
        "captured_rows": captured_rows,
        "blocker_summary": {
            "fixture_quality_failed_codes": fixture_blockers,
            "row_failure_codes": row_failure_codes,
            "full_runtime_failed_rows": [
                {
                    "sample": str(row.get("sample") or ""),
                    "variant": str(row.get("variant") or ""),
                    "failure_codes": list(row.get("row_failure_codes") or []),
                    "token_f1": dict(dict(row.get("providers") or {}).get("full_runtime") or {}).get("token_f1"),
                    "wer": dict(dict(row.get("providers") or {}).get("full_runtime") or {}).get("wer"),
                }
                for row in full_runtime_failures
            ],
        },
        "privacy": {
            "text_mode": str(dict(benchmark.get("scoring") or {}).get("text_mode") or "") if benchmark else "",
            "raw_transcript_fields": bool(dict(benchmark.get("scoring") or {}).get("raw_transcript_fields")) if benchmark else False,
            "redacted_text_fields": bool(dict(benchmark.get("scoring") or {}).get("redacted_text_fields")) if benchmark else False,
            "candidate_raw_text_fields": bool(candidate.get("raw_text_fields")) if candidate else False,
            "public_receipt_must_not_include_full_text": True,
        },
        "operator_full_text_debug": {
            "allowed_only_operator_local": True,
            "must_not_commit_full_text_receipt": True,
            "env": "EA_MEMORIAL_STT_BENCHMARK_TEXT_MODE=full",
            "reason": "Full text is useful only to compare operator ground truth with provider transcript when redacted hashes mismatch.",
        },
        "next_action": next_action,
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
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="Materialize a redacted diagnostic for the Manfred captured STT candidate.")
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
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
