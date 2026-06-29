#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

try:
    from scripts.source_state_head import resolve_source_state_head
except ModuleNotFoundError:  # pragma: no cover - script execution path
    from source_state_head import resolve_source_state_head


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RECEIPT = ROOT / ".codex-studio/published/teable_env_recovery_proof.generated.json"
EXPECTED_SCOPES = {"ea_root", "ea_root_local", "ea_service"}
EXPECTED_PRIVACY = {
    "raw_paths_exposed": False,
    "raw_table_id_exposed": False,
    "raw_api_key_exposed": False,
    "secret_values_exposed": False,
}


def _json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return dict(payload) if isinstance(payload, dict) else {}


def _git_head(path: Path = ROOT) -> str:
    return resolve_source_state_head(path)


def verify(path: Path = DEFAULT_RECEIPT, *, root: Path = ROOT) -> list[str]:
    issues: list[str] = []
    receipt = _json(path)
    if not receipt:
        return [f"teable env recovery proof missing or invalid: {path}"]

    if receipt.get("contract_name") != "ea.teable_env_recovery_proof.v1":
        issues.append("contract_name must be ea.teable_env_recovery_proof.v1")
    if receipt.get("generated_by") != "scripts/materialize_teable_env_recovery_proof.py":
        issues.append("generated_by must point at the recovery proof materializer")
    current_head = _git_head(root)
    if current_head and str(receipt.get("source_git_head") or "").strip() != current_head:
        issues.append("receipt is stale relative to current source HEAD")
    if receipt.get("status") != "pass":
        issues.append("status must be pass")
    if receipt.get("recovery_status") != "recovered":
        issues.append("recovery_status must be recovered")
    if receipt.get("fresh_host_api_key_source") != "process_env":
        issues.append("fresh_host_api_key_source must stay process_env")
    if receipt.get("secret_values_redacted") is not True:
        issues.append("secret_values_redacted must be true")
    if receipt.get("drill_output_removed") is not True:
        issues.append("drill_output_removed must be true")

    privacy = dict(receipt.get("privacy") or {})
    for key, value in EXPECTED_PRIVACY.items():
        if privacy.get(key) is not value:
            issues.append(f"privacy field drifted: {key}")

    env_files = list(receipt.get("env_files") or [])
    scopes = {str(row.get("scope") or "").strip() for row in env_files if isinstance(row, dict)}
    if scopes != EXPECTED_SCOPES:
        issues.append("env_files must include exactly ea_root, ea_root_local, and ea_service")
    for row in env_files:
        if not isinstance(row, dict):
            issues.append("env_files entries must be objects")
            continue
        if row.get("path_recorded") is not True:
            issues.append(f"env_files path_recorded must be true for {row.get('scope')}")
        if not str(row.get("path_sha256") or "").strip():
            issues.append(f"env_files path_sha256 missing for {row.get('scope')}")
        if str(row.get("mode") or "").strip() != "0o600":
            issues.append(f"env_files mode must stay 0o600 for {row.get('scope')}")
        restored = int(row.get("restored") or 0)
        verified = int(row.get("hash_verified") or 0)
        mismatches = int(row.get("hash_mismatch_count") or 0)
        if restored <= 0:
            issues.append(f"env_files restored count must be positive for {row.get('scope')}")
        if verified != restored:
            issues.append(f"env_files hash_verified must equal restored for {row.get('scope')}")
        if mismatches != 0:
            issues.append(f"env_files hash_mismatch_count must be zero for {row.get('scope')}")

    referenced = dict(receipt.get("referenced_files") or {})
    if int(referenced.get("hash_mismatch_count") or 0) != 0:
        issues.append("referenced_files hash_mismatch_count must be zero")
    if int(referenced.get("hash_verified") or 0) != int(referenced.get("restored") or 0):
        issues.append("referenced_files hash_verified must equal restored")
    if int(referenced.get("path_count") or 0) < int(referenced.get("restored") or 0):
        issues.append("referenced_files path_count must cover restored files")
    path_hashes = [str(item).strip() for item in list(referenced.get("path_sha256") or []) if str(item).strip()]
    if int(referenced.get("path_count") or 0) and not path_hashes:
        issues.append("referenced_files path_sha256 missing despite restored paths")
    for row in list(referenced.get("modes") or []):
        if not isinstance(row, dict):
            issues.append("referenced_files mode entries must be objects")
            continue
        if not str(row.get("path_sha256") or "").strip():
            issues.append("referenced_files mode entry missing path_sha256")
        if str(row.get("mode") or "").strip() != "0o600":
            issues.append("referenced_files mode entries must stay 0o600")

    verification = dict(receipt.get("verification") or {})
    if verification.get("status") != "pass":
        issues.append("verification.status must be pass")
    for key in (
        "missing_count",
        "different_hash_count",
        "missing_secret_value_count",
        "extra_restorable_count",
    ):
        if int(verification.get(key) or 0) != 0:
            issues.append(f"verification {key} must be zero")
    if int(verification.get("expected_rows") or 0) <= 0:
        issues.append("verification expected_rows must be positive")
    if int(verification.get("same_hash") or 0) != int(verification.get("expected_rows") or 0):
        issues.append("verification same_hash must equal expected_rows")

    return issues


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify the sanitized Teable env recovery proof receipt.")
    parser.add_argument("--receipt", type=Path, default=DEFAULT_RECEIPT)
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args()
    issues = verify(args.receipt)
    payload = {"status": "pass" if not issues else "blocked", "issues": issues}
    if args.pretty:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(json.dumps(payload))
    return 0 if not issues else 1


if __name__ == "__main__":
    raise SystemExit(main())
