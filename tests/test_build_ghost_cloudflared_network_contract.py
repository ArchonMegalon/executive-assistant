from __future__ import annotations

from functools import lru_cache
import json
import os
from pathlib import Path
import shutil
import subprocess

import yaml


ROOT = Path(__file__).resolve().parents[1]
COMPOSE_PATH = ROOT / "docker-compose.cloudflared.yml"
DEDICATED_NETWORK_KEY = "build_ghost_cloudflare_ingress"
DEDICATED_NETWORK_NAME = "chummer-build-ghost-cloudflare-ingress"


def _overlay_compose() -> dict[str, object]:
    parsed = yaml.safe_load(COMPOSE_PATH.read_text(encoding="utf-8"))
    assert isinstance(parsed, dict)
    return parsed


@lru_cache(maxsize=1)
def _rendered_compose() -> dict[str, object]:
    docker = shutil.which("docker")
    assert docker is not None, "docker CLI is required for the Compose contract"
    completed = subprocess.run(
        [
            docker,
            "compose",
            "--env-file",
            "/dev/null",
            "-f",
            "docker-compose.yml",
            "-f",
            "docker-compose.cloudflared.yml",
            "config",
            "--no-env-resolution",
            "--format",
            "json",
        ],
        cwd=ROOT,
        env={
            "COMPOSE_PROJECT_NAME": "ea-build-ghost-network-contract",
            "EA_CF_TUNNEL_TOKEN": "contract-sentinel",
            "HOME": "/tmp",
            "LANG": "C.UTF-8",
            "LC_ALL": "C.UTF-8",
            "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
            "POSTGRES_PASSWORD": "contract-sentinel",
        },
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
    parsed = json.loads(completed.stdout)
    assert isinstance(parsed, dict)
    return parsed


def test_cloudflared_alone_joins_the_dedicated_build_ghost_ingress() -> None:
    compose = _rendered_compose()
    services = compose["services"]
    assert isinstance(services, dict)

    cloudflared = services["ea-cloudflared"]
    assert isinstance(cloudflared, dict)
    assert cloudflared["container_name"] == "externalbrain-cloudflared"
    assert cloudflared["networks"] == {
        DEDICATED_NETWORK_KEY: {},
        "public_ingress": {"ipv4_address": "172.31.254.2"},
    }
    assert cloudflared.get("ports") is None
    assert cloudflared.get("network_mode") is None
    assert cloudflared.get("extra_hosts") is None

    dedicated_members = []
    for service_name, service in services.items():
        assert isinstance(service, dict)
        if DEDICATED_NETWORK_KEY in (service.get("networks") or {}):
            dedicated_members.append(service_name)
    assert dedicated_members == ["ea-cloudflared"]


def test_build_ghost_ingress_network_is_exact_external_authority() -> None:
    overlay = _overlay_compose()
    overlay_networks = overlay["networks"]
    assert isinstance(overlay_networks, dict)
    assert overlay_networks[DEDICATED_NETWORK_KEY] == {
        "external": True,
        "name": DEDICATED_NETWORK_NAME,
    }

    compose = _rendered_compose()
    networks = compose["networks"]
    assert isinstance(networks, dict)

    dedicated = networks[DEDICATED_NETWORK_KEY]
    assert isinstance(dedicated, dict)
    assert dedicated["external"] is True
    assert dedicated["name"] == DEDICATED_NETWORK_NAME
    assert set(dedicated) <= {"external", "ipam", "name"}

    public_ingress = networks["public_ingress"]
    assert isinstance(public_ingress, dict)
    assert public_ingress["name"] == "ea_public_ingress"
    assert public_ingress["ipam"] == {
        "config": [
            {
                "gateway": "172.31.254.1",
                "subnet": "172.31.254.0/29",
            }
        ]
    }


def test_cloudflared_overlay_does_not_bridge_private_services() -> None:
    text = COMPOSE_PATH.read_text(encoding="utf-8")

    assert "build-ghost-private" not in text
    assert "chummer-build-ghost-presentation" not in text
    assert "chummer-build-ghost-ai" not in text
    assert "build-ghost-private-edge" not in text
    assert "ports:" not in text
    assert "network_mode:" not in text
