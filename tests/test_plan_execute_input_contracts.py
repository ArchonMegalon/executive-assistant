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
            "context_refs": ["thread:board-prep", "memory:item:stakeholder-brief"],
        },
    )
    assert execute.status_code == 200
    body = execute.json()
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
    assert prepare_step["input_json"]["context_refs"] == ["thread:board-prep", "memory:item:stakeholder-brief"]


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
