from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FILES = (
    "Makefile",
    "scripts/bootstrap_telegram_bot.py",
    "scripts/ea_responses_proxy.py",
    "scripts/codexea",
    "scripts/release_v115_rag.sh",
    "scripts/smoke_postgres.sh",
    "scripts/verify_release_assets.sh",
)


def _rendered() -> str:
    return "\n".join((ROOT / name).read_text(encoding="utf-8") for name in FILES)


def test_helper_defaults_are_repo_local_or_env_driven() -> None:
    rendered = _rendered()

    assert "EA_ONEDRIVE_ATTACHMENTS_FALLBACK_HOST_PATH" in rendered
    assert "CODEXEA_FLEET_ROOT" in rendered
    assert "EA_FLEET_JOURNEY_GATES_PATH" in rendered
    assert "Path(__file__).resolve().parents[1]" in rendered


def test_helper_defaults_do_not_point_at_old_host_roots() -> None:
    rendered = _rendered()

    assert "/docker/" + "fleet" not in rendered
    assert "/docker/" + "property" not in rendered
    assert "/docker/" + "EA/" not in rendered
    assert "/mnt/" + "pcloud" not in rendered
