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


def test_openapi_session_step_schema_includes_paused_dependency_examples() -> None:
    client = _client()
    response = client.get("/openapi.json")
    assert response.status_code == 200

    session_step = response.json()["components"]["schemas"]["SessionStepOut"]
    examples = session_step["examples"]
    assert len(examples) >= 2

    waiting_approval = next(
        example for example in examples if example["step_id"] == "step-artifact-save-waiting-approval"
    )
    assert waiting_approval["state"] == "waiting_approval"
    assert waiting_approval["dependency_states"] == {"step_policy_evaluate": "completed"}
    assert waiting_approval["blocked_dependency_keys"] == []
    assert waiting_approval["dependencies_satisfied"] is True

    blocked_human = next(
        example for example in examples if example["step_id"] == "step-artifact-save-blocked-human"
    )
    assert blocked_human["state"] == "queued"
    assert blocked_human["dependency_states"] == {"step_human_review": "waiting_human"}
    assert blocked_human["blocked_dependency_keys"] == ["step_human_review"]
    assert blocked_human["dependencies_satisfied"] is False
