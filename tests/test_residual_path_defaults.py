from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = (
    "check_property_repo_isolation.py",
    "check_property_security_posture.py",
    "render_magicfit_property_flythrough.py",
    "materialize_next90_m129_ea_participation_followthrough_packets.py",
    "verify_next90_m129_ea_participation_followthrough_packets.py",
    "verify_design_mirror_bundle.py",
    "chummer_request_audit_dry_run.py",
)


def _rendered() -> str:
    return "\n".join((ROOT / "scripts" / name).read_text(encoding="utf-8") for name in SCRIPTS)


def test_residual_path_defaults_are_env_or_repo_local() -> None:
    rendered = _rendered()

    assert "EA_CHUMMER_CROSS_REPO_COMPLETION_ROOT" in rendered
    assert "EA_FLEET_COMPLETION_ROOT" in rendered
    assert "CHUMMER6_DESIGN_PRODUCT_ROOT" in rendered
    assert "CHUMMER_REQUEST_AUDIT_COMPLETION_DIR" in rendered
    assert "PROPERTYQUARRY_ROOT" in rendered
    assert "EA_MAGICFIT_ENV_FILE" in rendered
    assert 'ROOT / ".codex-design" / "product"' in rendered
    assert 'ROOT / "ea" / "_completion"' in rendered


def test_residual_scripts_do_not_default_to_old_host_paths() -> None:
    rendered = _rendered()

    assert "/docker/" + "chummercomplete" not in rendered
    assert "/docker/" + "fleet" not in rendered
    assert "/docker/" + "EA/" not in rendered
    assert "/docker/" + "property" not in rendered
    assert "/mnt/" + "onedrive" not in rendered
    assert "/mnt/" + "pcloud" not in rendered
