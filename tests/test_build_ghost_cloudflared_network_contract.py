from __future__ import annotations

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
COMPOSE_PATH = ROOT / "docker-compose.cloudflared.yml"
DEDICATED_NETWORK_KEY = "build_ghost_cloudflare_ingress"
DEDICATED_NETWORK_NAME = "chummer-build-ghost-cloudflare-ingress"


def _compose() -> dict[str, object]:
    parsed = yaml.safe_load(COMPOSE_PATH.read_text(encoding="utf-8"))
    assert isinstance(parsed, dict)
    return parsed


def test_cloudflared_alone_joins_the_dedicated_build_ghost_ingress() -> None:
    compose = _compose()
    services = compose["services"]
    assert isinstance(services, dict)

    cloudflared = services["ea-cloudflared"]
    assert isinstance(cloudflared, dict)
    assert cloudflared["container_name"] == "externalbrain-cloudflared"
    assert set(cloudflared["networks"]) == {
        "public_ingress",
        DEDICATED_NETWORK_KEY,
    }

    for service_name, service in services.items():
        if service_name == "ea-cloudflared":
            continue
        assert isinstance(service, dict)
        assert DEDICATED_NETWORK_KEY not in (service.get("networks") or {})


def test_build_ghost_ingress_network_is_exact_external_authority() -> None:
    compose = _compose()
    networks = compose["networks"]
    assert isinstance(networks, dict)

    dedicated = networks[DEDICATED_NETWORK_KEY]
    assert dedicated == {
        "external": True,
        "name": DEDICATED_NETWORK_NAME,
    }


def test_cloudflared_overlay_does_not_bridge_private_services() -> None:
    text = COMPOSE_PATH.read_text(encoding="utf-8")

    assert "build-ghost-private" not in text
    assert "chummer-build-ghost-presentation" not in text
    assert "chummer-build-ghost-ai" not in text
    assert "build-ghost-private-edge" not in text
    assert "ports:" not in text
