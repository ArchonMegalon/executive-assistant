from __future__ import annotations

import os
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient


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


def test_memory_router_module_is_a_thin_aggregator() -> None:
    source = Path("ea/app/api/routes/memory.py").read_text(encoding="utf-8")

    assert "include_router(memory_candidates_router)" in source
    assert "include_router(memory_graph_router)" in source
    assert "include_router(memory_operations_router)" in source
    assert "include_router(memory_governance_router)" in source
    assert "@router.post(" not in source
    assert "@router.get(" not in source
