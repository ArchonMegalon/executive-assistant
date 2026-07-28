from __future__ import annotations

import pytest

from scripts.deploy_ea_memorial import DeployError
from scripts.quarantine_ea_memorial_api_normalization_recovery import (
    _environment,
    _rendered_environment,
    _without_dynamic_memorial_get_body,
    _without_network_macs,
)


def test_environment_rejects_duplicates() -> None:
    with pytest.raises(
        DeployError,
        match="test_environment_invalid",
    ):
        _environment(
            ["A=one", "A=two"],
            reason="test_environment_invalid",
        )


def test_rendered_environment_merges_image_defaults_and_service_overrides() -> None:
    result = _rendered_environment(
        {
            "environment": {
                "IMAGE_ONLY_OVERRIDE": "service",
                "SERVICE_ONLY": "present",
            }
        },
        {
            "Config": {
                "Env": [
                    "IMAGE_ONLY=present",
                    "IMAGE_ONLY_OVERRIDE=image",
                ]
            }
        },
    )

    assert result == {
        "IMAGE_ONLY": "present",
        "IMAGE_ONLY_OVERRIDE": "service",
        "SERVICE_ONLY": "present",
    }


def test_without_network_macs_changes_only_ephemeral_mac_fields() -> None:
    source = {
        "network_mode": "ea_default",
        "networks": {
            "ea_default": {
                "ip_address": "172.22.0.5",
                "mac_address": "aa:bb:cc:dd:ee:ff",
            },
            "ea_public_ingress": {
                "ip_address": "172.31.254.3",
                "mac_address": "11:22:33:44:55:66",
            },
        },
    }

    result = _without_network_macs(source)

    assert result == {
        "network_mode": "ea_default",
        "networks": {
            "ea_default": {"ip_address": "172.22.0.5"},
            "ea_public_ingress": {"ip_address": "172.31.254.3"},
        },
    }
    assert source["networks"]["ea_default"]["mac_address"] == (
        "aa:bb:cc:dd:ee:ff"
    )


def test_without_dynamic_memorial_get_body_preserves_other_edge_evidence() -> None:
    source = {
        "origin": "https://myexternalbrain.com",
        "probes": {
            "memorial_get": {
                "status": 200,
                "body_sha256": "a" * 64,
            },
            "memorial_head": {
                "status": 200,
                "body_sha256": "b" * 64,
            },
        },
    }

    result = _without_dynamic_memorial_get_body(source)

    assert result["probes"]["memorial_get"] == {"status": 200}
    assert result["probes"]["memorial_head"]["body_sha256"] == "b" * 64
    assert source["probes"]["memorial_get"]["body_sha256"] == "a" * 64
