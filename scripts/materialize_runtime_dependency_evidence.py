#!/usr/bin/env python3
from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Any
import uuid


ROOT = Path(__file__).resolve().parents[1]
REQUIREMENTS_PATHS = (ROOT / "ea" / "requirements.txt",)
SBOM_OUTPUT = ROOT / ".codex-studio" / "published" / "runtime_dependency_sbom.cdx.json"
AUDIT_OUTPUT = (
    ROOT / ".codex-studio" / "published" / "runtime_dependency_audit.generated.json"
)
PIP_AUDIT_PYTHON_ENV = "EA_PIP_AUDIT_PYTHON"


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _git_head() -> str:
    completed = subprocess.run(  # nosec B603,B607
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        return ""
    return completed.stdout.strip()


def _requirements(path: Path) -> list[tuple[str, str]]:
    rows: list[tuple[str, str]] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or line.startswith("--"):
            continue
        operator_positions = [
            (line.find(operator), operator)
            for operator in ("===", "==", "~=", "!=", "<=", ">=", "<", ">")
            if line.find(operator) >= 0
        ]
        if not operator_positions:
            raise ValueError(
                f"unsupported requirement without version constraint: {line!r}"
            )
        position, operator = min(operator_positions, key=lambda item: item[0])
        name = line[:position].strip()
        constraint = line[position:].strip()
        if not name or not constraint[len(operator) :].strip():
            raise ValueError(f"invalid requirement constraint: {line!r}")
        version = (
            constraint[len(operator) :].strip() if operator == "==" else constraint
        )
        rows.append((name, version))
    return rows


def _normalized_package_name(value: str) -> str:
    base_name = value.split("[", 1)[0].strip().lower()
    return re.sub(r"[-_.]+", "-", base_name)


def _valid_python_candidate(candidate: Path) -> bool:
    return (
        candidate.is_absolute()
        and candidate.is_file()
        and os.access(candidate, os.X_OK)
    )


def _invoking_python_has_pip_audit() -> bool:
    return importlib.util.find_spec("pip_audit") is not None


def _shared_worktree_python() -> Path | None:
    completed = subprocess.run(  # nosec B603,B607
        ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0 or not completed.stdout.strip():
        return None
    common_dir = Path(completed.stdout.strip())
    if not common_dir.is_absolute():
        common_dir = (ROOT / common_dir).resolve()
    if common_dir.name != ".git":
        return None
    return common_dir.parent / ".venv" / "bin" / "python"


def _pip_audit_python() -> str:
    configured = os.environ.get(PIP_AUDIT_PYTHON_ENV, "").strip()
    if configured:
        candidate = Path(configured).expanduser()
        if not _valid_python_candidate(candidate):
            raise RuntimeError("pip_audit_python_invalid")
        return str(candidate)

    invoking_python = Path(sys.executable).expanduser()
    if _valid_python_candidate(invoking_python) and _invoking_python_has_pip_audit():
        return str(invoking_python)

    shared_worktree_python = _shared_worktree_python()
    if shared_worktree_python is None or not _valid_python_candidate(
        shared_worktree_python
    ):
        raise RuntimeError("pip_audit_python_invalid")
    return str(shared_worktree_python)


def _build_sbom(
    requirement_sets: list[tuple[Path, list[tuple[str, str]]]],
) -> dict[str, Any]:
    components: list[dict[str, Any]] = []
    dependencies: list[dict[str, Any]] = []
    for source_index, (path, requirements) in enumerate(requirement_sets, start=1):
        source_ref = path.relative_to(ROOT).as_posix()
        for package_index, (name, version) in enumerate(requirements, start=1):
            ref = f"pkg:{name}@{version}#{source_index}-{package_index}"
            components.append(
                {
                    "bom-ref": ref,
                    "name": name,
                    "type": "library",
                    "version": version,
                    "properties": [
                        {
                            "name": "ea.requirements_source",
                            "value": source_ref,
                        }
                    ],
                }
            )
            dependencies.append({"ref": ref})
    return {
        "bomFormat": "CycloneDX",
        "specVersion": "1.6",
        "$schema": "http://cyclonedx.org/schema/bom-1.6.schema.json",
        "serialNumber": f"urn:uuid:{uuid.uuid4()}",
        "version": 1,
        "metadata": {"timestamp": _utc_now()},
        "components": components,
        "dependencies": dependencies,
    }


def _pip_audit_json(requirements_path: Path) -> dict[str, Any]:
    audit_python = _pip_audit_python()
    completed = subprocess.run(  # nosec B603
        [
            audit_python,
            "-m",
            "pip_audit",
            "-r",
            str(requirements_path),
            "--progress-spinner",
            "off",
            "--format",
            "json",
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    combined = "\n".join(
        part for part in (completed.stdout, completed.stderr) if part
    ).strip()
    json_line = ""
    for line in reversed(combined.splitlines()):
        stripped = line.strip()
        if stripped.startswith("{") and stripped.endswith("}"):
            json_line = stripped
            break
    if not json_line:
        raise RuntimeError("pip_audit_json_missing")
    try:
        payload = json.loads(json_line)
    except json.JSONDecodeError as exc:
        raise RuntimeError("pip_audit_json_invalid") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("pip_audit_json_invalid")
    raw_dependencies = payload.get("dependencies")
    raw_fixes = payload.get("fixes")
    if not isinstance(raw_dependencies, list) or not all(
        isinstance(item, dict) for item in raw_dependencies
    ):
        raise RuntimeError("pip_audit_dependencies_invalid")
    if not isinstance(raw_fixes, list):
        raise RuntimeError("pip_audit_fixes_invalid")
    required_names = {
        _normalized_package_name(name)
        for name, _version in _requirements(requirements_path)
    }
    audited_names = {
        _normalized_package_name(str(item.get("name") or ""))
        for item in raw_dependencies
        if str(item.get("name") or "").strip()
    }
    if required_names - audited_names:
        raise RuntimeError("pip_audit_direct_requirements_incomplete")
    vulnerable = any(list(item.get("vulns") or []) for item in raw_dependencies)
    if completed.returncode not in {0, 1}:
        raise RuntimeError("pip_audit_execution_failed")
    if completed.returncode == 1 and not vulnerable:
        raise RuntimeError("pip_audit_nonzero_without_vulnerabilities")
    return payload


def materialize() -> dict[str, Any]:
    requirement_sets = [(path, _requirements(path)) for path in REQUIREMENTS_PATHS]
    sbom = _build_sbom(requirement_sets)
    source_receipts: list[dict[str, Any]] = []
    dependencies: list[dict[str, Any]] = []
    vulnerable: list[dict[str, Any]] = []
    total_fix_count = 0
    for requirements_path, _requirements_rows in requirement_sets:
        audit_payload = _pip_audit_json(requirements_path)
        source_dependencies = [
            dict(item)
            for item in list(audit_payload.get("dependencies") or [])
            if isinstance(item, dict)
        ]
        source_vulnerable = [
            item for item in source_dependencies if list(item.get("vulns") or [])
        ]
        source_ref = requirements_path.relative_to(ROOT).as_posix()
        total_fix_count += len(list(audit_payload.get("fixes") or []))
        dependencies.extend(source_dependencies)
        for item in source_vulnerable:
            item = dict(item)
            item["requirements_path"] = source_ref
            vulnerable.append(item)
        source_receipts.append(
            {
                "requirements_path": source_ref,
                "requirements_sha256": _sha256(requirements_path),
                "audit_complete": True,
                "direct_requirement_count": len(_requirements_rows),
                "dependency_count": len(source_dependencies),
                "vulnerable_dependency_count": len(source_vulnerable),
                "fix_count": len(list(audit_payload.get("fixes") or [])),
            }
        )
    receipt = {
        "contract_name": "ea.runtime_dependency_audit.v1",
        "generated_at": _utc_now(),
        "generated_by": "scripts/materialize_runtime_dependency_evidence.py",
        "source_git_head": _git_head(),
        "requirements_path": (ROOT / "ea" / "requirements.txt")
        .relative_to(ROOT)
        .as_posix(),
        "requirements_sha256": _sha256(ROOT / "ea" / "requirements.txt"),
        "requirements_sources": source_receipts,
        "audit_complete": True,
        "direct_requirement_count": sum(len(rows) for _path, rows in requirement_sets),
        "sbom_path": SBOM_OUTPUT.relative_to(ROOT).as_posix(),
        "sbom_sha256": "",
        "dependency_count": len(dependencies),
        "vulnerable_dependency_count": len(vulnerable),
        "fix_count": total_fix_count,
        "vulnerable_dependencies": [
            {
                "name": str(item.get("name") or ""),
                "version": str(item.get("version") or ""),
                "requirements_path": str(item.get("requirements_path") or ""),
                "vulnerability_ids": [
                    str(vuln.get("id") or "")
                    for vuln in list(item.get("vulns") or [])
                    if isinstance(vuln, dict)
                ],
            }
            for item in vulnerable
        ],
        "status": "pass" if not vulnerable else "fail",
    }
    SBOM_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    SBOM_OUTPUT.write_text(
        json.dumps(sbom, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    receipt["sbom_sha256"] = _sha256(SBOM_OUTPUT)
    AUDIT_OUTPUT.write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return receipt


def main() -> int:
    receipt = materialize()
    print(json.dumps(receipt, indent=2, sort_keys=True))
    return 0 if receipt["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
