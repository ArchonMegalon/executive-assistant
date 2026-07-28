from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]


def _load_script(name: str):
    path = ROOT / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _offline_audit_payload(materializer, requirements_path: Path) -> dict[str, object]:
    return {
        "dependencies": [
            {
                "name": name.split("[", 1)[0],
                "version": version,
                "vulns": [],
            }
            for name, version in materializer._requirements(requirements_path)
        ],
        "fixes": [],
    }


def _isolated_materializer(monkeypatch, tmp_path: Path):
    materializer = _load_script("materialize_runtime_dependency_evidence")
    requirements_path = tmp_path / "ea" / "requirements.txt"
    requirements_path.parent.mkdir(parents=True, exist_ok=True)
    requirements_path.write_text(
        (ROOT / "ea" / "requirements.txt").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    monkeypatch.setattr(materializer, "ROOT", tmp_path)
    monkeypatch.setattr(materializer, "REQUIREMENTS_PATHS", (requirements_path,))
    monkeypatch.setattr(
        materializer,
        "SBOM_OUTPUT",
        tmp_path / ".codex-studio" / "published" / "runtime_dependency_sbom.cdx.json",
    )
    monkeypatch.setattr(
        materializer,
        "AUDIT_OUTPUT",
        tmp_path
        / ".codex-studio"
        / "published"
        / "runtime_dependency_audit.generated.json",
    )
    return materializer


def test_runtime_dependency_materializer_writes_pass_receipts(
    monkeypatch,
    tmp_path: Path,
) -> None:
    materializer = _isolated_materializer(monkeypatch, tmp_path)
    monkeypatch.setattr(
        materializer,
        "_pip_audit_json",
        lambda path: _offline_audit_payload(materializer, path),
    )

    receipt = materializer.materialize()

    assert receipt["contract_name"] == "ea.runtime_dependency_audit.v1"
    assert receipt["status"] == "pass"
    assert receipt["audit_complete"] is True
    assert receipt["direct_requirement_count"] == 21
    assert receipt["dependency_count"] >= receipt["direct_requirement_count"]
    assert receipt["vulnerable_dependency_count"] == 0
    sbom_path = tmp_path / str(receipt["sbom_path"])
    assert sbom_path.is_file()
    sbom = json.loads(sbom_path.read_text(encoding="utf-8"))
    assert sbom["bomFormat"] == "CycloneDX"
    assert sbom["specVersion"] == "1.6"
    assert len(list(sbom.get("components") or [])) >= 10
    requirement_sources = {str(item["requirements_path"]) for item in list(receipt.get("requirements_sources") or [])}
    assert requirement_sources == {"ea/requirements.txt"}
    assert all(str(item.get("requirements_sha256") or "").strip() for item in list(receipt.get("requirements_sources") or []))
    sbom_sources = {
        str(prop.get("value") or "")
        for component in list(sbom.get("components") or [])
        if isinstance(component, dict)
        for prop in list(component.get("properties") or [])
        if isinstance(prop, dict) and str(prop.get("name") or "") == "ea.requirements_source"
    }
    assert {"ea/requirements.txt"} <= sbom_sources


def test_runtime_dependency_audit_uses_invoking_python(
    monkeypatch,
    tmp_path: Path,
) -> None:
    materializer = _load_script("materialize_runtime_dependency_evidence")
    monkeypatch.delenv(materializer.PIP_AUDIT_PYTHON_ENV, raising=False)
    requirements_path = tmp_path / "requirements.txt"
    requirements_path.write_text("example==1.0\n", encoding="utf-8")
    captured: list[str] = []

    def fake_run(command: list[str], **_kwargs):
        captured.extend(command)
        return materializer.subprocess.CompletedProcess(
            command,
            0,
            stdout='{"dependencies": [{"name": "example", "version": "1.0", "vulns": []}], "fixes": []}',
            stderr="",
        )

    monkeypatch.setattr(materializer.subprocess, "run", fake_run)

    payload = materializer._pip_audit_json(requirements_path)

    assert payload == {
        "dependencies": [{"name": "example", "version": "1.0", "vulns": []}],
        "fixes": [],
    }
    assert captured[:3] == [sys.executable, "-m", "pip_audit"]


def test_runtime_dependency_audit_fails_closed_when_tool_execution_fails(
    monkeypatch,
    tmp_path: Path,
) -> None:
    materializer = _load_script("materialize_runtime_dependency_evidence")
    requirements_path = tmp_path / "requirements.txt"
    requirements_path.write_text("example==1.0\n", encoding="utf-8")

    def fake_run(command: list[str], **_kwargs):
        return materializer.subprocess.CompletedProcess(
            command,
            2,
            stdout="",
            stderr="pip-audit unavailable",
        )

    monkeypatch.setattr(materializer.subprocess, "run", fake_run)

    with pytest.raises(RuntimeError, match="pip_audit_json_missing"):
        materializer._pip_audit_json(requirements_path)


def test_runtime_dependency_materializer_accepts_exact_and_bounded_constraints(
    tmp_path: Path,
) -> None:
    materializer = _load_script("materialize_runtime_dependency_evidence")
    requirements_path = tmp_path / "requirements.txt"
    requirements_path.write_text(
        "exact-package==1.2.3\n"
        "bounded-package>=48.0.1,<49.0.0\n",
        encoding="utf-8",
    )

    assert materializer._requirements(requirements_path) == [
        ("exact-package", "1.2.3"),
        ("bounded-package", ">=48.0.1,<49.0.0"),
    ]


def test_runtime_dependency_verifier_passes_for_current_tree(
    monkeypatch,
    tmp_path: Path,
) -> None:
    materializer = _isolated_materializer(monkeypatch, tmp_path)
    verifier = _load_script("verify_runtime_dependency_evidence")
    monkeypatch.setattr(verifier, "ROOT", tmp_path)
    monkeypatch.setattr(verifier, "SBOM_PATH", materializer.SBOM_OUTPUT)
    monkeypatch.setattr(verifier, "AUDIT_PATH", materializer.AUDIT_OUTPUT)
    monkeypatch.setattr(
        materializer,
        "_pip_audit_json",
        lambda path: _offline_audit_payload(materializer, path),
    )
    _ = materializer.materialize()

    result = verifier.verify()

    assert result["contract_name"] == "ea.runtime_dependency_evidence_verify.v1"
    assert result["status"] == "pass"
    assert result["issues"] == []


def test_runtime_dependency_verifier_rejects_empty_audit_coverage(
    monkeypatch,
    tmp_path: Path,
) -> None:
    verifier = _load_script("verify_runtime_dependency_evidence")
    monkeypatch.setattr(verifier, "ROOT", tmp_path)
    monkeypatch.setattr(verifier, "SBOM_PATH", tmp_path / "runtime-sbom.json")
    monkeypatch.setattr(verifier, "AUDIT_PATH", tmp_path / "runtime-audit.json")
    requirements_path = tmp_path / "ea" / "requirements.txt"
    requirements_path.parent.mkdir(parents=True)
    requirements_path.write_text("example==1.0\n", encoding="utf-8")
    verifier.SBOM_PATH.write_text(
        json.dumps(
            {
                "bomFormat": "CycloneDX",
                "specVersion": "1.6",
                "components": [
                    {
                        "name": "example",
                        "properties": [
                            {"name": "ea.requirements_source", "value": "ea/requirements.txt"}
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    verifier.AUDIT_PATH.write_text(
        json.dumps(
            {
                "contract_name": "ea.runtime_dependency_audit.v1",
                "status": "pass",
                "audit_complete": True,
                "vulnerable_dependency_count": 0,
                "sbom_path": "runtime-sbom.json",
                "direct_requirement_count": 1,
                "dependency_count": 0,
                "requirements_sources": [
                    {
                        "requirements_path": "ea/requirements.txt",
                        "requirements_sha256": "present",
                        "audit_complete": True,
                        "direct_requirement_count": 1,
                        "dependency_count": 0,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    result = verifier.verify()

    assert result["status"] == "fail"
    assert "audit_dependency_coverage_incomplete" in result["issues"]


def test_makefile_wires_runtime_dependency_evidence_gate() -> None:
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")

    assert "PIP_AUDIT_PYTHON ?= $(abspath $(PYTHON_BIN))" in makefile
    assert "materialize-runtime-dependency-evidence:" in makefile
    assert "verify-runtime-dependency-evidence:" in makefile
    assert 'EA_PIP_AUDIT_PYTHON="$(PIP_AUDIT_PYTHON)"' in makefile
    ci_gates_body = makefile.split("ci-gates:\n", 1)[1].split("\n\n", 1)[0]
    assert "$(MAKE) verify-runtime-dependency-evidence" in ci_gates_body
