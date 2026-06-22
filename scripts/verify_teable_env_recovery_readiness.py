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
DEFAULT_RECEIPT = ROOT / ".codex-studio/published/teable_env_recovery_readiness.generated.json"
EXPECTED_CHECK_KEYS = {
    "makefile": {
        "env_check_teable_target",
        "env_fresh_host_teable_target",
        "env_probe_teable_target",
        "verify_env_teable_recovery_target",
    },
    "readme": {
        "fresh_host_doc",
        "probe_doc",
        "check_doc",
        "drill_doc",
        "local_status_doc",
    },
    "bootstrap_script": {
        "fresh_host_help",
        "probe_help",
        "check_help",
        "drill_help",
        "ensure_local_help",
        "seeded_key_required_fresh_host",
        "seeded_key_required_probe",
    },
    "sync_script": {
        "recover_command",
        "drill_command",
        "check_command",
        "verify_command",
        "local_status_command",
        "ensure_local_command",
        "seeded_api_key_flag",
        "recovery_proof_contract",
    },
}
EXPECTED_COMMANDS = {
    "make verify-teable-env-recovery-readiness",
    "make verify-env-teable-recovery",
    "make env-check-teable",
    "make env-probe-teable",
    "make env-fresh-host-teable",
}
EXPECTED_RULES = {
    "This receipt proves local command and documentation readiness only; it does not prove a fresh-host recovery drill happened.",
    "Do not claim Teable recovery pass from this receipt alone.",
    "A seeded fresh-host probe or drill receipt must be mirrored separately before the recover lens can claim pass.",
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
        return [f"teable env recovery readiness missing or invalid: {path}"]

    if receipt.get("contract_name") != "ea.teable_env_recovery_readiness.v1":
        issues.append("contract_name must be ea.teable_env_recovery_readiness.v1")
    if receipt.get("generated_by") != "scripts/materialize_teable_env_recovery_readiness.py":
        issues.append("generated_by must point at the teable env recovery readiness materializer")
    current_head = _git_head(root)
    if current_head and str(receipt.get("source_git_head") or "").strip() != current_head:
        issues.append("receipt is stale relative to current source HEAD")

    status = str(receipt.get("status") or "").strip()
    if status not in {"ready_local_audit", "blocked"}:
        issues.append("status must stay ready_local_audit or blocked")

    command_surface_ready = bool(receipt.get("command_surface_ready"))
    if status == "ready_local_audit" and not command_surface_ready:
        issues.append("ready_local_audit requires command_surface_ready=true")
    if status == "blocked" and command_surface_ready:
        issues.append("blocked status must not claim command_surface_ready=true")

    if receipt.get("fresh_host_drill_receipt_mirrored") is not False:
        issues.append("fresh_host_drill_receipt_mirrored must remain false until a real drill receipt is mirrored")
    if receipt.get("claim_limit") != "local_command_contract_readiness_not_fresh_host_drill":
        issues.append("claim_limit drifted away from the conservative recovery wording")

    commands = set(str(item).strip() for item in list(receipt.get("verifier_commands") or []) if str(item).strip())
    if commands != EXPECTED_COMMANDS:
        issues.append("verifier_commands drifted")

    next_receipts = set(str(item).strip() for item in list(receipt.get("required_next_receipts") or []) if str(item).strip())
    if next_receipts != {"fresh_host_teable_recovery_drill_receipt"}:
        issues.append("required_next_receipts must keep the fresh-host drill receipt pending")

    rules = set(str(item).strip() for item in list(receipt.get("rules") or []) if str(item).strip())
    if rules != EXPECTED_RULES:
        issues.append("rules drifted")

    check_groups = dict(receipt.get("checks") or {})
    for group, keys in EXPECTED_CHECK_KEYS.items():
        values = dict(check_groups.get(group) or {})
        if set(values) != keys:
            issues.append(f"{group} checks drifted")
            continue
        if status == "ready_local_audit" and not all(bool(values[key]) for key in keys):
            issues.append(f"{group} must pass for ready_local_audit")

    recorded_issues = [str(item).strip() for item in list(receipt.get("issues") or []) if str(item).strip()]
    if status == "ready_local_audit" and recorded_issues:
        issues.append("ready_local_audit must not carry issues")
    if status == "blocked" and not recorded_issues:
        issues.append("blocked receipt must list issues")

    return issues


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify the Teable env recovery readiness receipt.")
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
