from __future__ import annotations

import os
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

REPO_ROOT = Path(__file__).resolve().parents[1]


def _client() -> TestClient:
    os.environ["EA_STORAGE_BACKEND"] = "memory"
    os.environ.pop("EA_LEDGER_BACKEND", None)
    os.environ["EA_API_TOKEN"] = ""
    from app.api.app import create_app

    client = TestClient(create_app())
    client.headers.update({"X-EA-Principal-ID": "exec-1"})
    return client


def test_memory_router_keeps_split_subrouters_mounted_under_v1_memory() -> None:
    client = _client()
    route_paths = {route.path for route in client.app.routes}

    expected_paths = {
        "/v1/memory/candidates",
        "/v1/memory/items/{item_id}",
        "/v1/memory/entities",
        "/v1/memory/relationships/{relationship_id}",
        "/v1/memory/commitments",
        "/v1/memory/follow-up-rules/{rule_id}",
        "/v1/memory/communication-policies",
        "/v1/memory/stakeholders/{stakeholder_id}",
        "/v1/memory/authority-bindings",
        "/v1/memory/delivery-preferences/{preference_id}",
        "/v1/memory/interruption-budgets/{budget_id}",
    }

    assert expected_paths <= route_paths


def test_memory_commitment_schema_name_does_not_change_product_api_contracts() -> None:
    document = _client().app.openapi()
    schemas = document["components"]["schemas"]

    assert "CommitmentOut" in schemas
    assert "MemoryCommitmentOut" in schemas
    assert not {
        name
        for name in schemas
        if name.endswith("CommitmentOut")
        and name not in {"CommitmentOut", "MemoryCommitmentOut"}
    }
    assert schemas["PersonDetailOut"]["properties"]["commitments"]["items"] == {
        "$ref": "#/components/schemas/CommitmentOut"
    }

    product_responses = {
        ("post", "/app/api/commitments"),
        ("post", "/app/api/commitments/candidates/{candidate_id}/accept"),
        ("get", "/app/api/commitments/{commitment_ref}"),
        ("post", "/app/api/commitments/{commitment_ref}/resolve"),
    }
    for method, path in product_responses:
        response_schema = document["paths"][path][method]["responses"]["200"][
            "content"
        ]["application/json"]["schema"]
        assert response_schema == {"$ref": "#/components/schemas/CommitmentOut"}

    product_commitment_list = document["paths"]["/app/api/commitments"]["get"][
        "responses"
    ]["200"]["content"]["application/json"]["schema"]
    assert product_commitment_list["items"] == {
        "$ref": "#/components/schemas/CommitmentOut"
    }

    for method, path in {
        ("post", "/app/api/people/{person_id}/correct"),
        ("get", "/app/api/people/{person_id}/detail"),
    }:
        response_schema = document["paths"][path][method]["responses"]["200"][
            "content"
        ]["application/json"]["schema"]
        assert response_schema == {"$ref": "#/components/schemas/PersonDetailOut"}

    memory_responses = {
        ("post", "/v1/memory/commitments"),
        ("get", "/v1/memory/commitments/{commitment_id}"),
    }
    for method, path in memory_responses:
        response_schema = document["paths"][path][method]["responses"]["200"][
            "content"
        ]["application/json"]["schema"]
        assert response_schema == {
            "$ref": "#/components/schemas/MemoryCommitmentOut"
        }

    memory_commitment_list = document["paths"]["/v1/memory/commitments"]["get"][
        "responses"
    ]["200"]["content"]["application/json"]["schema"]
    assert memory_commitment_list["items"] == {
        "$ref": "#/components/schemas/MemoryCommitmentOut"
    }


def test_memory_router_module_is_a_thin_aggregator() -> None:
    source = (REPO_ROOT / "ea/app/api/routes/memory.py").read_text(encoding="utf-8")

    assert "include_router(memory_candidates_router)" in source
    assert "include_router(memory_graph_router)" in source
    assert "include_router(memory_operations_router)" in source
    assert "include_router(memory_governance_router)" in source
    assert "@router.post(" not in source
    assert "@router.get(" not in source


def test_memory_operations_module_is_a_thin_aggregator() -> None:
    source = (REPO_ROOT / "ea/app/api/routes/memory_operations.py").read_text(encoding="utf-8")

    assert "include_router(memory_commitments_router)" in source
    assert "include_router(memory_followups_router)" in source
    assert "include_router(memory_windows_router)" in source
    assert "@router.post(" not in source
    assert "@router.get(" not in source
