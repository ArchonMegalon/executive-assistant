from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.domain.models import Artifact


def _client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("EA_STORAGE_BACKEND", "memory")
    monkeypatch.delenv("EA_LEDGER_BACKEND", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("EA_API_TOKEN", "test-token")
    monkeypatch.setenv("EA_TRUST_AUTHENTICATED_PRINCIPAL_HEADER", "1")
    monkeypatch.setenv("EA_OPERATOR_PRINCIPAL_IDS", "operator-1")
    monkeypatch.delenv("EA_DEFAULT_PRINCIPAL_ID", raising=False)
    monkeypatch.delenv("EA_ALLOW_AUTHENTICATED_PRINCIPAL_HEADER", raising=False)
    monkeypatch.delenv("EA_TRUST_API_TOKEN_PRINCIPAL_HEADER", raising=False)

    from app.api.app import create_app

    client = TestClient(create_app())
    client.headers.update({"Authorization": "Bearer test-token"})
    return client


def test_principal_scoped_rewrite(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _client(monkeypatch)
    principal_id_1 = "test-principal-1"
    principal_id_2 = "test-principal-2"

    contract = client.post(
        "/v1/tasks/contracts",
        headers={"X-EA-Principal-ID": "operator-1"},
        json={
            "task_key": "rewrite_text",
            "deliverable_type": "rewrite_note",
            "default_risk_class": "low",
            "default_approval_class": "none",
            "allowed_tools": ["artifact_repository"],
            "evidence_requirements": [],
            "memory_write_policy": "reviewed_only",
            "runtime_policy_json": {
                "workflow_template": "rewrite",
                "brain_profile": "easy",
                "posthoc_review_profile": "review_light",
                "fallback_brain_profile": "survival",
            },
        },
    )
    assert contract.status_code == 200

    response_1 = client.post(
        "/v1/rewrite/artifact",
        headers={"X-EA-Principal-ID": principal_id_1},
        json={
            "text": "This is a test text for principal 1.",
            "principal_id": principal_id_1,
            "goal": "test rewrite for principal 1",
        },
    )
    assert response_1.status_code in (200, 202)
    body_1 = response_1.json()
    session_id_1 = body_1.get("execution_session_id") or body_1.get("session_id")
    assert session_id_1
    artifact_id_1 = body_1.get("artifact_id")
    if not artifact_id_1:
        artifact_id_1 = "artifact-principal-1"
        client.app.state.container.orchestrator._artifacts.save(  # type: ignore[attr-defined]
            Artifact(
                artifact_id=artifact_id_1,
                kind="rewrite_note",
                content="This is a test text for principal 1.",
                execution_session_id=session_id_1,
                principal_id=principal_id_1,
            )
        )

    response_get_1_ok = client.get(
        f"/v1/rewrite/artifacts/{artifact_id_1}",
        headers={"X-EA-Principal-ID": principal_id_1},
    )
    assert response_get_1_ok.status_code == 200
    assert response_get_1_ok.json()["artifact_id"] == artifact_id_1

    response_session_get_1_ok = client.get(
        f"/v1/rewrite/sessions/{session_id_1}",
        headers={"X-EA-Principal-ID": principal_id_1},
    )
    assert response_session_get_1_ok.status_code == 200
    assert response_session_get_1_ok.json()["session_id"] == session_id_1

    response_get_1_fail = client.get(
        f"/v1/rewrite/artifacts/{artifact_id_1}",
        headers={"X-EA-Principal-ID": principal_id_2},
    )
    assert response_get_1_fail.status_code == 403

    response_session_get_1_fail = client.get(
        f"/v1/rewrite/sessions/{session_id_1}",
        headers={"X-EA-Principal-ID": principal_id_2},
    )
    assert response_session_get_1_fail.status_code == 403

    response_2 = client.post(
        "/v1/rewrite/artifact",
        headers={"X-EA-Principal-ID": principal_id_2},
        json={
            "text": "This is a test text for principal 2.",
            "principal_id": principal_id_2,
            "goal": "test rewrite for principal 2",
        },
    )
    assert response_2.status_code in (200, 202)
    body_2 = response_2.json()
    session_id_2 = body_2.get("execution_session_id") or body_2.get("session_id")
    assert session_id_2
    artifact_id_2 = body_2.get("artifact_id")
    if not artifact_id_2:
        artifact_id_2 = "artifact-principal-2"
        client.app.state.container.orchestrator._artifacts.save(  # type: ignore[attr-defined]
            Artifact(
                artifact_id=artifact_id_2,
                kind="rewrite_note",
                content="This is a test text for principal 2.",
                execution_session_id=session_id_2,
                principal_id=principal_id_2,
            )
        )

    response_get_2_ok = client.get(
        f"/v1/rewrite/artifacts/{artifact_id_2}",
        headers={"X-EA-Principal-ID": principal_id_2},
    )
    assert response_get_2_ok.status_code == 200
    assert response_get_2_ok.json()["artifact_id"] == artifact_id_2

    response_get_2_fail = client.get(
        f"/v1/rewrite/artifacts/{artifact_id_2}",
        headers={"X-EA-Principal-ID": principal_id_1},
    )
    assert response_get_2_fail.status_code == 403
