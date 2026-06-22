from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType


ROOT = Path(__file__).resolve().parents[1]


def _load_script(name: str) -> ModuleType:
    path = ROOT / "scripts" / name
    spec = importlib.util.spec_from_file_location(path.stem, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_ltd_mesh_scripts_default_to_design_mirror_and_repo_local_completion(monkeypatch) -> None:
    monkeypatch.delenv("CHUMMER6_DESIGN_PRODUCT_ROOT", raising=False)
    monkeypatch.delenv("LTD_CAPABILITY_MESH_COMPLETION_DIR", raising=False)

    verify_mesh = _load_script("verify_ltd_capability_mesh.py")
    expected_completion = ROOT / "ea/_completion/ltd_capability_mesh_v2"

    assert verify_mesh.EA_ROOT == ROOT
    assert verify_mesh.DESIGN_ROOT == ROOT / ".codex-design/product"
    assert verify_mesh.COMPLETION_DIR == expected_completion

    rendered = "\n".join(
        (ROOT / "scripts" / name).read_text(encoding="utf-8")
        for name in (
            "verify_ltd_capability_mesh.py",
            "sync_chummer_projection_to_teable.py",
            "productlift_signal_bridge_e2e.py",
            "verify_teable_projection_adapter.py",
        )
    )
    host_specific_root = "/docker/" + "chummercomplete"
    assert host_specific_root not in rendered
    assert "LTD_CAPABILITY_MESH_COMPLETION_DIR" in rendered
    assert "ea/_completion/ltd_capability_mesh_v2" in rendered


def test_ltd_mesh_scripts_honor_path_overrides(monkeypatch, tmp_path: Path) -> None:
    design_root = tmp_path / "design"
    completion_dir = tmp_path / "completion"
    monkeypatch.setenv("CHUMMER6_DESIGN_PRODUCT_ROOT", str(design_root))
    monkeypatch.setenv("LTD_CAPABILITY_MESH_COMPLETION_DIR", str(completion_dir))

    verify_mesh = _load_script("verify_ltd_capability_mesh.py")

    assert verify_mesh.DESIGN_ROOT == design_root
    assert verify_mesh.COMPLETION_DIR == completion_dir
