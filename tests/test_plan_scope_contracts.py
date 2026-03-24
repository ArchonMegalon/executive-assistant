from __future__ import annotations

import os

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient


def _client(*, principal_id: str) -> TestClient:
    os.environ["EA_STORAGE_BACKEND"] = "memory"
    os.environ.pop("EA_LEDGER_BACKEND", None)
    os.environ.pop("EA_DEFAULT_PRINCIPAL_ID", None)
    os.environ["EA_API_TOKEN"] = "test-token"
    os.environ["EA_TRUST_AUTHENTICATED_PRINCIPAL_HEADER"] = "1"
    os.environ["EA_OPERATOR_PRINCIPAL_IDS"] = "operator-1"
    from app.api.app import create_app

    client = TestClient(create_app())
    client.headers.update({"Authorization": "Bearer test-token"})
    client.headers.update({"X-EA-Principal-ID": principal_id})
    return client


def test_plan_compile_rejects_cross_principal_body_scope() -> None:
    owner = _client(principal_id="exec-1")

    compiled = owner.post("/v1/plans/compile", json={"task_key": "rewrite_text", "goal": "rewrite this"})
    assert compiled.status_code == 200
    assert compiled.json()["intent"]["principal_id"] == "exec-1"
    assert compiled.json()["plan"]["principal_id"] == "exec-1"

    denied = owner.post(
        "/v1/plans/compile",
        json={"task_key": "rewrite_text", "principal_id": "exec-2", "goal": "rewrite this"},
    )
    assert denied.status_code == 403
    assert denied.json()["error"]["code"] == "principal_scope_mismatch"


def test_plan_execute_completed_outputs_stay_in_principal_scope() -> None:
    owner = _client(principal_id="exec-1")

    contract = owner.post(
        "/v1/tasks/contracts",
        headers={"Authorization": "Bearer test-token", "X-EA-Principal-ID": "operator-1"},
        json={
            "task_key": "stakeholder_briefing_scope",
            "deliverable_type": "stakeholder_briefing",
            "default_risk_class": "low",
            "default_approval_class": "none",
            "allowed_tools": ["artifact_repository"],
            "memory_write_policy": "reviewed_only",
            "budget_policy_json": {"class": "low"},
        },
    )
    assert contract.status_code == 200

    execute = owner.post(
        "/v1/plans/execute",
        json={
            "task_key": "stakeholder_briefing_scope",
            "text": "Board context and stakeholder sensitivities.",
            "goal": "prepare a stakeholder briefing",
        },
    )
    assert execute.status_code == 200
    body = execute.json()

    session = owner.get(f"/v1/rewrite/sessions/{body['execution_session_id']}")
    assert session.status_code == 200
    session_body = session.json()

    for path in (
        f"/v1/rewrite/sessions/{body['execution_session_id']}",
        f"/v1/rewrite/artifacts/{body['artifact_id']}",
        f"/v1/rewrite/receipts/{session_body['receipts'][0]['receipt_id']}",
        f"/v1/rewrite/run-costs/{session_body['run_costs'][0]['cost_id']}",
    ):
        denied = owner.get(path, headers={"X-EA-Principal-ID": "exec-2"})
        assert denied.status_code == 403
        assert denied.json()["error"]["code"] == "principal_scope_mismatch"

    mismatch = owner.post(
        "/v1/plans/execute",
        json={
            "task_key": "stakeholder_briefing_scope",
            "text": "Should stay in principal scope.",
            "principal_id": "exec-2",
            "goal": "prepare a stakeholder briefing",
        },
    )
    assert mismatch.status_code == 403
    assert mismatch.json()["error"]["code"] == "principal_scope_mismatch"


def test_plan_execute_async_session_stays_in_principal_scope() -> None:
    owner = _client(principal_id="exec-1")

    contract = owner.post(
        "/v1/tasks/contracts",
        headers={"Authorization": "Bearer test-token", "X-EA-Principal-ID": "operator-1"},
        json={
            "task_key": "decision_brief_scope_review",
            "deliverable_type": "decision_brief",
            "default_risk_class": "low",
            "default_approval_class": "manager",
            "allowed_tools": ["artifact_repository"],
            "memory_write_policy": "reviewed_only",
            "budget_policy_json": {"class": "low"},
        },
    )
    assert contract.status_code == 200

    accepted = owner.post(
        "/v1/plans/execute",
        json={
            "task_key": "decision_brief_scope_review",
            "text": "Decision context that requires approval.",
            "goal": "prepare a decision brief",
        },
    )
    assert accepted.status_code == 202
    assert accepted.json()["status"] == "awaiting_approval"

    owner_session = owner.get(f"/v1/rewrite/sessions/{accepted.json()['session_id']}")
    assert owner_session.status_code == 200

    denied = owner.get(f"/v1/rewrite/sessions/{accepted.json()['session_id']}", headers={"X-EA-Principal-ID": "exec-2"})
    assert denied.status_code == 403
    assert denied.json()["error"]["code"] == "principal_scope_mismatch"
