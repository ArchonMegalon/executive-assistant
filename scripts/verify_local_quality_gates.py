#!/usr/bin/env python3
from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import re
import subprocess  # nosec B404


ROOT = Path(__file__).resolve().parents[1]
PYTHON_BIN = ROOT / ".venv" / "bin" / "python"
RUFF_BIN = ROOT / ".venv" / "bin" / "ruff"
MYPY_BIN = ROOT / ".venv" / "bin" / "mypy"
QUALITY_REQUIREMENTS = ROOT / "requirements-dev-quality.txt"
ENV_SECRET_GUARD = ROOT / "scripts" / "verify_env_no_secrets.py"
CODEXEA_E2E_EXIT_GATE = ROOT / "scripts" / "verify_codexea_e2e_exit_gate.sh"
CODEXEA_FLEET_SHIM_PARITY = ROOT / "scripts" / "verify_codexea_fleet_shim_parity.py"
PIP_AUDIT_REQUIREMENTS = [
    "ea/requirements.txt",
]
TARGETS = [
    "ea/app/settings.py",
    "scripts/materialize_release_manifest.py",
    "scripts/verify_release_manifest_runtime_mode.py",
    "scripts/verify_release_manifest_artifact_plane.py",
    "scripts/verify_release_authority.py",
    "scripts/verify_runtime_supply_chain.py",
    "scripts/verify_codexea_fleet_shim_parity.py",
    "scripts/verify_local_quality_gates.py",
]
BANDIT_TARGETS = [
    "ea/app/settings.py",
    "scripts/verify_release_manifest_runtime_mode.py",
    "scripts/verify_release_manifest_artifact_plane.py",
    "scripts/verify_release_authority.py",
    "scripts/verify_runtime_supply_chain.py",
    "scripts/verify_codexea_fleet_shim_parity.py",
    "scripts/verify_local_quality_gates.py",
]


def _env_int(name: str, default: int, *, minimum: int) -> tuple[int, bool, str]:
    raw = str(os.environ.get(name) or "").strip()
    if not raw:
        return default, True, raw
    if not re.fullmatch(r"-?\d+", raw):
        return default, False, raw
    try:
        value = int(raw)
    except Exception:
        return default, False, raw
    if value < minimum:
        return default, False, raw
    return value, True, raw


(
    CODEXEA_E2E_EXIT_GATE_TIMEOUT_SECONDS,
    CODEXEA_E2E_EXIT_GATE_TIMEOUT_SECONDS_VALID,
    CODEXEA_E2E_EXIT_GATE_TIMEOUT_SECONDS_RAW,
) = _env_int(
    "CODEXEA_E2E_EXIT_GATE_TIMEOUT_SECONDS",
    300,
    minimum=1,
)
(
    CODEXEA_E2E_EXIT_GATE_SUPERVISOR_GRACE_SECONDS,
    CODEXEA_E2E_EXIT_GATE_SUPERVISOR_GRACE_SECONDS_VALID,
    CODEXEA_E2E_EXIT_GATE_SUPERVISOR_GRACE_SECONDS_RAW,
) = _env_int(
    "CODEXEA_E2E_EXIT_GATE_SUPERVISOR_GRACE_SECONDS",
    30,
    minimum=5,
)


def _run(
    command: list[str],
    *,
    env: dict[str, str] | None = None,
    timeout_seconds: int | None = None,
) -> dict[str, object]:
    try:
        completed = subprocess.run(  # nosec B603
            command,
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
            env=env,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as exc:
        stdout = (exc.stdout or "").strip() if isinstance(exc.stdout, str) else ""
        stderr = (exc.stderr or "").strip() if isinstance(exc.stderr, str) else ""
        output = "\n".join(
            part
            for part in (
                f"Command timed out after {int(timeout_seconds or 0)}s",
                stdout,
                stderr,
            )
            if part
        ).strip()
        return {
            "returncode": 124,
            "output": output,
            "timed_out": True,
            "timeout_seconds": timeout_seconds,
        }
    output = "\n".join(part for part in (completed.stdout.strip(), completed.stderr.strip()) if part).strip()
    return {
        "returncode": completed.returncode,
        "output": output,
        "timed_out": False,
        "timeout_seconds": timeout_seconds,
    }


def verify() -> dict[str, object]:
    issues: list[str] = []
    details: dict[str, object] = {
        "targets": TARGETS,
        "bandit_targets": BANDIT_TARGETS,
        "quality_requirements": QUALITY_REQUIREMENTS.relative_to(ROOT).as_posix(),
        "env_secret_guard": ENV_SECRET_GUARD.relative_to(ROOT).as_posix(),
        "codexea_e2e_exit_gate": CODEXEA_E2E_EXIT_GATE.relative_to(ROOT).as_posix(),
        "codexea_fleet_shim_parity": CODEXEA_FLEET_SHIM_PARITY.relative_to(ROOT).as_posix(),
        "codexea_e2e_exit_gate_timeout_seconds": CODEXEA_E2E_EXIT_GATE_TIMEOUT_SECONDS,
        "codexea_e2e_exit_gate_timeout_seconds_valid": CODEXEA_E2E_EXIT_GATE_TIMEOUT_SECONDS_VALID,
        "codexea_e2e_exit_gate_timeout_seconds_raw": CODEXEA_E2E_EXIT_GATE_TIMEOUT_SECONDS_RAW,
        "codexea_e2e_exit_gate_supervisor_grace_seconds": CODEXEA_E2E_EXIT_GATE_SUPERVISOR_GRACE_SECONDS,
        "codexea_e2e_exit_gate_supervisor_grace_seconds_valid": CODEXEA_E2E_EXIT_GATE_SUPERVISOR_GRACE_SECONDS_VALID,
        "codexea_e2e_exit_gate_supervisor_grace_seconds_raw": CODEXEA_E2E_EXIT_GATE_SUPERVISOR_GRACE_SECONDS_RAW,
        "pip_audit_requirements": list(PIP_AUDIT_REQUIREMENTS),
    }

    if not QUALITY_REQUIREMENTS.is_file():
        issues.append("quality_requirements_missing")
    if not RUFF_BIN.is_file():
        issues.append("ruff_missing")
    if not MYPY_BIN.is_file():
        issues.append("mypy_missing")
    if not PYTHON_BIN.is_file():
        issues.append("venv_python_missing")
    if not ENV_SECRET_GUARD.is_file():
        issues.append("env_secret_guard_missing")
    if not CODEXEA_E2E_EXIT_GATE.is_file():
        issues.append("codexea_e2e_exit_gate_missing")
    if not CODEXEA_FLEET_SHIM_PARITY.is_file():
        issues.append("codexea_fleet_shim_parity_missing")
    if not CODEXEA_E2E_EXIT_GATE_TIMEOUT_SECONDS_VALID:
        issues.append("codexea_e2e_exit_gate_timeout_seconds_invalid")
    if not CODEXEA_E2E_EXIT_GATE_SUPERVISOR_GRACE_SECONDS_VALID:
        issues.append("codexea_e2e_exit_gate_supervisor_grace_seconds_invalid")

    if not issues:
        codexea_gate = _run(
            ["bash", str(CODEXEA_E2E_EXIT_GATE)],
            timeout_seconds=CODEXEA_E2E_EXIT_GATE_TIMEOUT_SECONDS + CODEXEA_E2E_EXIT_GATE_SUPERVISOR_GRACE_SECONDS,
        )
        details["codexea_e2e_exit_gate_result"] = {
            "status": "pass" if codexea_gate["returncode"] == 0 else "fail",
            "output": codexea_gate["output"],
            "timed_out": bool(codexea_gate["timed_out"]),
            "timeout_seconds": codexea_gate["timeout_seconds"],
        }
        if codexea_gate["returncode"] != 0:
            issues.append("codexea_e2e_exit_gate_failed")

        codexea_parity = _run([str(PYTHON_BIN), str(CODEXEA_FLEET_SHIM_PARITY)])
        details["codexea_fleet_shim_parity_result"] = {
            "status": "pass" if codexea_parity["returncode"] == 0 else "fail",
            "output": codexea_parity["output"],
        }
        if codexea_parity["returncode"] != 0:
            issues.append("codexea_fleet_shim_parity_failed")

        env_guard = _run([str(PYTHON_BIN), str(ENV_SECRET_GUARD)])
        details["env_secret_guard_result"] = {"status": "pass" if env_guard["returncode"] == 0 else "fail", "output": env_guard["output"]}
        if env_guard["returncode"] != 0:
            issues.append("env_secret_guard_failed")

        ruff_result = _run([str(RUFF_BIN), "check", *TARGETS])
        details["ruff"] = {"status": "pass" if ruff_result["returncode"] == 0 else "fail", "output": ruff_result["output"]}
        if ruff_result["returncode"] != 0:
            issues.append("ruff_failed")

        mypy_result = _run(
            [
                str(MYPY_BIN),
                "--hide-error-context",
                "--no-error-summary",
                *TARGETS,
            ],
            env={"PYTHONPATH": "ea"},
        )
        details["mypy"] = {"status": "pass" if mypy_result["returncode"] == 0 else "fail", "output": mypy_result["output"]}
        if mypy_result["returncode"] != 0:
            issues.append("mypy_failed")

        bandit_result = _run([str(PYTHON_BIN), "-m", "bandit", "-q", "-r", *BANDIT_TARGETS])
        details["bandit"] = {"status": "pass" if bandit_result["returncode"] == 0 else "fail", "output": bandit_result["output"]}
        if bandit_result["returncode"] != 0:
            issues.append("bandit_failed")

        pip_audit_runs: list[dict[str, str]] = []
        pip_audit_failed = False
        for requirements_path in PIP_AUDIT_REQUIREMENTS:
            pip_audit_result = _run([str(PYTHON_BIN), "-m", "pip_audit", "-r", requirements_path, "--progress-spinner", "off"])
            pip_audit_runs.append(
                {
                    "requirements_path": requirements_path,
                    "status": "pass" if pip_audit_result["returncode"] == 0 else "fail",
                    "output": str(pip_audit_result["output"]),
                }
            )
            if pip_audit_result["returncode"] != 0:
                pip_audit_failed = True
        details["pip_audit"] = {"status": "pass" if not pip_audit_failed else "fail", "runs": pip_audit_runs}
        if pip_audit_failed:
            issues.append("pip_audit_failed")

    return {
        "contract_name": "ea.local_quality_gates.v1",
        "status": "pass" if not issues else "fail",
        "issues": issues,
        "details": details,
    }


def main() -> int:
    if len(sys.argv) > 1 and sys.argv[1] in {"--help", "-h"}:
        print(
            "\n".join(
                [
                    "Usage:",
                    "  python3 scripts/verify_local_quality_gates.py",
                    "",
                    "Runs the local quality verifier, including the spawned CodexEA",
                    "E2E gate, env secret guard, ruff, mypy, bandit, and pip-audit.",
                    "",
                    "Environment:",
                    "  CODEXEA_E2E_EXIT_GATE_TIMEOUT_SECONDS",
                    "      Integer seconds for the CodexEA gate timeout. Default: 300.",
                    "  CODEXEA_E2E_EXIT_GATE_SUPERVISOR_GRACE_SECONDS",
                    "      Integer grace seconds above the gate timeout. Default: 30.",
                ]
            )
        )
        return 0
    if len(sys.argv) > 1:
        print(f"Unknown arguments: {' '.join(sys.argv[1:])}", file=sys.stderr)
        return 2
    result = verify()
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
