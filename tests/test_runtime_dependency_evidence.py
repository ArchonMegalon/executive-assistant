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


def test_runtime_dependency_materializer_writes_pass_receipts() -> None:
    materializer = _load_script("materialize_runtime_dependency_evidence")

    receipt = materializer.materialize()

    assert receipt["contract_name"] == "ea.runtime_dependency_audit.v1"
    assert receipt["status"] == "pass"
    assert receipt["vulnerable_dependency_count"] == 0
    sbom_path = ROOT / str(receipt["sbom_path"])
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


def test_runtime_dependency_verifier_passes_for_current_tree() -> None:
    materializer = _load_script("materialize_runtime_dependency_evidence")
    verifier = _load_script("verify_runtime_dependency_evidence")
    _ = materializer.materialize()

    result = verifier.verify()

    assert result["contract_name"] == "ea.runtime_dependency_evidence_verify.v1"
    assert result["status"] == "pass"
    assert result["issues"] == []


def test_makefile_wires_runtime_dependency_evidence_gate() -> None:
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")

    assert "materialize-runtime-dependency-evidence:" in makefile
    assert "verify-runtime-dependency-evidence:" in makefile
    ci_gates_body = makefile.split("ci-gates:\n", 1)[1].split("\n\n", 1)[0]
    assert "$(MAKE) verify-runtime-dependency-evidence" in ci_gates_body
