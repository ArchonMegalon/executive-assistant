from __future__ import annotations

import json

from tests.smoke_runtime_api_support import build_client as _client


def test_health_release_authority_is_public_and_returns_gate_payloads() -> None:
    client = _client(storage_backend="memory", authenticated=False, principal_id="")
    response = client.get("/health/release-authority")

    assert response.status_code == 200
    body = response.json()
    assert body["release_authority"]["state"] in {"clear", "watch", "missing"}
    assert body["release_authority"]["manifest_path"].endswith("release_manifest.generated.json")
    assert "deploy_context_path" in body["release_authority"]
    assert body["release_authority_gate"]["contract_name"] == "ea.release_authority_gate.v1"
    assert body["release_authority_gate"]["status"] in {"pass", "fail", "error"}
    assert body["deploy_context_gate"]["contract_name"] == "ea.deploy_context_gate.v1"
    assert body["deploy_context_gate"]["status"] in {"pass", "fail", "error"}
    assert body["runtime_supply_chain"]["state"] in {"clear", "watch"}
    assert body["runtime_supply_chain_gate"]["contract_name"] == "ea.runtime_supply_chain.v1"
    assert dict(body["release_authority"].get("deploy_context_gate") or {}) == body["deploy_context_gate"]
    assert dict(body["release_authority"].get("gate") or {}) == body["release_authority_gate"]
    assert dict(body["runtime_supply_chain"].get("gate") or {}) == body["runtime_supply_chain_gate"]


def test_health_release_authority_external_projection_recursively_redacts_topology() -> None:
    client = _client(storage_backend="memory", authenticated=False, principal_id="")

    response = client.get(
        "/health/release-authority",
        headers={"host": "status.example.invalid"},
    )

    assert response.status_code == 200
    body = response.json()
    assert set(body["release_authority"]) == {
        "state",
        "authority_posture",
        "source",
        "gate",
        "deploy_context_gate",
    }
    for key in ("release_authority_gate", "deploy_context_gate", "runtime_supply_chain_gate"):
        assert set(body[key]) <= {
            "contract_name",
            "status",
            "issue_count",
            "authority_posture",
        }
        assert isinstance(body[key]["issue_count"], int)
    serialized = json.dumps(body, sort_keys=True).lower()
    for forbidden in (
        "manifest_path",
        "deploy_context_path",
        "project_modes_path",
        "git_remote_origin",
        "compose_services",
        "dockerfiles",
        "/docker/",
        "/home/",
        "/app/",
    ):
        assert forbidden not in serialized
