#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RECEIPT = ROOT / ".codex-studio/published/memorial_stt_captured_candidate_diagnostic.generated.json"
CONTRACT_NAME = "ea.memorial_stt_captured_candidate_diagnostic"
VERIFIER_CONTRACT_NAME = "ea.memorial_stt_captured_candidate_diagnostic_verifier"
SENSITIVE_MARKERS = (
    "authorization:",
    "bearer ",
    "api_key",
    "password",
    "token=",
    "komnt",
    "kommt",
    "manfred",
    "sprechen",
    "stumm",
)


def _load_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


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


def _provider_passed(row: dict[str, Any], provider: str) -> bool:
    return dict(dict(row.get("providers") or {}).get(provider) or {}).get("passed") is True


def verify_diagnostic(receipt_path: Path = DEFAULT_RECEIPT) -> dict[str, object]:
    issues: list[str] = []
    receipt = _load_json(receipt_path)
    if not receipt:
        issues.append("diagnostic_receipt_missing_or_invalid")
    else:
        if receipt.get("contract_name") != CONTRACT_NAME:
            issues.append("diagnostic_contract_mismatch")
        if str(receipt.get("diagnostic_status") or "") not in {"ready", "incomplete"}:
            issues.append("diagnostic_status_invalid")
        status = str(receipt.get("status") or "")
        if status not in {"pass", "blocked"}:
            issues.append("diagnostic_status_not_pass_or_blocked")
        privacy = dict(receipt.get("privacy") or {})
        if privacy.get("raw_transcript_fields") is not False:
            issues.append("diagnostic_raw_transcript_fields_exposed")
        if privacy.get("candidate_raw_text_fields") is not False:
            issues.append("diagnostic_candidate_raw_text_fields_exposed")
        if privacy.get("public_receipt_must_not_include_full_text") is not True:
            issues.append("diagnostic_full_text_public_guard_missing")
        captured_rows = [dict(row) for row in list(receipt.get("captured_rows") or []) if isinstance(row, dict)]
        promotion_allowed = bool(receipt.get("promotion_allowed"))
        may_update = bool(receipt.get("may_update_fixture_manifest"))
        all_full_runtime_passed = bool(captured_rows) and all(_provider_passed(row, "full_runtime") for row in captured_rows)
        if promotion_allowed != may_update:
            issues.append("diagnostic_promotion_update_flag_mismatch")
        if promotion_allowed and (status != "pass" or not all_full_runtime_passed):
            issues.append("diagnostic_promotion_overclaim")
        if not promotion_allowed:
            if status != "blocked":
                issues.append("diagnostic_blocked_status_required")
            blocker_summary = dict(receipt.get("blocker_summary") or {})
            row_failures = list(blocker_summary.get("row_failure_codes") or [])
            full_runtime_failed = list(blocker_summary.get("full_runtime_failed_rows") or [])
            fixture_failures = list(blocker_summary.get("fixture_quality_failed_codes") or [])
            if not (row_failures or full_runtime_failed or fixture_failures or list(receipt.get("issues") or [])):
                issues.append("diagnostic_blocker_summary_missing")
        if captured_rows:
            for row in captured_rows:
                provenance = dict(row.get("provenance") or {})
                if provenance.get("external_bundle") is not True:
                    issues.append("diagnostic_captured_row_not_external_bundle")
                providers = dict(row.get("providers") or {})
                full_runtime = dict(providers.get("full_runtime") or {})
                if not full_runtime:
                    issues.append("diagnostic_full_runtime_summary_missing")
                if full_runtime.get("text_redacted") is not True:
                    issues.append("diagnostic_full_runtime_text_not_redacted")
        for value in _walk_strings(receipt):
            lowered = value.strip().lower()
            if any(marker in lowered for marker in SENSITIVE_MARKERS):
                issues.append("diagnostic_sensitive_or_raw_text_exposed")
                break
    return {
        "contract_name": VERIFIER_CONTRACT_NAME,
        "status": "pass" if not issues else "fail",
        "issues": issues,
        "receipt": receipt_path.as_posix(),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify the redacted Manfred captured STT candidate diagnostic.")
    parser.add_argument("--receipt", type=Path, default=DEFAULT_RECEIPT)
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args()
    payload = verify_diagnostic(args.receipt)
    print(json.dumps(payload, indent=2 if args.pretty else None, sort_keys=True))
    return 0 if payload["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
