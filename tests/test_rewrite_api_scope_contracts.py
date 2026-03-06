from __future__ import annotations

import os

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient


def _client(*, principal_id: str) -> TestClient:
    os.environ["EA_STORAGE_BACKEND"] = "memory"
    os.environ.pop("EA_LEDGER_BACKEND", None)
    os.environ["EA_API_TOKEN"] = ""
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
