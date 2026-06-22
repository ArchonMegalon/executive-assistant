#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / "ea"
PIN_RE = re.compile(r"^[A-Za-z0-9_.+\-\[\]]+==[^=\s]+$")
DOCKER_RE = re.compile(r"^FROM\s+python:(?P<tag>3\.(?:11|12)-slim)@sha256:(?P<digest>[a-f0-9]{64})\s*$", re.MULTILINE)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _pinned_requirements(path: Path) -> list[str]:
    rows: list[str] = []
    for raw in _read(path).splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or line.startswith("--"):
            continue
        rows.append(line)
    return rows


def verify() -> dict[str, object]:
    issues: list[str] = []

    requirements = _pinned_requirements(APP_ROOT / "requirements.txt")
    openvoice_requirements = _pinned_requirements(APP_ROOT / "requirements-openvoice.txt")
    if not requirements:
        issues.append("requirements_txt_empty")
    if not openvoice_requirements:
        issues.append("requirements_openvoice_empty")
    if any(not PIN_RE.match(line) for line in requirements):
        issues.append("requirements_txt_unpinned_entries")
    if any(not PIN_RE.match(line) for line in openvoice_requirements):
        issues.append("requirements_openvoice_unpinned_entries")

    lock_text = _read(APP_ROOT / "requirements.lock")
    if not lock_text.strip():
        issues.append("requirements_lock_empty")

    for rel in ("ea/Dockerfile", "ea/Dockerfile.operator", "ea/Dockerfile.openvoice", "Dockerfile"):
        text = _read(ROOT / rel)
        if not DOCKER_RE.search(text):
            issues.append(f"docker_base_not_pinned:{rel}")
    if "pip install --no-cache-dir -r requirements.txt -c requirements.lock" not in _read(APP_ROOT / "Dockerfile.operator"):
        issues.append("operator_image_missing_locked_install")
    if "pip install --no-cache-dir -r requirements.txt;" in _read(APP_ROOT / "Dockerfile.operator"):
        issues.append("operator_image_has_unlocked_install_fallback")
    if "pip install --no-cache-dir -r requirements.txt -c requirements.lock" not in _read(ROOT / "Dockerfile"):
        issues.append("root_image_missing_locked_install")

    return {
        "contract_name": "ea.runtime_supply_chain.v1",
        "status": "pass" if not issues else "fail",
        "issues": issues,
        "checked": {
            "requirements_txt": "ea/requirements.txt",
            "requirements_openvoice_txt": "ea/requirements-openvoice.txt",
            "requirements_lock": "ea/requirements.lock",
            "dockerfiles": [
                "ea/Dockerfile",
                "ea/Dockerfile.operator",
                "ea/Dockerfile.openvoice",
                "Dockerfile",
            ],
        },
    }


def main() -> int:
    result = verify()
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
