from __future__ import annotations

import os

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient


def _client(*, principal_id: str, approval_threshold_chars: int = 5) -> TestClient:
    os.environ["EA_STORAGE_BACKEND"] = "memory"
    os.environ.pop("EA_LEDGER_BACKEND", None)
    os.environ["EA_API_TOKEN"] = ""
    os.environ["EA_APPROVAL_THRESHOLD_CHARS"] = str(approval_threshold_chars)
    from app.api.app import create_app

    client = TestClient(create_app())
    client.headers.update({"X-EA-Principal-ID": principal_id})
    return client


def test_policy_evaluate_rejects_cross_principal_body_scope() -> None:
    client = _client(principal_id="exec-1")

    allowed = client.post(
        "/v1/policy/evaluate",
        json={
            "content": "Send the board update.",
            "tool_name": "connector.dispatch",
            "action_kind": "delivery.send",
            "channel": "email",
        },
    )
    assert allowed.status_code == 200
    assert allowed.json()["requires_approval"] is True

    denied = client.post(
        "/v1/policy/evaluate",
        json={
            "content": "Send the board update.",
            "tool_name": "connector.dispatch",
            "action_kind": "delivery.send",
            "channel": "email",
            "principal_id": "exec-2",
        },
    )
    assert denied.status_code == 403
    assert denied.json()["error"]["code"] == "principal_scope_mismatch"


def test_policy_routes_hide_and_reject_cross_principal_approvals() -> None:
    client = _client(principal_id="exec-1")

    created = client.post("/v1/rewrite/artifact", json={"text": "approval scope payload"})
    assert created.status_code == 202
    approval_id = created.json()["approval_id"]
    session_id = created.json()["session_id"]

    pending_owner = client.get("/v1/policy/approvals/pending", params={"limit": 10})
    assert pending_owner.status_code == 200
    assert any(row["approval_id"] == approval_id for row in pending_owner.json())

    pending_foreign = client.get(
        "/v1/policy/approvals/pending",
        params={"limit": 10},
        headers={"X-EA-Principal-ID": "exec-2"},
    )
    assert pending_foreign.status_code == 200
    assert all(row["approval_id"] != approval_id for row in pending_foreign.json())

    foreign_session = client.get(
        "/v1/policy/decisions/recent",
        params={"session_id": session_id, "limit": 10},
        headers={"X-EA-Principal-ID": "exec-2"},
    )
    assert foreign_session.status_code == 403
    assert foreign_session.json()["error"]["code"] == "principal_scope_mismatch"

    foreign_approve = client.post(
        f"/v1/policy/approvals/{approval_id}/approve",
        json={"decided_by": "exec-2", "reason": "forbidden cross-principal approval"},
        headers={"X-EA-Principal-ID": "exec-2"},
    )
    assert foreign_approve.status_code == 403
    assert foreign_approve.json()["error"]["code"] == "principal_scope_mismatch"

    approved = client.post(
        f"/v1/policy/approvals/{approval_id}/approve",
        json={"decided_by": "exec-1", "reason": "approved in principal scope"},
    )
    assert approved.status_code == 200
    assert approved.json()["decision"] == "approved"

    history_owner = client.get("/v1/policy/approvals/history", params={"session_id": session_id, "limit": 10})
    assert history_owner.status_code == 200
    assert any(row["approval_id"] == approval_id and row["decision"] == "approved" for row in history_owner.json())

    history_foreign = client.get(
        "/v1/policy/approvals/history",
        params={"session_id": session_id, "limit": 10},
        headers={"X-EA-Principal-ID": "exec-2"},
    )
    assert history_foreign.status_code == 403
    assert history_foreign.json()["error"]["code"] == "principal_scope_mismatch"
