from __future__ import annotations

from datetime import datetime, timedelta, timezone
import os

import pytest
from fastapi.testclient import TestClient


def _client(*, principal_id: str) -> TestClient:
    os.environ["EA_STORAGE_BACKEND"] = "memory"
    os.environ.pop("EA_LEDGER_BACKEND", None)
    os.environ.pop("EA_DEFAULT_PRINCIPAL_ID", None)
    os.environ["EA_API_TOKEN"] = ""
    from app.api.app import create_app

    client = TestClient(create_app())
    client.headers.update({"X-EA-Principal-ID": principal_id})
    return client


def test_runtime_cognitive_load_and_proactive_horizon_visibility() -> None:
    client = _client(principal_id="exec-1")

    budget = client.post(
        "/v1/memory/interruption-budgets",
        json={
            "principal_id": "exec-1",
            "scope": "default",
            "window_kind": "daily",
            "budget_minutes": 120,
            "used_minutes": 0,
            "status": "active",
            "notes": "default budget",
        },
    )
    assert budget.status_code == 200

    decision = client.post(
        "/v1/memory/decision-windows",
        json={
            "principal_id": "exec-1",
            "title": "Board response decision",
            "context": "Choose timing",
            "closes_at": (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat(),
            "urgency": "high",
            "authority_required": "exec",
            "status": "open",
            "notes": "Needs decision today",
            "source_json": {"source": "manual"},
        },
    )
    assert decision.status_code == 200

    other_principal_decision = client.post(
        "/v1/memory/decision-windows",
        json={
            "principal_id": "exec-2",
            "title": "Other principal decision",
            "context": "Keep isolated",
            "closes_at": (datetime.now(timezone.utc) + timedelta(hours=3)).isoformat(),
            "urgency": "medium",
            "authority_required": "exec",
            "status": "open",
            "notes": "Should not bleed into exec-1 runtime scan",
            "source_json": {"source": "manual"},
        },
        headers={"X-EA-Principal-ID": "exec-2"},
    )
    assert other_principal_decision.status_code == 200

    load = client.get("/v1/runtime/cognitive-load")
    assert load.status_code == 200
    load_body = load.json()
    assert load_body["principal_id"] == "exec-1"
    assert load_body["state"]["messages_last_15m"] >= 0
    assert load_body["interruption_budget"]["budget_minutes"] == 120

    scan = client.get("/v1/runtime/proactive-horizon/scan")
    assert scan.status_code == 200
    scan_body = scan.json()
    assert scan_body["principal_id"] == "exec-1"
    assert scan_body["candidate_count"] >= 1
    assert all(row["principal_id"] == "exec-1" for row in scan_body["candidates"])

    filtered = client.get("/v1/runtime/proactive-horizon/scan", params={"principal_id": "exec-1"})
    assert filtered.status_code == 200
    filtered_body = filtered.json()
    assert filtered_body["principal_id"] == "exec-1"
    assert all(row["principal_id"] == "exec-1" for row in filtered_body["candidates"])

    launched = client.post("/v1/runtime/proactive-horizon/run", params={"principal_id": "exec-1"})
    assert launched.status_code == 200
    launched_body = launched.json()
    assert launched_body["principal_id"] == "exec-1"
    assert launched_body["launched_count"] >= 1


def test_runtime_lane_telemetry_endpoint_surfaces_codex_status(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _client(principal_id="exec-1")
    from app.api.routes import runtime as runtime_route

    monkeypatch.setattr(
        runtime_route.upstream,
        "codex_status_report",
        lambda window="1h": {
            "provider_config": {"default_profile": "easy", "default_lane": "fast"},
            "lane_telemetry": {"selected_window": {"lanes": {"fast": {"request_count": 2, "p50_latency_ms": 120}}}},
            "onemin_aggregate": {"current_pace_burn_credits_per_hour": 1200.0},
            "onemin_billing_aggregate": {"observed_usage_burn_credits_per_hour": 900.0},
            "fleet_burn": {"selected_window": {"provider_credits": {"onemin": 500}}},
            "avoided_credits": {"selected_window": {"easy_lane": {"avoided_credits": 300, "requests": 2}}},
        },
    )

    response = client.get("/v1/runtime/lanes/telemetry", params={"window": "24h"})
    assert response.status_code == 200
    body = response.json()
    assert body["window"] == "24h"
    assert body["provider_config"]["default_profile"] == "easy"
    assert body["lane_telemetry"]["selected_window"]["lanes"]["fast"]["p50_latency_ms"] == 120
    assert body["onemin_aggregate"]["current_pace_burn_credits_per_hour"] == 1200.0
    assert body["avoided_credits"]["selected_window"]["easy_lane"]["avoided_credits"] == 300
