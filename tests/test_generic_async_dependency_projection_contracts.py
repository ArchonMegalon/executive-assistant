from __future__ import annotations

import os

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient


def _client() -> TestClient:
    os.environ["EA_STORAGE_BACKEND"] = "memory"
    os.environ.pop("EA_LEDGER_BACKEND", None)
    os.environ.pop("EA_DEFAULT_PRINCIPAL_ID", None)
    os.environ["EA_API_TOKEN"] = "test-token"
    os.environ["EA_TRUST_AUTHENTICATED_PRINCIPAL_HEADER"] = "1"
    os.environ["EA_OPERATOR_PRINCIPAL_IDS"] = "exec-1"
    from app.api.app import create_app

    client = TestClient(create_app())
    client.headers.update({"Authorization": "Bearer test-token"})
    client.headers.update({"X-EA-Principal-ID": "exec-1"})
    return client


def _steps_by_key(session_json: dict[str, object]) -> dict[str, dict[str, object]]:
    return {
        str((step.get("input_json") or {}).get("plan_step_key") or ""): step
        for step in (session_json.get("steps") or [])
        if isinstance(step, dict)
    }


def test_generic_async_approval_session_keeps_dependency_projection() -> None:
    client = _client()
    contract = client.post(
        "/v1/tasks/contracts",
        json={
            "task_key": "decision_brief_approval",
            "deliverable_type": "decision_brief",
            "default_risk_class": "low",
            "default_approval_class": "manager",
            "allowed_tools": ["artifact_repository"],
            "evidence_requirements": ["decision_context"],
            "memory_write_policy": "reviewed_only",
            "budget_policy_json": {"class": "low"},
        },
    )
    assert contract.status_code == 200

    execute = client.post(
        "/v1/plans/execute",
        json={
            "task_key": "decision_brief_approval",
            "text": "Decision context for the approval-backed briefing.",
            "goal": "prepare a decision brief",
        },
    )
    assert execute.status_code == 202

    session = client.get(f"/v1/rewrite/sessions/{execute.json()['session_id']}")
    assert session.status_code == 200
    assert session.json()["intent_task_type"] == "decision_brief_approval"

    steps = _steps_by_key(session.json())
    assert steps["step_artifact_save"]["state"] == "waiting_approval"
    assert steps["step_artifact_save"]["dependency_keys"] == ["step_policy_evaluate"]
    assert steps["step_artifact_save"]["dependency_states"] == {"step_policy_evaluate": "completed"}
    assert steps["step_artifact_save"]["dependency_step_ids"]["step_policy_evaluate"] == steps["step_policy_evaluate"]["step_id"]
    assert steps["step_artifact_save"]["blocked_dependency_keys"] == []
    assert steps["step_artifact_save"]["dependencies_satisfied"] is True


def test_generic_async_human_session_projects_blocked_dependency_state() -> None:
    client = _client()
    contract = client.post(
        "/v1/tasks/contracts",
        json={
            "task_key": "stakeholder_briefing_review",
            "deliverable_type": "stakeholder_briefing",
            "default_risk_class": "low",
            "default_approval_class": "none",
            "allowed_tools": ["artifact_repository"],
            "evidence_requirements": ["stakeholder_context"],
            "memory_write_policy": "reviewed_only",
            "budget_policy_json": {
                "class": "low",
                "human_review_role": "briefing_reviewer",
                "human_review_task_type": "briefing_review",
                "human_review_brief": "Review the stakeholder briefing before finalization.",
                "human_review_priority": "high",
                "human_review_desired_output_json": {"format": "review_packet"},
            },
        },
    )
    assert contract.status_code == 200

    execute = client.post(
        "/v1/plans/execute",
        json={
            "task_key": "stakeholder_briefing_review",
            "text": "Stakeholder context for human-reviewed briefing.",
            "goal": "prepare a stakeholder briefing",
        },
    )
    assert execute.status_code == 202

    session = client.get(f"/v1/rewrite/sessions/{execute.json()['session_id']}")
    assert session.status_code == 200
    assert session.json()["intent_task_type"] == "stakeholder_briefing_review"

    steps = _steps_by_key(session.json())
    assert steps["step_human_review"]["state"] == "waiting_human"
    assert steps["step_human_review"]["dependency_keys"] == ["step_policy_evaluate"]
    assert steps["step_human_review"]["dependency_states"] == {"step_policy_evaluate": "completed"}
    assert steps["step_human_review"]["dependency_step_ids"]["step_policy_evaluate"] == steps["step_policy_evaluate"]["step_id"]
    assert steps["step_human_review"]["blocked_dependency_keys"] == []
    assert steps["step_human_review"]["dependencies_satisfied"] is True
    assert steps["step_artifact_save"]["state"] == "queued"
    assert steps["step_artifact_save"]["dependency_keys"] == ["step_human_review"]
    assert steps["step_artifact_save"]["dependency_states"] == {"step_human_review": "waiting_human"}
    assert steps["step_artifact_save"]["dependency_step_ids"]["step_human_review"] == steps["step_human_review"]["step_id"]
    assert steps["step_artifact_save"]["blocked_dependency_keys"] == ["step_human_review"]
    assert steps["step_artifact_save"]["dependencies_satisfied"] is False
