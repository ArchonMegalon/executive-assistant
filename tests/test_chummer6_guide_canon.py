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
    assert "when" in catalog["hub"]
    assert "notice" in catalog["hub"]
    assert "limits" in catalog["hub"]


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
        "table-pulse",
    }
    assert "ghostwire" not in catalog
    assert "knowledge-fabric" not in catalog
    assert "local-co-processor" not in catalog
    assert "rule-x-ray" not in catalog
    assert "heat-web" not in catalog


def test_load_faq_and_help_canon_track_public_question_sets() -> None:
    canon = _load_module()

    faq = canon.load_faq_canon()
    help_copy = canon.load_help_canon()

    assert "participation_and_preview" in faq
    questions = {entry["question"] for entry in faq["participation_and_preview"]["entries"]}
    assert "What is a booster?" in questions
    assert "Will booster-first previews become free later?" in questions
    assert "the cheap baseline remains the default path" in help_copy["privacy_and_review_safety"]
