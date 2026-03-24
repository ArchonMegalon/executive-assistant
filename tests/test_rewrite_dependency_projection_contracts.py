from __future__ import annotations

import os

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient


def _client(*, approval_threshold_chars: int | None = None) -> TestClient:
    os.environ["EA_STORAGE_BACKEND"] = "memory"
    os.environ.pop("EA_LEDGER_BACKEND", None)
    os.environ["EA_API_TOKEN"] = "test-token"
    os.environ["EA_TRUST_AUTHENTICATED_PRINCIPAL_HEADER"] = "1"
    os.environ["EA_OPERATOR_PRINCIPAL_IDS"] = "exec-1"
    if approval_threshold_chars is None:
        os.environ.pop("EA_APPROVAL_THRESHOLD_CHARS", None)
    else:
        os.environ["EA_APPROVAL_THRESHOLD_CHARS"] = str(approval_threshold_chars)
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


def test_session_steps_project_dependency_keys_alongside_parent_links() -> None:
    client = _client()
    created = client.post("/v1/rewrite/artifact", json={"text": "dependency projection"})
    assert created.status_code == 200

    session = client.get(f"/v1/rewrite/sessions/{created.json()['execution_session_id']}")
    assert session.status_code == 200

    steps = _steps_by_key(session.json())
    assert steps["step_input_prepare"]["dependency_keys"] == []
    assert steps["step_input_prepare"]["dependency_states"] == {}
    assert steps["step_input_prepare"]["dependency_step_ids"] == {}
    assert steps["step_input_prepare"]["blocked_dependency_keys"] == []
    assert steps["step_input_prepare"]["dependencies_satisfied"] is True
    assert steps["step_policy_evaluate"]["dependency_keys"] == ["step_input_prepare"]
    assert steps["step_policy_evaluate"]["dependency_states"] == {"step_input_prepare": "completed"}
    assert steps["step_policy_evaluate"]["dependency_step_ids"]["step_input_prepare"] == steps["step_input_prepare"]["step_id"]
    assert steps["step_policy_evaluate"]["blocked_dependency_keys"] == []
    assert steps["step_policy_evaluate"]["dependencies_satisfied"] is True
    assert steps["step_artifact_save"]["dependency_keys"] == ["step_policy_evaluate"]
    assert steps["step_artifact_save"]["dependency_states"] == {"step_policy_evaluate": "completed"}
    assert steps["step_artifact_save"]["dependency_step_ids"]["step_policy_evaluate"] == steps["step_policy_evaluate"]["step_id"]
    assert steps["step_artifact_save"]["blocked_dependency_keys"] == []
    assert steps["step_artifact_save"]["dependencies_satisfied"] is True


def test_session_steps_keep_dependency_projection_when_waiting_approval() -> None:
    client = _client(approval_threshold_chars=5)
    created = client.post("/v1/rewrite/artifact", json={"text": "approval gated dependency projection"})
    assert created.status_code == 202

    session = client.get(f"/v1/rewrite/sessions/{created.json()['session_id']}")
    assert session.status_code == 200

    steps = _steps_by_key(session.json())
    assert steps["step_policy_evaluate"]["dependency_states"] == {"step_input_prepare": "completed"}
    assert steps["step_policy_evaluate"]["blocked_dependency_keys"] == []
    assert steps["step_policy_evaluate"]["dependencies_satisfied"] is True
    assert steps["step_artifact_save"]["state"] == "waiting_approval"
    assert steps["step_artifact_save"]["dependency_keys"] == ["step_policy_evaluate"]
    assert steps["step_artifact_save"]["dependency_states"] == {"step_policy_evaluate": "completed"}
    assert steps["step_artifact_save"]["dependency_step_ids"]["step_policy_evaluate"] == steps["step_policy_evaluate"]["step_id"]
    assert steps["step_artifact_save"]["blocked_dependency_keys"] == []
    assert steps["step_artifact_save"]["dependencies_satisfied"] is True


def test_session_steps_project_blocked_dependency_state_when_waiting_human() -> None:
    client = _client()
    contract = client.post(
        "/v1/tasks/contracts",
        json={
            "task_key": "rewrite_text",
            "deliverable_type": "rewrite_note",
            "default_risk_class": "low",
            "default_approval_class": "none",
            "allowed_tools": ["artifact_repository"],
            "evidence_requirements": ["stakeholder_context"],
            "memory_write_policy": "reviewed_only",
            "budget_policy_json": {
                "class": "low",
                "human_review_role": "communications_reviewer",
                "human_review_task_type": "communications_review",
                "human_review_brief": "Review the rewrite before finalizing it.",
                "human_review_priority": "high",
                "human_review_sla_minutes": 45,
                "human_review_desired_output_json": {"format": "review_packet"},
                "human_review_authority_required": "send_on_behalf_review",
                "human_review_why_human": "Executive-facing rewrite needs human judgment before finalization.",
                "human_review_quality_rubric_json": {"checks": ["tone", "accuracy", "stakeholder_sensitivity"]},
            },
        },
    )
    assert contract.status_code == 200

    created = client.post("/v1/rewrite/artifact", json={"text": "rewrite with human review"})
    assert created.status_code == 202

    session = client.get(f"/v1/rewrite/sessions/{created.json()['session_id']}")
    assert session.status_code == 200

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
