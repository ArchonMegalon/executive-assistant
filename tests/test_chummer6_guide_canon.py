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
    assert "What is guided contribution?" in questions
    assert "Will guided-preview lanes open wider later?" in questions
    assert "the cheap baseline remains the default path" in help_copy["privacy_and_review_safety"]


def test_asset_visual_profile_derives_critical_first_contact_requirements() -> None:
    canon = _load_module()

    hero = canon.asset_visual_profile("assets/hero/chummer6-hero.png")
    readme = canon.asset_visual_profile("README.md")
    horizons = canon.asset_visual_profile("assets/pages/horizons-index.png")
    forge = canon.asset_visual_profile("assets/horizons/karma-forge.png")

    assert hero["visual_density_profile"] == "first_contact_hero"
    assert hero["required_person_count"] == "duo_or_team"
    assert hero["required_overlay_mode"] == "medscan_diagnostic"
    assert hero["critical_style_overrides_shared_prompt_scaffold"] is True
    assert hero["style_epoch_force_only"] is True
    assert hero["overlay_render_strategy"] == "verified_post_composite_only"
    assert hero["render_layers"] == ["base_scene", "verified_overlay"]
    assert "AGI or ESS" in hero["status_binding_rule"]
    assert "tusks" in " ".join(hero["required_troll_markers"]).lower()
    assert hero["world_marker_minimum"] == 2
    assert "metahuman presence" in " ".join(hero["world_marker_bucket"]).lower()
    assert "slim attribute rails" in " ".join(hero["overlay_geometry"]).lower()
    assert "illustrated cover-grade promo poster" in hero["critical_style_anchor"].lower()
    assert "visible operator relationship" in " ".join(hero["must_show_semantic_anchors"]).lower()
    assert readme["visual_density_profile"] == "first_contact_hero"
    assert readme["section_order"][:4] == ["pitch", "quick_nav", "current_posture", "hero"]
    assert readme["max_front_page_updates"] == 0
    assert horizons["visual_density_profile"] == "page_index"
    assert horizons["required_overlay_density"] == "medium"
    assert horizons["required_overlay_mode"] == "ambient_diegetic"
    assert "lane arcs" in " ".join(horizons["overlay_geometry"]).lower()
    assert horizons["overlay_render_strategy"] == "verified_post_composite_optional"
    assert "branching futures" in " ".join(horizons["must_show_semantic_anchors"]).lower()
    assert forge["visual_density_profile"] == "flagship_horizon"
    assert forge["required_person_count"] == "duo_preferred"
    assert forge["required_overlay_mode"] == "forge_review_ar"
    assert forge["style_epoch_force_only"] is True
    assert forge["overlay_render_strategy"] == "verified_post_composite_only"
    assert forge["render_layers"] == ["base_scene", "verified_overlay"]
    assert "approval state" in " ".join(forge["overlay_priority_order"]).lower()
    assert "reviewer" in " ".join(forge["must_show_semantic_anchors"]).lower()


def test_critical_asset_contracts_returns_three_targeted_rerun_profiles() -> None:
    canon = _load_module()

    contracts = canon.critical_asset_contracts()

    assert set(contracts) == {
        "assets/hero/chummer6-hero.png",
        "assets/pages/horizons-index.png",
        "assets/horizons/karma-forge.png",
    }
    assert contracts["assets/hero/chummer6-hero.png"]["flash_level"] == "bold"
