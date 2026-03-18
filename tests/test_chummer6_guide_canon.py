from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "chummer6_guide_canon.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("chummer6_guide_canon", MODULE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load module from {MODULE_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_load_part_canon_tracks_current_active_repo_graph() -> None:
    canon = _load_module()

    catalog = canon.load_part_canon()

    assert set(catalog) >= {
        "design",
        "core",
        "ui",
        "mobile",
        "hub",
        "ui-kit",
        "hub-registry",
        "media-factory",
    }
    assert "presentation" not in catalog
    assert "play" not in catalog
    assert "run-services" not in catalog


def test_load_horizon_canon_tracks_live_design_horizons() -> None:
    canon = _load_module()

    catalog = canon.load_horizon_canon()

    assert set(catalog) >= {
        "nexus-pan",
        "alice",
        "karma-forge",
        "jackpoint",
        "runsite",
        "runbook-press",
    }
    assert "ghostwire" not in catalog
    assert "rule-x-ray" not in catalog
    assert "heat-web" not in catalog
