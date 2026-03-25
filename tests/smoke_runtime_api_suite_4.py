from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

from tests.smoke_runtime_api_support import build_client as _client
from tests.smoke_runtime_api_support import build_headers as _headers


def test_memory_follow_up_rules_principal_scope_flow() -> None:
    client = _client(storage_backend="memory")

    created = client.post(
        "/v1/memory/follow-up-rules",
        json={
            "principal_id": "exec-1",
            "name": "Board reminder escalation",
            "trigger_kind": "deadline_risk",
            "channel_scope": ["email", "slack"],
            "delay_minutes": 120,
            "max_attempts": 3,
            "escalation_policy": "notify_exec",
            "conditions_json": {"priority": "high"},
            "action_json": {"action": "draft_follow_up"},
            "status": "active",
            "notes": "Escalate if follow-up is late",
        },
    )
    assert created.status_code == 200
    rule_id = created.json()["rule_id"]

    listed = client.get("/v1/memory/follow-up-rules", params={"principal_id": "exec-1", "limit": 10})
    assert listed.status_code == 200
    assert any(row["rule_id"] == rule_id for row in listed.json())

    fetched = client.get(f"/v1/memory/follow-up-rules/{rule_id}", params={"principal_id": "exec-1"})
    assert fetched.status_code == 200
    assert fetched.json()["name"] == "Board reminder escalation"

    wrong_scope = client.get(f"/v1/memory/follow-up-rules/{rule_id}", params={"principal_id": "exec-2"})
    assert wrong_scope.status_code == 403
    assert wrong_scope.json()["error"]["code"] == "principal_scope_mismatch"


def test_memory_interruption_budgets_principal_scope_flow() -> None:
    client = _client(storage_backend="memory")

    created = client.post(
        "/v1/memory/interruption-budgets",
        json={
            "principal_id": "exec-1",
            "scope": "workday",
            "window_kind": "daily",
            "budget_minutes": 120,
            "used_minutes": 30,
            "reset_at": "2026-03-07T00:00:00+00:00",
            "quiet_hours_json": {"start": "22:00", "end": "07:00"},
            "status": "active",
            "notes": "Keep non-critical interruptions bounded",
        },
    )
    assert created.status_code == 200
    budget_id = created.json()["budget_id"]

    listed = client.get("/v1/memory/interruption-budgets", params={"principal_id": "exec-1", "limit": 10})
    assert listed.status_code == 200
    assert any(row["budget_id"] == budget_id for row in listed.json())

    fetched = client.get(f"/v1/memory/interruption-budgets/{budget_id}", params={"principal_id": "exec-1"})
    assert fetched.status_code == 200
    assert fetched.json()["scope"] == "workday"

    wrong_scope = client.get(f"/v1/memory/interruption-budgets/{budget_id}", params={"principal_id": "exec-2"})
    assert wrong_scope.status_code == 403
    assert wrong_scope.json()["error"]["code"] == "principal_scope_mismatch"


def test_memory_deadline_windows_principal_scope_flow() -> None:
    client = _client(storage_backend="memory")

    created = client.post(
        "/v1/memory/deadline-windows",
        json={
            "principal_id": "exec-1",
            "title": "Board prep delivery window",
            "start_at": "2026-03-07T08:30:00+00:00",
            "end_at": "2026-03-07T10:00:00+00:00",
            "status": "open",
            "priority": "high",
            "notes": "Draft must be ready before board sync",
            "source_json": {"source": "manual"},
        },
    )
    assert created.status_code == 200
    window_id = created.json()["window_id"]

    listed = client.get("/v1/memory/deadline-windows", params={"principal_id": "exec-1", "limit": 10})
    assert listed.status_code == 200
    assert any(row["window_id"] == window_id for row in listed.json())

    fetched = client.get(f"/v1/memory/deadline-windows/{window_id}", params={"principal_id": "exec-1"})
    assert fetched.status_code == 200
    assert fetched.json()["title"] == "Board prep delivery window"

    wrong_scope = client.get(f"/v1/memory/deadline-windows/{window_id}", params={"principal_id": "exec-2"})
    assert wrong_scope.status_code == 403
    assert wrong_scope.json()["error"]["code"] == "principal_scope_mismatch"


def test_memory_stakeholders_principal_scope_flow() -> None:
    client = _client(storage_backend="memory")

    created = client.post(
        "/v1/memory/stakeholders",
        json={
            "principal_id": "exec-1",
            "display_name": "Sam Stakeholder",
            "channel_ref": "email:sam@example.com",
            "authority_level": "approver",
            "importance": "high",
            "response_cadence": "fast",
            "tone_pref": "diplomatic",
            "sensitivity": "confidential",
            "escalation_policy": "notify_exec",
            "open_loops_json": {"board_follow_up": "open"},
            "friction_points_json": {"scheduling": "tight"},
            "last_interaction_at": "2026-03-06T15:30:00+00:00",
            "status": "active",
            "notes": "Needs concise summaries",
        },
    )
    assert created.status_code == 200
    stakeholder_id = created.json()["stakeholder_id"]

    listed = client.get("/v1/memory/stakeholders", params={"principal_id": "exec-1", "limit": 10})
    assert listed.status_code == 200
    assert any(row["stakeholder_id"] == stakeholder_id for row in listed.json())

    fetched = client.get(f"/v1/memory/stakeholders/{stakeholder_id}", params={"principal_id": "exec-1"})
    assert fetched.status_code == 200
    assert fetched.json()["display_name"] == "Sam Stakeholder"

    wrong_scope = client.get(f"/v1/memory/stakeholders/{stakeholder_id}", params={"principal_id": "exec-2"})
    assert wrong_scope.status_code == 403
    assert wrong_scope.json()["error"]["code"] == "principal_scope_mismatch"


def test_memory_decision_windows_principal_scope_flow() -> None:
    client = _client(storage_backend="memory")

    created = client.post(
        "/v1/memory/decision-windows",
        json={
            "principal_id": "exec-1",
            "title": "Board response decision",
            "context": "Choose timing and channel for reply",
            "opens_at": "2026-03-06T08:00:00+00:00",
            "closes_at": "2026-03-06T12:00:00+00:00",
            "urgency": "high",
            "authority_required": "exec",
            "status": "open",
            "notes": "Needs decision before board prep",
            "source_json": {"source": "manual"},
        },
    )
    assert created.status_code == 200
    decision_window_id = created.json()["decision_window_id"]

    listed = client.get("/v1/memory/decision-windows", params={"principal_id": "exec-1", "limit": 10})
    assert listed.status_code == 200
    assert any(row["decision_window_id"] == decision_window_id for row in listed.json())

    fetched = client.get(
        f"/v1/memory/decision-windows/{decision_window_id}",
        params={"principal_id": "exec-1"},
    )
    assert fetched.status_code == 200
    assert fetched.json()["title"] == "Board response decision"

    wrong_scope = client.get(
        f"/v1/memory/decision-windows/{decision_window_id}",
        params={"principal_id": "exec-2"},
    )
    assert wrong_scope.status_code == 403
    assert wrong_scope.json()["error"]["code"] == "principal_scope_mismatch"


def test_memory_communication_policies_principal_scope_flow() -> None:
    client = _client(storage_backend="memory")

    created = client.post(
        "/v1/memory/communication-policies",
        json={
            "principal_id": "exec-1",
            "scope": "board_threads",
            "preferred_channel": "email",
            "tone": "concise_diplomatic",
            "max_length": 1200,
            "quiet_hours_json": {"start": "22:00", "end": "07:00"},
            "escalation_json": {"on_high_urgency": "notify_exec"},
            "status": "active",
            "notes": "Board-facing communication defaults",
        },
    )
    assert created.status_code == 200
    policy_id = created.json()["policy_id"]

    listed = client.get("/v1/memory/communication-policies", params={"principal_id": "exec-1", "limit": 10})
    assert listed.status_code == 200
    assert any(row["policy_id"] == policy_id for row in listed.json())

    fetched = client.get(f"/v1/memory/communication-policies/{policy_id}", params={"principal_id": "exec-1"})
    assert fetched.status_code == 200
    assert fetched.json()["scope"] == "board_threads"

    wrong_scope = client.get(f"/v1/memory/communication-policies/{policy_id}", params={"principal_id": "exec-2"})
    assert wrong_scope.status_code == 403
    assert wrong_scope.json()["error"]["code"] == "principal_scope_mismatch"


def test_memory_routes_use_default_principal_when_header_and_body_are_omitted() -> None:
    client = _client(storage_backend="memory", principal_id="")

    staged = client.post(
        "/v1/memory/candidates",
        json={
            "category": "stakeholder_pref",
            "summary": "Default principal candidate",
            "fact_json": {"channel": "email"},
        },
    )
    assert staged.status_code == 200
    assert staged.json()["principal_id"] == "local-user"

    listed = client.get("/v1/memory/candidates", params={"limit": 10})
    assert listed.status_code == 200
    assert any(row["candidate_id"] == staged.json()["candidate_id"] for row in listed.json())


def test_auth_allow_and_deny() -> None:
    token = "secret-token"
    client = _client(storage_backend="memory", auth_token=token, authenticated=False)

    denied = client.get("/v1/observations/recent")
    assert denied.status_code == 401
    assert denied.json()["error"]["code"] == "auth_required"

    allowed = client.get("/v1/observations/recent", headers=_headers(token))
    assert allowed.status_code == 200

    health = client.get("/health")
    assert health.status_code == 200


def test_prod_mode_rejects_insecure_startup_dependency_fallback() -> None:
    saved_env = {
        "EA_RUNTIME_MODE": os.environ.get("EA_RUNTIME_MODE"),
        "EA_API_TOKEN": os.environ.get("EA_API_TOKEN"),
        "EA_STORAGE_BACKEND": os.environ.get("EA_STORAGE_BACKEND"),
        "EA_LEDGER_BACKEND": os.environ.get("EA_LEDGER_BACKEND"),
        "DATABASE_URL": os.environ.get("DATABASE_URL"),
    }
    try:
        os.environ["EA_RUNTIME_MODE"] = "prod"
        os.environ["EA_API_TOKEN"] = "secret-token"
        os.environ["EA_STORAGE_BACKEND"] = "memory"
        os.environ.pop("EA_LEDGER_BACKEND", None)
        os.environ.pop("DATABASE_URL", None)

        from app.api.app import create_app

        with pytest.raises(RuntimeError, match=r"EA_RUNTIME_MODE=prod requires DATABASE_URL"):
            TestClient(create_app())
    finally:
        for key, value in saved_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def test_prod_mode_rejects_blank_api_token_at_startup() -> None:
    saved_env = {
        "EA_RUNTIME_MODE": os.environ.get("EA_RUNTIME_MODE"),
        "EA_API_TOKEN": os.environ.get("EA_API_TOKEN"),
        "EA_STORAGE_BACKEND": os.environ.get("EA_STORAGE_BACKEND"),
        "EA_LEDGER_BACKEND": os.environ.get("EA_LEDGER_BACKEND"),
        "DATABASE_URL": os.environ.get("DATABASE_URL"),
    }
    try:
        os.environ["EA_RUNTIME_MODE"] = "prod"
        os.environ["EA_API_TOKEN"] = "  \t"
        os.environ["EA_STORAGE_BACKEND"] = "postgres"
        os.environ.pop("EA_LEDGER_BACKEND", None)
        os.environ["DATABASE_URL"] = "postgresql://127.0.0.1:5432/ea"

        from app.api.app import create_app

        with pytest.raises(RuntimeError, match="EA_RUNTIME_MODE=prod requires EA_API_TOKEN or Cloudflare Access auth to be set"):
            TestClient(create_app())
    finally:
        for key, value in saved_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def test_ready_fails_when_postgres_backend_without_database_url() -> None:
    saved_env = {
        "EA_RUNTIME_MODE": os.environ.get("EA_RUNTIME_MODE"),
        "EA_API_TOKEN": os.environ.get("EA_API_TOKEN"),
        "EA_STORAGE_BACKEND": os.environ.get("EA_STORAGE_BACKEND"),
        "EA_LEDGER_BACKEND": os.environ.get("EA_LEDGER_BACKEND"),
        "DATABASE_URL": os.environ.get("DATABASE_URL"),
    }
    try:
        os.environ.pop("EA_RUNTIME_MODE", None)
        os.environ["EA_API_TOKEN"] = ""
        os.environ["EA_STORAGE_BACKEND"] = "postgres"
        os.environ.pop("EA_LEDGER_BACKEND", None)
        os.environ.pop("DATABASE_URL", None)

        from app.api.app import create_app

        with pytest.raises(RuntimeError, match=r"EA_STORAGE_BACKEND=postgres requires DATABASE_URL"):
            TestClient(create_app())
    finally:
        for key, value in saved_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def test_prod_ready_fails_when_postgres_backend_database_url_missing() -> None:
    saved_env = {
        "EA_RUNTIME_MODE": os.environ.get("EA_RUNTIME_MODE"),
        "EA_API_TOKEN": os.environ.get("EA_API_TOKEN"),
        "EA_STORAGE_BACKEND": os.environ.get("EA_STORAGE_BACKEND"),
        "EA_LEDGER_BACKEND": os.environ.get("EA_LEDGER_BACKEND"),
        "DATABASE_URL": os.environ.get("DATABASE_URL"),
    }
    try:
        os.environ["EA_RUNTIME_MODE"] = "prod"
        os.environ["EA_API_TOKEN"] = "secret-token"
        os.environ["EA_STORAGE_BACKEND"] = "postgres"
        os.environ.pop("EA_LEDGER_BACKEND", None)
        os.environ.pop("DATABASE_URL", None)

        from app.api.app import create_app

        with pytest.raises(RuntimeError, match=r"EA_RUNTIME_MODE=prod requires DATABASE_URL"):
            TestClient(create_app())
    finally:
        for key, value in saved_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
