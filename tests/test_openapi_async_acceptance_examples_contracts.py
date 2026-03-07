from __future__ import annotations

import os

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient


def _client() -> TestClient:
    os.environ["EA_STORAGE_BACKEND"] = "memory"
    os.environ.pop("EA_LEDGER_BACKEND", None)
    os.environ["EA_API_TOKEN"] = ""
    from app.api.app import create_app

    return TestClient(create_app())


def test_openapi_async_acceptance_schemas_include_approval_and_human_examples() -> None:
    client = _client()
    response = client.get("/openapi.json")
    assert response.status_code == 200

    schemas = response.json()["components"]["schemas"]

    rewrite_examples = schemas["RewriteAcceptedOut"]["examples"]
    rewrite_approval = next(example for example in rewrite_examples if example["status"] == "awaiting_approval")
    rewrite_human = next(example for example in rewrite_examples if example["status"] == "awaiting_human")
    rewrite_queued = next(example for example in rewrite_examples if example["status"] == "queued")
    assert rewrite_approval["approval_id"] == "approval-123"
    assert rewrite_approval["human_task_id"] == ""
    assert rewrite_approval["next_action"] == "poll_or_subscribe"
    assert rewrite_human["approval_id"] == ""
    assert rewrite_human["human_task_id"] == "human-task-123"
    assert rewrite_human["next_action"] == "poll_or_subscribe"
    assert rewrite_queued["approval_id"] == ""
    assert rewrite_queued["human_task_id"] == ""
    assert rewrite_queued["next_action"] == "poll_or_subscribe"

    plan_examples = schemas["PlanExecuteAcceptedOut"]["examples"]
    plan_approval = next(example for example in plan_examples if example["status"] == "awaiting_approval")
    plan_human = next(example for example in plan_examples if example["status"] == "awaiting_human")
    plan_queued = next(example for example in plan_examples if example["status"] == "queued")
    assert plan_approval["task_key"] == "decision_brief_approval"
    assert plan_approval["approval_id"] == "approval-123"
    assert plan_approval["human_task_id"] == ""
    assert plan_human["task_key"] == "stakeholder_briefing_review"
    assert plan_human["approval_id"] == ""
    assert plan_human["human_task_id"] == "human-task-123"
    assert plan_queued["task_key"] == "rewrite_retry_delayed"
    assert plan_queued["approval_id"] == ""
    assert plan_queued["human_task_id"] == ""
    assert plan_queued["next_action"] == "poll_or_subscribe"
