from __future__ import annotations

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
BASE_COMPOSE = ROOT / "docker-compose.yml"
MEMORIAL_COMPOSE = ROOT / "docker-compose.memorial.yml"


def test_ea_public_tours_use_a_dedicated_myexternalbrain_volume() -> None:
    raw = BASE_COMPOSE.read_text(encoding="utf-8")
    payload = yaml.safe_load(raw)

    assert payload["volumes"]["ea_public_tours"] == {
        "external": True,
        "name": "ea_myexternalbrain_public_tours",
    }
    assert "property_propertyquarry_public_tours" not in raw
    assert "PROPERTYQUARRY_" not in raw

    mounted_services = {
        service_name
        for service_name, service in payload["services"].items()
        if "ea_public_tours:/data/public_property_tours"
        in service.get("volumes", [])
    }
    assert mounted_services == {"ea-api", "ea-responses-proxy", "ea-worker"}


def _retired_memorial_overlay_is_memorial_only_and_propertyquarry_env_free() -> None:
    raw = MEMORIAL_COMPOSE.read_text(encoding="utf-8")

    assert "- EA_DEPLOY_PRIMARY_MODE=MEMORIAL\n" in raw
    assert "- EA_DEPLOY_ENABLED_MODES=MEMORIAL\n" in raw
    assert "EA_DEPLOY_ENABLED_MODES=MEMORIAL,PROPERTY" not in raw
    assert "PROPERTYQUARRY_" not in raw
