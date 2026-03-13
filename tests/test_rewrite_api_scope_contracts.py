from __future__ import annotations

import os

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient


def _client(*, principal_id: str) -> TestClient:
    os.environ["EA_STORAGE_BACKEND"] = "memory"
    os.environ.pop("EA_LEDGER_BACKEND", None)
    os.environ.pop("EA_DEFAULT_PRINCIPAL_ID", None)
    os.environ["EA_API_TOKEN"] = ""
    os.environ["EA_APPROVAL_THRESHOLD_CHARS"] = "5000"
    from app.api.app import create_app

    client = TestClient(create_app())
    client.headers.update({"X-EA-Principal-ID": principal_id})
    return client


def test_rewrite_fetch_routes_reject_cross_principal_access() -> None:
    owner = _client(principal_id="exec-1")
    created = owner.post("/v1/rewrite/artifact", json={"text": "scoped artifact"})
    assert created.status_code == 200

    payload = created.json()
    session = owner.get(f"/v1/rewrite/sessions/{payload['execution_session_id']}")
    assert session.status_code == 200
    session_body = session.json()
    assert payload["principal_id"] == "exec-1"
    assert session_body["artifacts"][0]["principal_id"] == "exec-1"
    fetched_artifact = owner.get(f"/v1/rewrite/artifacts/{payload['artifact_id']}")
    assert fetched_artifact.status_code == 200
    assert fetched_artifact.json()["principal_id"] == "exec-1"

    for path in (
        f"/v1/rewrite/sessions/{payload['execution_session_id']}",
        f"/v1/rewrite/artifacts/{payload['artifact_id']}",
        f"/v1/rewrite/receipts/{session_body['receipts'][0]['receipt_id']}",
        f"/v1/rewrite/run-costs/{session_body['run_costs'][0]['cost_id']}",
    ):
        denied = owner.get(path, headers={"X-EA-Principal-ID": "exec-2"})
        assert denied.status_code == 403
        assert denied.json()["error"]["code"] == "principal_scope_mismatch"


def test_rewrite_artifact_surfaces_delayed_retry_as_queued_async_acceptance() -> None:
    owner = _client(principal_id="exec-1")
    container = owner.app.state.container
    original = container.tool_execution._handlers["artifact_repository"]
    calls = {"count": 0}

    def flaky_artifact_handler(request, definition):
        calls["count"] += 1
        if calls["count"] == 1:
            raise RuntimeError("temporary_failure")
        return original(request, definition)

    container.tool_execution.register_handler("artifact_repository", flaky_artifact_handler)

    contract = owner.post(
        "/v1/tasks/contracts",
        json={
            "task_key": "rewrite_text",
            "deliverable_type": "rewrite_note",
            "default_risk_class": "low",
            "default_approval_class": "none",
            "allowed_tools": ["artifact_repository"],
            "memory_write_policy": "reviewed_only",
            "budget_policy_json": {
                "class": "low",
                "artifact_failure_strategy": "retry",
                "artifact_max_attempts": 2,
                "artifact_retry_backoff_seconds": 30,
            },
        },
    )
    assert contract.status_code == 200

    created = owner.post("/v1/rewrite/artifact", json={"text": "delayed retry artifact"})
    assert created.status_code == 202
    assert created.json()["status"] == "queued"
    assert created.json()["next_action"] == "poll_or_subscribe"

    session = owner.get(f"/v1/rewrite/sessions/{created.json()['session_id']}")
    assert session.status_code == 200
    session_body = session.json()
    assert session_body["status"] == "queued"
    artifact_step = next(
        row for row in session_body["steps"] if row["input_json"]["plan_step_key"] == "step_artifact_save"
    )
    assert artifact_step["state"] == "queued"
    assert artifact_step["error_json"]["reason"] == "retry_scheduled"
    assert session_body["queue_items"][-1]["state"] == "queued"
    assert session_body["queue_items"][-1]["next_attempt_at"]
    assert calls["count"] == 1
