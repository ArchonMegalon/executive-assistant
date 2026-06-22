from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]


def _load_script(name: str):
    path = ROOT / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_quality_requirements_are_pinned() -> None:
    path = ROOT / "requirements-dev-quality.txt"
    lines = [
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]

    assert lines
    assert all("==" in line for line in lines)
    assert not any(">=" in line or "<=" in line or "~=" in line for line in lines)


def test_local_quality_gate_contract_passes() -> None:
    module = _load_script("verify_local_quality_gates")

    result = module.verify()

    assert result["contract_name"] == "ea.local_quality_gates.v1"
    assert result["status"] == "pass"
    assert result["issues"] == []
    details = dict(result["details"])
    assert details["quality_requirements"] == "requirements-dev-quality.txt"
    assert details["bandit_targets"] == [
        "ea/app/settings.py",
        "scripts/verify_release_manifest_runtime_mode.py",
        "scripts/verify_release_manifest_artifact_plane.py",
        "scripts/verify_release_authority.py",
        "scripts/verify_runtime_supply_chain.py",
        "scripts/verify_local_quality_gates.py",
    ]
    assert dict(details["ruff"])["status"] == "pass"
    assert dict(details["mypy"])["status"] == "pass"
    assert dict(details["bandit"])["status"] == "pass"
    assert dict(details["pip_audit"])["status"] == "pass"


def test_makefile_wires_local_quality_gate() -> None:
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")

    assert "verify-local-quality-gates:" in makefile
    assert "$(PYTHON_BIN) scripts/verify_local_quality_gates.py" in makefile
    assert "verify-release-authority:" in makefile
    assert "$(PYTHON_BIN) scripts/verify_release_authority.py --pretty" in makefile
    ci_gates_body = makefile.split("ci-gates:\n", 1)[1].split("\n\n", 1)[0]
    assert "$(MAKE) verify-local-quality-gates" in ci_gates_body
