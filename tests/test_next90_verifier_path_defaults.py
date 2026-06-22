from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = (
    "verify_next90_m113_operator_safe_packets.py",
    "verify_next90_m118_ea_organizer_packets.py",
    "verify_next90_m135_ea_closure_coverage.py",
)
M141_M143_SCRIPTS = (
    "materialize_next90_m141_ea_route_local_screenshot_packs.py",
    "verify_next90_m141_ea_route_local_screenshot_packs.py",
    "materialize_next90_m142_ea_family_local_screenshot_and_interaction_packs.py",
    "verify_next90_m142_ea_family_local_screenshot_and_interaction_packs.py",
    "materialize_next90_m143_ea_route_specific_compare_packs.py",
    "verify_next90_m143_ea_route_specific_compare_packs.py",
)


def _source(name: str) -> str:
    return (ROOT / "scripts" / name).read_text(encoding="utf-8")


def test_next90_verifier_paths_are_env_driven_and_default_to_local_design_mirror() -> None:
    rendered = "\n".join(_source(name) for name in SCRIPTS)

    assert 'os.environ.get("CHUMMER6_DESIGN_PRODUCT_ROOT") or ROOT / ".codex-design/product"' in rendered
    assert 'os.environ.get("CHUMMER6_DESIGN_PRODUCT_ROOT") or REPO_ROOT / ".codex-design/product"' in rendered
    assert "EA_NEXT90_QUEUE_STAGING_PATH" in rendered
    assert "EA_NEXT90_DESIGN_QUEUE_STAGING_PATH" in rendered
    assert "EA_NEXT90_SUCCESSOR_REGISTRY_PATH" in rendered
    assert 'DESIGN_PRODUCT_ROOT / "NEXT_90_DAY_QUEUE_STAGING.generated.yaml"' in rendered
    assert 'DESIGN_PRODUCT_ROOT / "NEXT_90_DAY_PRODUCT_ADVANCE_REGISTRY.yaml"' in rendered


def test_next90_verifier_sources_do_not_default_to_external_chummer_paths() -> None:
    rendered = "\n".join((ROOT / "scripts" / name).read_text(encoding="utf-8") for name in SCRIPTS)
    external_root = "/docker/" + "chummercomplete"
    fleet_queue_root = "/docker/" + "fleet/.codex-studio"

    assert external_root not in rendered
    assert fleet_queue_root not in rendered


def test_next90_m141_to_m143_paths_are_env_driven_and_repo_local_by_default() -> None:
    rendered = "\n".join(_source(name) for name in M141_M143_SCRIPTS)
    external_root = "/docker/" + "chummercomplete"
    fleet_root = "/docker/" + "fleet"
    old_local_literal = "/docker/" + "EA/.codex-design"

    assert "CHUMMER6_DESIGN_PRODUCT_ROOT" in rendered
    assert "EA_CHUMMER_CROSS_REPO_COMPLETION_ROOT" in rendered
    assert "EA_FLEET_COMPLETION_ROOT" in rendered
    assert "EA_NEXT90_QUEUE_STAGING_PATH" in rendered
    assert "EA_NEXT90_SUCCESSOR_REGISTRY_PATH" in rendered
    assert 'ROOT / ".codex-design" / "product"' in rendered
    assert external_root not in rendered
    assert fleet_root not in rendered
    assert old_local_literal not in rendered
