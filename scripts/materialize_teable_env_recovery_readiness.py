#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

try:
    from scripts.source_state_head import resolve_source_state_head
except ModuleNotFoundError:  # pragma: no cover - script execution path
    from source_state_head import resolve_source_state_head


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / ".codex-studio/published/teable_env_recovery_readiness.generated.json"
MAKEFILE = ROOT / "Makefile"
README = ROOT / "README.md"
BOOTSTRAP_SCRIPT = ROOT / "scripts/bootstrap_from_teable.sh"
SYNC_SCRIPT = ROOT / "scripts/sync_env_to_teable.py"

MAKEFILE_SNIPPETS = {
    "env_check_teable_target": "env-check-teable:\n\t$(PYTHON_BIN) scripts/sync_env_to_teable.py check",
    "env_fresh_host_teable_target": "env-fresh-host-teable:\n\t@scripts/bootstrap_from_teable.sh --fresh-host",
    "env_probe_teable_target": "env-probe-teable:\n\t@scripts/bootstrap_from_teable.sh --probe",
    "verify_env_teable_recovery_target": "verify-env-teable-recovery:\n\t$(PYTHON_BIN) scripts/sync_env_to_teable.py verify",
}

README_SNIPPETS = {
    "fresh_host_doc": "make env-fresh-host-teable",
    "probe_doc": "make env-probe-teable",
    "check_doc": "make env-check-teable",
    "drill_doc": "make env-drill-teable",
    "local_status_doc": "make env-local-status-teable",
}

BOOTSTRAP_SNIPPETS = {
    "fresh_host_help": "scripts/bootstrap_from_teable.sh --fresh-host",
    "probe_help": "scripts/bootstrap_from_teable.sh --probe",
    "check_help": "scripts/bootstrap_from_teable.sh --check",
    "drill_help": "scripts/bootstrap_from_teable.sh --drill",
    "ensure_local_help": "scripts/bootstrap_from_teable.sh --ensure-local",
    "seeded_key_required_fresh_host": "TEABLE_API_KEY must be seeded in the shell for fresh-host recovery.",
    "seeded_key_required_probe": "TEABLE_API_KEY must be seeded in the shell for fresh-host probe recovery.",
}

SYNC_SNIPPETS = {
    "recover_command": '"recover",',
    "drill_command": '"drill",',
    "check_command": '"check",',
    "verify_command": '"verify",',
    "local_status_command": '"local-status",',
    "ensure_local_command": '"ensure-local",',
    "seeded_api_key_flag": "--require-seeded-api-key",
    "recovery_proof_contract": "ea.teable_env_recovery_proof.v1",
}


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _git_head(path: Path) -> str:
    return resolve_source_state_head(path)


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return ""


def _check_snippets(*, text: str, snippets: dict[str, str], issue_prefix: str) -> tuple[dict[str, bool], list[str]]:
    checks: dict[str, bool] = {}
    issues: list[str] = []
    for key, snippet in snippets.items():
        present = snippet in text
        checks[key] = present
        if not present:
            issues.append(f"{issue_prefix}:{key}")
    return checks, issues


def build_teable_env_recovery_readiness(
    *,
    root: Path = ROOT,
    output_path: Path = DEFAULT_OUTPUT,
    generated_at: str | None = None,
) -> dict[str, Any]:
    makefile_path = root / MAKEFILE.relative_to(ROOT)
    readme_path = root / README.relative_to(ROOT)
    bootstrap_path = root / BOOTSTRAP_SCRIPT.relative_to(ROOT)
    sync_path = root / SYNC_SCRIPT.relative_to(ROOT)

    makefile_text = _read_text(makefile_path)
    readme_text = _read_text(readme_path)
    bootstrap_text = _read_text(bootstrap_path)
    sync_text = _read_text(sync_path)

    issues: list[str] = []
    source_files = {
        "makefile": makefile_path.exists(),
        "readme": readme_path.exists(),
        "bootstrap_script": bootstrap_path.exists(),
        "sync_script": sync_path.exists(),
    }
    for key, present in source_files.items():
        if not present:
            issues.append(f"recovery_source_missing:{key}")

    makefile_checks, makefile_issues = _check_snippets(
        text=makefile_text, snippets=MAKEFILE_SNIPPETS, issue_prefix="makefile_contract_missing"
    )
    readme_checks, readme_issues = _check_snippets(
        text=readme_text, snippets=README_SNIPPETS, issue_prefix="readme_contract_missing"
    )
    bootstrap_checks, bootstrap_issues = _check_snippets(
        text=bootstrap_text, snippets=BOOTSTRAP_SNIPPETS, issue_prefix="bootstrap_contract_missing"
    )
    sync_checks, sync_issues = _check_snippets(
        text=sync_text, snippets=SYNC_SNIPPETS, issue_prefix="sync_contract_missing"
    )

    issues.extend(makefile_issues)
    issues.extend(readme_issues)
    issues.extend(bootstrap_issues)
    issues.extend(sync_issues)

    command_surface_ready = not issues
    status = "ready_local_audit" if command_surface_ready else "blocked"
    summary = (
        "Teable recovery command surface is mirrored and documented locally; a seeded fresh-host drill receipt is still required before any pass claim."
        if command_surface_ready
        else "Teable recovery readiness is blocked because the local command/docs contract is incomplete."
    )
    next_action = (
        "run_shell_seeded_fresh_host_probe_and_mirror_drill_evidence"
        if command_surface_ready
        else "repair_teable_recovery_contract_surface_and_regenerate_receipt"
    )

    return {
        "contract_name": "ea.teable_env_recovery_readiness.v1",
        "generated_at": generated_at or _utc_now(),
        "generated_by": "scripts/materialize_teable_env_recovery_readiness.py",
        "source_git_head": _git_head(root),
        "head_semantics": "source_state",
        "output_path": str(output_path if output_path.is_absolute() else output_path.as_posix()),
        "status": status,
        "summary": summary,
        "next_action": next_action,
        "command_surface_ready": command_surface_ready,
        "fresh_host_drill_receipt_mirrored": False,
        "claim_limit": "local_command_contract_readiness_not_fresh_host_drill",
        "required_next_receipts": [
            "fresh_host_teable_recovery_drill_receipt",
        ],
        "verifier_commands": [
            "make verify-teable-env-recovery-readiness",
            "make verify-env-teable-recovery",
            "make env-check-teable",
            "make env-probe-teable",
            "make env-fresh-host-teable",
        ],
        "source_files": {
            "makefile": makefile_path.relative_to(root).as_posix() if makefile_path.exists() else "missing",
            "readme": readme_path.relative_to(root).as_posix() if readme_path.exists() else "missing",
            "bootstrap_script": bootstrap_path.relative_to(root).as_posix() if bootstrap_path.exists() else "missing",
            "sync_script": sync_path.relative_to(root).as_posix() if sync_path.exists() else "missing",
        },
        "checks": {
            "makefile": makefile_checks,
            "readme": readme_checks,
            "bootstrap_script": bootstrap_checks,
            "sync_script": sync_checks,
        },
        "issues": issues,
        "rules": [
            "This receipt proves local command and documentation readiness only; it does not prove a fresh-host recovery drill happened.",
            "Do not claim Teable recovery pass from this receipt alone.",
            "A seeded fresh-host probe or drill receipt must be mirrored separately before the recover lens can claim pass.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Materialize the local Teable env recovery readiness receipt.")
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args()

    output_path = args.output if args.output.is_absolute() else args.root / args.output
    receipt = build_teable_env_recovery_readiness(root=args.root, output_path=output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if args.pretty:
        print(json.dumps(receipt, indent=2, sort_keys=True))
    else:
        print(output_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
