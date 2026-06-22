#!/usr/bin/env python3
from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import subprocess
from typing import Any
import uuid


ROOT = Path(__file__).resolve().parents[1]
REQUIREMENTS_PATH = ROOT / "ea" / "requirements.txt"
SBOM_OUTPUT = ROOT / ".codex-studio" / "published" / "runtime_dependency_sbom.cdx.json"
AUDIT_OUTPUT = ROOT / ".codex-studio" / "published" / "runtime_dependency_audit.generated.json"


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


def _requirements() -> list[tuple[str, str]]:
    rows: list[tuple[str, str]] = []
    for raw in REQUIREMENTS_PATH.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or line.startswith("--"):
            continue
        name, version = line.split("==", 1)
        rows.append((name.strip(), version.strip()))
    return rows


def _build_sbom(requirements: list[tuple[str, str]]) -> dict[str, Any]:
    components: list[dict[str, Any]] = []
    dependencies: list[dict[str, Any]] = []
    for index, (name, version) in enumerate(requirements, start=1):
        ref = f"pkg:{name}@{version}#{index}"
        components.append(
            {
                "bom-ref": ref,
                "name": name,
                "type": "library",
                "version": version,
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


def _pip_audit_json() -> dict[str, Any]:
    completed = subprocess.run(  # nosec B603
        [
            str(ROOT / ".venv" / "bin" / "python"),
            "-m",
            "pip_audit",
            "-r",
            str(REQUIREMENTS_PATH),
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
    combined = "\n".join(part for part in (completed.stdout, completed.stderr) if part).strip()
    json_line = ""
    for line in reversed(combined.splitlines()):
        stripped = line.strip()
        if stripped.startswith("{") and stripped.endswith("}"):
            json_line = stripped
            break
    payload = json.loads(json_line or "{}")
    if not isinstance(payload, dict):
        raise RuntimeError("pip_audit_json_invalid")
    return payload


def materialize() -> dict[str, Any]:
    requirements = _requirements()
    sbom = _build_sbom(requirements)
    audit_payload = _pip_audit_json()
    dependencies = [dict(item) for item in list(audit_payload.get("dependencies") or []) if isinstance(item, dict)]
    vulnerable = [item for item in dependencies if list(item.get("vulns") or [])]
    receipt = {
        "contract_name": "ea.runtime_dependency_audit.v1",
        "generated_at": _utc_now(),
        "generated_by": "scripts/materialize_runtime_dependency_evidence.py",
        "source_git_head": _git_head(),
        "requirements_path": REQUIREMENTS_PATH.relative_to(ROOT).as_posix(),
        "requirements_sha256": _sha256(REQUIREMENTS_PATH),
        "sbom_path": SBOM_OUTPUT.relative_to(ROOT).as_posix(),
        "sbom_sha256": "",
        "dependency_count": len(dependencies),
        "vulnerable_dependency_count": len(vulnerable),
        "fix_count": len(list(audit_payload.get("fixes") or [])),
        "vulnerable_dependencies": [
            {
                "name": str(item.get("name") or ""),
                "version": str(item.get("version") or ""),
                "vulnerability_ids": [str(vuln.get("id") or "") for vuln in list(item.get("vulns") or []) if isinstance(vuln, dict)],
            }
            for item in vulnerable
        ],
        "status": "pass" if not vulnerable else "fail",
    }
    SBOM_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    SBOM_OUTPUT.write_text(json.dumps(sbom, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    receipt["sbom_sha256"] = _sha256(SBOM_OUTPUT)
    AUDIT_OUTPUT.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return receipt


def main() -> int:
    receipt = materialize()
    print(json.dumps(receipt, indent=2, sort_keys=True))
    return 0 if receipt["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
