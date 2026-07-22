#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

try:
    from scripts import materialize_memorial_stt_captured_candidate_diagnostic as diagnostic
except ImportError as exc:  # pragma: no cover - script execution path
    if exc.name not in {
        "scripts",
        "scripts.materialize_memorial_stt_captured_candidate_diagnostic",
    }:
        raise
    import materialize_memorial_stt_captured_candidate_diagnostic as diagnostic


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RECEIPT = ROOT / ".codex-studio/published/memorial_stt_captured_candidate_diagnostic.generated.json"
DEFAULT_CANDIDATE_RECEIPT = diagnostic.DEFAULT_CANDIDATE_RECEIPT
DEFAULT_BENCHMARK_RECEIPT = diagnostic.DEFAULT_BENCHMARK_RECEIPT
CONTRACT_NAME = diagnostic.CONTRACT_NAME
CONTRACT_VERSION = diagnostic.CONTRACT_VERSION
GENERATED_BY = diagnostic.GENERATED_BY
VERIFIER_CONTRACT_NAME = "ea.memorial_stt_captured_candidate_diagnostic_verifier"
SENSITIVE_MARKERS = (
    "authorization:",
    "bearer ",
    "api_key",
    "password",
    "token=",
)


def _mapping(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _walk_strings(value: object) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        found: list[str] = []
        for child in value.values():
            found.extend(_walk_strings(child))
        return found
    if isinstance(value, list):
        found: list[str] = []
        for child in value:
            found.extend(_walk_strings(child))
        return found
    return []


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _receipt_timestamp_issues(receipt: dict[str, Any], *, observed_at: str) -> list[str]:
    issues: list[str] = []
    observed = diagnostic._parse_timestamp(observed_at)  # noqa: SLF001
    generated = diagnostic._parse_timestamp(receipt.get("generated_at"))  # noqa: SLF001
    if observed is None:
        observed = datetime.now(UTC)
    if generated is None:
        return ["diagnostic_generated_at_invalid_or_timezone_missing"]
    if generated > observed + timedelta(seconds=diagnostic.MAX_FUTURE_SKEW_SECONDS):
        issues.append("diagnostic_generated_at_future")
    if observed - generated > timedelta(seconds=diagnostic.MAX_EVIDENCE_AGE_SECONDS):
        issues.append("diagnostic_generated_at_stale")
    return issues


def _semantic_equal(left: object, right: object) -> bool:
    try:
        return diagnostic._canonical_json(left) == diagnostic._canonical_json(right)  # noqa: SLF001
    except (TypeError, ValueError):
        return False


def verify_diagnostic(
    receipt_path: Path = DEFAULT_RECEIPT,
    *,
    candidate_receipt_path: Path = DEFAULT_CANDIDATE_RECEIPT,
    benchmark_receipt_path: Path = DEFAULT_BENCHMARK_RECEIPT,
) -> dict[str, object]:
    issues: list[str] = []
    receipt, _receipt_entry = diagnostic._load_json_with_entry(receipt_path)  # noqa: SLF001
    observed = _utc_now()
    if not receipt:
        issues.append("diagnostic_receipt_missing_or_invalid")
    else:
        if receipt.get("contract_name") != CONTRACT_NAME:
            issues.append("diagnostic_contract_mismatch")
        if receipt.get("contract_version") != CONTRACT_VERSION:
            issues.append("diagnostic_contract_version_mismatch")
        if receipt.get("generated_by") != GENERATED_BY:
            issues.append("diagnostic_generated_by_mismatch")
        issues.extend(_receipt_timestamp_issues(receipt, observed_at=observed))

        current_head = diagnostic.resolve_source_state_head(ROOT)
        current_fingerprint = diagnostic.resolve_source_worktree_fingerprint(ROOT)
        if receipt.get("head_semantics") != diagnostic.HEAD_SEMANTICS:
            issues.append("diagnostic_head_semantics_mismatch")
        if receipt.get("source_git_head") != current_head:
            issues.append("diagnostic_source_git_head_not_current")
        if receipt.get("source_state_fingerprint_semantics") != diagnostic.FINGERPRINT_SEMANTICS:
            issues.append("diagnostic_source_state_fingerprint_semantics_mismatch")
        if receipt.get("source_state_fingerprint") != current_fingerprint:
            issues.append("diagnostic_source_state_fingerprint_not_current")

        privacy = _mapping(receipt.get("privacy"))
        if privacy.get("raw_transcript_fields") is not False:
            issues.append("diagnostic_raw_transcript_fields_exposed")
        if privacy.get("candidate_raw_text_fields") is not False:
            issues.append("diagnostic_candidate_raw_text_fields_exposed")
        if privacy.get("public_receipt_must_not_include_full_text") is not True:
            issues.append("diagnostic_full_text_public_guard_missing")
        if diagnostic._raw_text_exposed(receipt):  # noqa: SLF001
            issues.append("diagnostic_raw_text_exposed")
        for value in _walk_strings(receipt):
            lowered = value.strip().lower()
            if any(marker in lowered for marker in SENSITIVE_MARKERS):
                issues.append("diagnostic_sensitive_or_raw_text_exposed")
                break

        generated_at = str(receipt.get("generated_at") or "")
        try:
            expected = diagnostic.build_diagnostic(
                candidate_receipt_path=candidate_receipt_path,
                benchmark_receipt_path=benchmark_receipt_path,
                generated_at=generated_at,
            )
        except ValueError:
            expected = {}
            issues.append("diagnostic_semantic_rebuild_failed")
        input_binding = _mapping(receipt.get("input_binding"))
        expected_input_binding = _mapping(expected.get("input_binding"))
        if input_binding.get("contract_name") != diagnostic.INPUT_BINDING_CONTRACT_NAME:
            issues.append("diagnostic_input_binding_contract_mismatch")
        if input_binding.get("canonicalization") != diagnostic.CANONICALIZATION:
            issues.append("diagnostic_input_binding_canonicalization_mismatch")
        if not _semantic_equal(input_binding.get("payload"), expected_input_binding.get("payload")):
            issues.append("diagnostic_input_binding_payload_mismatch")
        if input_binding.get("sha256") != expected_input_binding.get("sha256"):
            issues.append("diagnostic_input_binding_sha256_mismatch")
        if receipt.get("input_binding_sha256") != expected.get("input_binding_sha256"):
            issues.append("diagnostic_top_level_input_binding_sha256_mismatch")

        if receipt.get("candidate_receipt") != expected.get("candidate_receipt"):
            issues.append("diagnostic_candidate_source_entry_mismatch")
        if receipt.get("benchmark_receipt") != expected.get("benchmark_receipt"):
            issues.append("diagnostic_benchmark_source_entry_mismatch")
        if (
            receipt.get("promotion_allowed") != expected.get("promotion_allowed")
            or receipt.get("may_update_fixture_manifest") != expected.get("may_update_fixture_manifest")
            or receipt.get("status") != expected.get("status")
        ):
            issues.append("diagnostic_promotion_overclaim_or_status_mismatch")
        if not _semantic_equal(receipt, expected):
            issues.append("diagnostic_semantic_payload_mismatch")

    unique_issues = sorted(set(issues))
    return {
        "contract_name": VERIFIER_CONTRACT_NAME,
        "status": "pass" if not unique_issues else "fail",
        "issues": unique_issues,
        "receipt": "[diagnostic_receipt]",
        "candidate_receipt": "[candidate_receipt]",
        "benchmark_receipt": "[benchmark_receipt]",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify a diagnostic against explicit current candidate and benchmark sources.")
    parser.add_argument("--receipt", type=Path, default=DEFAULT_RECEIPT)
    parser.add_argument("--candidate-receipt", type=Path, default=DEFAULT_CANDIDATE_RECEIPT)
    parser.add_argument("--benchmark-receipt", type=Path, default=DEFAULT_BENCHMARK_RECEIPT)
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args()
    payload = verify_diagnostic(
        args.receipt,
        candidate_receipt_path=args.candidate_receipt,
        benchmark_receipt_path=args.benchmark_receipt,
    )
    print(json.dumps(payload, indent=2 if args.pretty else None, sort_keys=True))
    return 0 if payload["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
