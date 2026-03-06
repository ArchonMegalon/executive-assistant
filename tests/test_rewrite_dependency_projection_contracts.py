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

    client = TestClient(create_app())
    client.headers.update({"X-EA-Principal-ID": "exec-1"})
    return client


def test_session_steps_project_dependency_keys_alongside_parent_links() -> None:
    client = _client()
    created = client.post("/v1/rewrite/artifact", json={"text": "dependency projection"})
    assert created.status_code == 200

    session = client.get(f"/v1/rewrite/sessions/{created.json()['execution_session_id']}")
    assert session.status_code == 200

    steps = {
        step["input_json"]["plan_step_key"]: step
        for step in session.json()["steps"]
    }
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
