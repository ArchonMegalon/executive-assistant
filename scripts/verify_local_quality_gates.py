#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path
import subprocess  # nosec B404


ROOT = Path(__file__).resolve().parents[1]
PYTHON_BIN = ROOT / ".venv" / "bin" / "python"
RUFF_BIN = ROOT / ".venv" / "bin" / "ruff"
MYPY_BIN = ROOT / ".venv" / "bin" / "mypy"
QUALITY_REQUIREMENTS = ROOT / "requirements-dev-quality.txt"
TARGETS = [
    "ea/app/settings.py",
    "scripts/materialize_release_manifest.py",
    "scripts/verify_release_manifest_runtime_mode.py",
    "scripts/verify_release_manifest_artifact_plane.py",
    "scripts/verify_release_authority.py",
    "scripts/verify_runtime_supply_chain.py",
    "scripts/verify_local_quality_gates.py",
]
BANDIT_TARGETS = [
    "ea/app/settings.py",
    "scripts/verify_release_manifest_runtime_mode.py",
    "scripts/verify_release_manifest_artifact_plane.py",
    "scripts/verify_release_authority.py",
    "scripts/verify_runtime_supply_chain.py",
    "scripts/verify_local_quality_gates.py",
]


def _run(command: list[str], *, env: dict[str, str] | None = None) -> tuple[int, str]:
    completed = subprocess.run(  # nosec B603
        command,
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )
    output = "\n".join(part for part in (completed.stdout.strip(), completed.stderr.strip()) if part).strip()
    return completed.returncode, output


def verify() -> dict[str, object]:
    issues: list[str] = []
    details: dict[str, object] = {
        "targets": TARGETS,
        "bandit_targets": BANDIT_TARGETS,
        "quality_requirements": QUALITY_REQUIREMENTS.relative_to(ROOT).as_posix(),
    }

    if not QUALITY_REQUIREMENTS.is_file():
        issues.append("quality_requirements_missing")
    if not RUFF_BIN.is_file():
        issues.append("ruff_missing")
    if not MYPY_BIN.is_file():
        issues.append("mypy_missing")
    if not PYTHON_BIN.is_file():
        issues.append("venv_python_missing")

    if not issues:
        code, output = _run([str(RUFF_BIN), "check", *TARGETS])
        details["ruff"] = {"status": "pass" if code == 0 else "fail", "output": output}
        if code != 0:
            issues.append("ruff_failed")

        code, output = _run(
            [
                str(MYPY_BIN),
                "--hide-error-context",
                "--no-error-summary",
                *TARGETS,
            ],
            env={"PYTHONPATH": "ea"},
        )
        details["mypy"] = {"status": "pass" if code == 0 else "fail", "output": output}
        if code != 0:
            issues.append("mypy_failed")

        code, output = _run([str(PYTHON_BIN), "-m", "bandit", "-q", "-r", *BANDIT_TARGETS])
        details["bandit"] = {"status": "pass" if code == 0 else "fail", "output": output}
        if code != 0:
            issues.append("bandit_failed")

        code, output = _run([str(PYTHON_BIN), "-m", "pip_audit", "-r", "ea/requirements.txt", "--progress-spinner", "off"])
        details["pip_audit"] = {"status": "pass" if code == 0 else "fail", "output": output}
        if code != 0:
            issues.append("pip_audit_failed")

    return {
        "contract_name": "ea.local_quality_gates.v1",
        "status": "pass" if not issues else "fail",
        "issues": issues,
        "details": details,
    }


def main() -> int:
    result = verify()
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
