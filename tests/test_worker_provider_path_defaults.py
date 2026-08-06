from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = (
    "avomap_flyover_worker.py",
    "booka_book_worker.py",
    "browseract_template_service_worker.py",
    "verify_avatar_presenter_provider.py",
    "verify_joggai_provider.py",
    "analyze_voicewave_workspace.py",
    "capture_vidboard_provider_receipts.py",
    "publish_browseract_ui_results.py",
    "publish_crezlo_property_tours.py",
    "publish_crezlo_public_tours.py",
    "run_crezlo_property_tour_batch.py",
    "materialize_weekly_product_pulse.py",
    "support_bundle.sh",
    "verify_magicfit_design_boundary.py",
    "browseract_bootstrap_manager.py",
    "attempt_unmixr_browseract_clone.py",
    "verify_flagship_release_readiness.py",
    "operator_summary.sh",
    "analyze_nonverbia_custom_project.py",
    "avatar_presenter_provider_check.py",
    "newsroom_provider_inventory_check.py",
    "export_browseract_ui_service_templates.py",
    "ensure_fastestvpn_proxy_pool.sh",
    "backfill_public_tour_research_snapshots.py",
    "mootion_movie_worker.py",
    "verify_pocket_audio_archive.py",
    "generate_browseract_content_templates.py",
)
def _rendered() -> str:
    return "\n".join((ROOT / "scripts" / name).read_text(encoding="utf-8") for name in SCRIPTS)


def test_worker_and_provider_defaults_are_repo_local_or_env_driven() -> None:
    rendered = _rendered()

    assert "EA_UI_SERVICE_WORKER_OUTPUT_ROOT" in rendered
    assert "EA_UI_SERVICE_SHARED_TEMP_ROOT" in rendered
    assert "EA_AVATAR_PRESENTER_PROVIDER_OUT_DIR" in rendered
    assert "EA_VOICEWAVE_PROVIDER_OUT_DIR" in rendered
    assert "EA_FLEET_JOURNEY_GATES_PATH" in rendered
    assert "CHUMMER_DESIGN_ROOT" in rendered
    assert "CHUMMER_MEDIA_FACTORY_ROOT" in rendered
    assert "BROWSERACT_BOOTSTRAP_STATE_DIR" in rendered
    assert "EA_UNMIXR_PROVIDER_OUT_DIR" in rendered
    assert "EA_NEWSROOM_PROVIDER_OUTPUT" in rendered
    assert "PROPERTYQUARRY_ROOT" in rendered
    assert "FASTESTVPN_CONFIG_ROOT" in rendered
    assert "EA_POCKET_AUDIO_ARCHIVE_ROOT" in rendered
    assert "EA_BROWSERACT_CONTENT_TEMPLATE_OUTPUT_DIR" in rendered
    assert "EA_DEFAULT_PRINCIPAL_ID" in rendered
    assert 'X-EA-Principal-ID": "exec-1"' not in rendered
    assert 'ROOT / "ea" / "_completion"' in rendered or 'root / "ea/_completion' in rendered


def test_worker_and_provider_defaults_do_not_point_at_old_host_roots() -> None:
    rendered = _rendered()

    assert "/docker/" + "fleet" not in rendered
    assert "/docker/" + "chummercomplete" not in rendered
    assert "/docker/" + "property" not in rendered
    assert "/mnt/" + "pcloud" not in rendered
