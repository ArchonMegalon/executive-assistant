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
    }
    assert "ghostwire" not in catalog
    assert "knowledge-fabric" not in catalog
    assert "local-co-processor" not in catalog
    assert "rule-x-ray" not in catalog
    assert "heat-web" not in catalog
    assert "## Mission Market" in catalog["black-ledger"]["public_body"]
    assert "## Rule Environment" in catalog["karma-forge"]["public_body"]
    assert "## Canon Links" not in catalog["black-ledger"]["public_body"]
    assert "## Canon Links" not in catalog["karma-forge"]["public_body"]
    assert "products/chummer/" not in catalog["black-ledger"]["public_body"]
    assert "products/chummer/" not in catalog["karma-forge"]["public_body"]
    assert "C0 - campaign, run, and Hub-owned receipt boundaries" in catalog["black-ledger"]["foundations"]
    assert "D2 - restore-safe sync, package portability, and missing-package warnings" in catalog["karma-forge"]["foundations"]


def test_load_faq_and_help_canon_track_public_question_sets() -> None:
    canon = _load_module()

    faq = canon.load_faq_canon()
    help_copy = canon.load_help_canon()
    release = canon.load_release_experience_canon()
    trust = canon.load_trust_content_canon()

    assert "participation_and_preview" in faq
    questions = {entry["question"] for entry in faq["participation_and_preview"]["entries"]}
    assert "What is guided contribution?" in questions
    assert "Will guided-preview access open wider later?" in questions
    assert "the cheap baseline remains the default path" in help_copy["privacy_and_review_safety"]
    assert canon.design_root() == ROOT / ".codex-design" / "product"
    assert "one clear public download" in str(release["release_notes_summary"]).lower()
    trust_pages = {str(page.get("id") or ""): page for page in trust.get("trust_pages") or [] if isinstance(page, dict)}
    help_page = dict(trust_pages["help"])
    assert "downloads and setup stay clear" in [str(value).lower() for value in help_page.get("summary_points") or []]
    faq_pages = [page for page in trust.get("faq_pages") or [] if isinstance(page, dict)]
    faq_questions = {
        str(entry.get("question") or "")
        for page in faq_pages
        for section in page.get("sections") or []
        if isinstance(section, dict)
        for entry in section.get("entries") or []
        if isinstance(entry, dict)
    }
    assert "Do I need an account to download the current preview?" in faq_questions


def test_asset_visual_profile_derives_critical_first_contact_requirements() -> None:
    canon = _load_module()

    hero = canon.asset_visual_profile("assets/hero/chummer6-hero.png")
    readme = canon.asset_visual_profile("README.md")
    horizons = canon.asset_visual_profile("assets/pages/horizons-index.png")
    forge = canon.asset_visual_profile("assets/horizons/karma-forge.png")

    assert hero["visual_density_profile"] == "first_contact_hero"
    assert hero["required_person_count"] == "duo_or_team"
    assert hero["required_overlay_mode"] == "cyberarm_fit_diagnostic"
    assert hero["critical_style_overrides_shared_prompt_scaffold"] is True
    assert hero["style_epoch_force_only"] is True
    assert hero["overlay_render_strategy"] == "verified_post_composite_only"
    assert hero["render_layers"] == ["base_scene", "verified_overlay"]
    assert "NERVE SYNC" in hero["status_binding_rule"]
    assert "cyberarm" in hero["status_binding_rule"]
    assert "tusks" in " ".join(hero["required_troll_markers"]).lower()
    assert hero["world_marker_minimum"] == 4
    assert hero["environment_share_minimum"] == 0.58
    assert hero["subject_crop_maximum"] == 0.26
    assert hero["cast_readability_required"] is True
    assert hero["overlay_anchor_required"] is True
    assert "metahuman presence" in " ".join(hero["world_marker_bucket"]).lower()
    assert "paper lotus" in " ".join(hero["world_marker_bucket"]).lower()
    assert "megacorp" in " ".join(hero["world_marker_bucket"]).lower()
    assert "fit-status microcopy" in " ".join(hero["overlay_geometry"]).lower()
    assert "illustrated cover-grade promo poster" in hero["critical_style_anchor"].lower()
    assert "visible operator relationship" in " ".join(hero["must_show_semantic_anchors"]).lower()
    assert readme["visual_density_profile"] == "first_contact_hero"
    assert readme["section_order"][:4] == ["pitch", "quick_nav", "current_posture", "hero"]
    assert readme["max_front_page_updates"] == 0
    assert horizons["visual_density_profile"] == "page_index"
    assert horizons["required_overlay_density"] == "medium"
    assert horizons["required_overlay_mode"] == "ambient_diegetic"
    assert horizons["world_marker_minimum"] == 4
    assert horizons["environment_share_minimum"] == 0.72
    assert horizons["subject_crop_maximum"] == 0.18
    assert horizons["overlay_anchor_required"] is True
    assert "lane arcs" in " ".join(horizons["overlay_geometry"]).lower()
    assert horizons["overlay_render_strategy"] == "verified_post_composite_public"
    assert "none" not in horizons["allowed_overlay_modes"]
    assert "branching futures" in " ".join(horizons["must_show_semantic_anchors"]).lower()
    assert forge["visual_density_profile"] == "flagship_horizon"
    assert forge["required_person_count"] == "duo_preferred"
    assert forge["required_overlay_mode"] == "forge_review_ar"
    assert forge["style_epoch_force_only"] is True
    assert forge["overlay_render_strategy"] == "verified_post_composite_only"
    assert forge["render_layers"] == ["base_scene", "verified_overlay"]
    assert forge["world_marker_minimum"] == 4
    assert forge["environment_share_minimum"] == 0.60
    assert forge["apparatus_share_minimum"] == 0.52
    assert forge["subject_crop_maximum"] == 0.24
    assert forge["cast_readability_required"] is True
    assert forge["overlay_anchor_required"] is True
    assert "approval state" in " ".join(forge["overlay_priority_order"]).lower()
    assert "reviewer" in " ".join(forge["must_show_semantic_anchors"]).lower()


def test_asset_image_curation_tracks_editorial_cover_locks() -> None:
    canon = _load_module()

    ui = canon.asset_image_curation("assets/parts/ui.png")
    runsite = canon.asset_image_curation("assets/horizons/runsite.png")
    parts_index = canon.asset_image_curation("assets/pages/parts-index.png")

    assert ui["review_status"] == "editorial_cover"
    assert ui["embed_policy"] == "manual"
    assert ui["curation_locked"] is True
    assert Path(ui["source_path"]).exists()
    assert runsite["curation_locked"] is True
    assert Path(runsite["source_path"]).exists()
    assert parts_index["curation_locked"] is True
    assert Path(parts_index["source_path"]).exists()


def test_critical_asset_contracts_returns_three_targeted_rerun_profiles() -> None:
    canon = _load_module()

    contracts = canon.critical_asset_contracts()

    assert set(contracts) == {
        "assets/hero/chummer6-hero.png",
        "assets/pages/horizons-index.png",
        "assets/horizons/karma-forge.png",
    }
    assert contracts["assets/hero/chummer6-hero.png"]["flash_level"] == "bold"
