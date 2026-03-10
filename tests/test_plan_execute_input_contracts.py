from __future__ import annotations

import os

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient


def _client(*, principal_id: str = "exec-1") -> TestClient:
    os.environ["EA_STORAGE_BACKEND"] = "memory"
    os.environ.pop("EA_LEDGER_BACKEND", None)
    os.environ["EA_API_TOKEN"] = ""
    from app.api.app import create_app

    client = TestClient(create_app())
    if principal_id:
        client.headers.update({"X-EA-Principal-ID": principal_id})
    return client


def test_plan_execute_accepts_structured_input_json_and_context_refs() -> None:
    client = _client()
    candidate = client.post(
        "/v1/memory/candidates/stage",
        json={
            "category": "stakeholder_pref",
            "summary": "Alex prefers concise updates",
            "fact_json": {"tone": "concise"},
        },
    )
    assert candidate.status_code == 200
    promoted = client.post(
        f"/v1/memory/candidates/{candidate.json()['candidate_id']}/promote",
        json={"reviewer": "operator-1"},
    )
    assert promoted.status_code == 200
    item_id = promoted.json()["item"]["item_id"]

    execute = client.post(
        "/v1/plans/execute",
        json={
            "task_key": "rewrite_text",
            "goal": "rewrite this text",
            "input_json": {
                "source_text": "Structured workflow input.",
                "channel": "email",
                "stakeholder_ref": "alex-exec",
            },
            "context_refs": ["thread:board-prep", f"memory:item:{item_id}"],
        },
    )
    assert execute.status_code == 200
    body = execute.json()
    assert body["skill_key"] == "rewrite_text"
    assert body["content"] == "Structured workflow input."

    session = client.get(f"/v1/rewrite/sessions/{body['execution_session_id']}")
    assert session.status_code == 200
    session_body = session.json()
    prepare_step = next(
        row for row in session_body["steps"] if row["input_json"]["plan_step_key"] == "step_input_prepare"
    )
    assert prepare_step["input_json"]["source_text"] == "Structured workflow input."
    assert prepare_step["input_json"]["normalized_text"] == "Structured workflow input."
    assert prepare_step["input_json"]["channel"] == "email"
    assert prepare_step["input_json"]["stakeholder_ref"] == "alex-exec"
    assert prepare_step["input_json"]["context_refs"] == ["thread:board-prep", f"memory:item:{item_id}"]
    assert prepare_step["input_json"]["context_pack"]["principal_id"] == "exec-1"
    assert prepare_step["input_json"]["context_pack"]["memory_items"][0]["item_id"] == item_id
    assert prepare_step["input_json"]["context_pack"]["unresolved_refs"] == ["thread:board-prep"]


def test_memory_context_pack_route_returns_reasoned_pack() -> None:
    client = _client()
    candidate = client.post(
        "/v1/memory/candidates/stage",
        json={
            "category": "commitment",
            "summary": "Send board follow-up",
            "fact_json": {"due_at": "2026-03-10T09:00:00+00:00", "status": "open"},
            "confidence": 0.9,
        },
    )
    assert candidate.status_code == 200
    runtime = client.app.state.container.memory_runtime
    runtime.upsert_commitment(
        principal_id="exec-1",
        title="Send board follow-up",
        details="Needs send",
        status="open",
        priority="high",
        due_at="2026-03-10T08:00:00+00:00",
    )

    response = client.post(
        "/v1/memory/context-pack",
        json={
            "task_key": "rewrite_text",
            "goal": "Draft board follow-up",
            "context_refs": ["thread:board-prep"],
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["principal_id"] == "exec-1"
    assert body["task_key"] == "rewrite_text"
    assert body["unresolved_refs"] == ["thread:board-prep"]
    assert body["promotion_signals"][0]["candidate_id"] == candidate.json()["candidate_id"]
    assert any(row["risk_type"] == "commitment_deadline" for row in body["commitment_risks"])


def test_plan_execute_requires_text_or_input_json() -> None:
    client = _client()

    execute = client.post(
        "/v1/plans/execute",
        json={
            "task_key": "rewrite_text",
            "goal": "rewrite this text",
            "text": "",
            "input_json": {},
        },
    )
    assert execute.status_code == 422
    assert any(
        detail["type"] == "text_or_input_json_required"
        for detail in execute.json()["error"]["details"]
    )


def test_plan_execute_requires_task_or_skill_key() -> None:
    client = _client()

    execute = client.post(
        "/v1/plans/execute",
        json={
            "goal": "rewrite this text",
            "text": "payload present but no task selector",
        },
    )
    assert execute.status_code == 422
    assert any(
        detail["type"] == "task_or_skill_key_required"
        for detail in execute.json()["error"]["details"]
    )


def test_plan_execute_surfaces_delayed_retry_as_queued_async_acceptance() -> None:
    client = _client()
    container = client.app.state.container
    original = container.tool_execution._handlers["artifact_repository"]
    calls = {"count": 0}

    def flaky_artifact_handler(request, definition):
        calls["count"] += 1
        if calls["count"] == 1:
            raise RuntimeError("temporary_failure")
        return original(request, definition)

    container.tool_execution.register_handler("artifact_repository", flaky_artifact_handler)

    contract = client.post(
        "/v1/tasks/contracts",
        json={
            "task_key": "rewrite_retry_delayed_plan",
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

    execute = client.post(
        "/v1/plans/execute",
        json={
            "task_key": "rewrite_retry_delayed_plan",
            "goal": "retry this later",
            "text": "Delayed retry payload.",
        },
    )
    assert execute.status_code == 202
    assert execute.json()["skill_key"] == "rewrite_retry_delayed_plan"
    assert execute.json()["status"] == "queued"
    assert execute.json()["next_action"] == "poll_or_subscribe"

    session = client.get(f"/v1/rewrite/sessions/{execute.json()['session_id']}")
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
