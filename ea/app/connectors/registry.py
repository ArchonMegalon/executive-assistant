from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.net.egress_guard import evaluate_connector_url


@dataclass(frozen=True)
class ConnectorContract:
    key: str
    display_name: str
    supports_discover: bool = True
    supports_authorize: bool = True
    supports_test: bool = True
    supports_preview: bool = True
    supports_initial_sync: bool = True
    supports_delta_sync: bool = True


CONNECTOR_REGISTRY: dict[str, ConnectorContract] = {
    "paperless": ConnectorContract(key="paperless", display_name="Paperless"),
    "immich": ConnectorContract(key="immich", display_name="Immich"),
    "onedrive_folder": ConnectorContract(key="onedrive_folder", display_name="OneDrive Folder"),
}


def connector_or_raise(connector_type: str) -> ConnectorContract:
    key = (connector_type or "").strip().lower()
    if key not in CONNECTOR_REGISTRY:
        raise ValueError(f"unknown_connector_type:{connector_type}")
    return CONNECTOR_REGISTRY[key]


def test_connector_endpoint(
    *,
    connector_type: str,
    endpoint_url: str,
    network_mode: str = "hosted",
    allow_private_targets: bool = False,
    allow_metadata_targets: bool = False,
) -> dict[str, Any]:
    contract = connector_or_raise(connector_type)
    decision = evaluate_connector_url(
        endpoint_url,
        network_mode=network_mode,
        allow_private_targets=allow_private_targets,
        allow_metadata_targets=allow_metadata_targets,
    )
    return {
        "connector": contract.key,
        "network_mode": network_mode,
        "ok": decision.allowed,
        "reason": decision.reason,
        "resolved_ips": list(decision.resolved_ips),
    }

