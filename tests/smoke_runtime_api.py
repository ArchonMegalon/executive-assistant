from __future__ import annotations

import os

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient


def _client(
    *,
    storage_backend: str = "memory",
    auth_token: str = "",
    database_url: str = "",
    approval_threshold_chars: int | None = None,
) -> TestClient:
    os.environ["EA_STORAGE_BACKEND"] = storage_backend
    os.environ["EA_LEDGER_BACKEND"] = storage_backend  # backward-compat path
    os.environ["EA_API_TOKEN"] = auth_token
    if approval_threshold_chars is None:
        os.environ.pop("EA_APPROVAL_THRESHOLD_CHARS", None)
    else:
        os.environ["EA_APPROVAL_THRESHOLD_CHARS"] = str(approval_threshold_chars)
    if database_url:
        os.environ["DATABASE_URL"] = database_url
    else:
        os.environ.pop("DATABASE_URL", None)
    from app.api.app import create_app

    return TestClient(create_app())


def _headers(token: str = "") -> dict[str, str]:
    if not token:
        return {}
    return {"Authorization": f"Bearer {token}"}


def test_health_ready_and_version() -> None:
    client = _client(storage_backend="memory")
    assert client.get("/health").status_code == 200
    assert client.get("/health/live").json()["status"] == "live"
    ready = client.get("/health/ready")
    assert ready.status_code == 200
    assert ready.json()["status"] == "ready"
    version = client.get("/version")
    assert version.status_code == 200
    assert version.json()["app_name"]
    assert version.json()["version"]


def test_rewrite_and_policy_audit_flow() -> None:
    client = _client(storage_backend="memory")
    create = client.post("/v1/rewrite/artifact", json={"text": "smoke"})
    assert create.status_code == 200
    payload = create.json()
    session_id = payload["execution_session_id"]

    session = client.get(f"/v1/rewrite/sessions/{session_id}")
    assert session.status_code == 200
    body = session.json()
    event_names = [e["name"] for e in body["events"]]
    assert "policy_decision" in event_names
    assert len(body["steps"]) >= 1
    assert body["steps"][0]["state"] in {"completed", "running", "blocked", "waiting_approval"}
    assert len(body["receipts"]) >= 1
    assert body["artifacts"][0]["artifact_id"] == payload["artifact_id"]

    policy = client.get("/v1/policy/decisions/recent", params={"session_id": session_id, "limit": 5})
    assert policy.status_code == 200
    decisions = policy.json()
    assert len(decisions) >= 1
    assert decisions[0]["reason"] == "allowed"


def test_rewrite_requires_approval_then_approve_flow() -> None:
    client = _client(storage_backend="memory", approval_threshold_chars=5)
    create = client.post("/v1/rewrite/artifact", json={"text": "approval smoke payload"})
    assert create.status_code == 409
    assert create.json()["error"]["code"] == "policy_denied:approval_required"

    pending = client.get("/v1/policy/approvals/pending", params={"limit": 10})
    assert pending.status_code == 200
    rows = pending.json()
    assert len(rows) >= 1
    approval_id = rows[0]["approval_id"]
    session_id = rows[0]["session_id"]
    assert rows[0]["status"] == "pending"

    session = client.get(f"/v1/rewrite/sessions/{session_id}")
    assert session.status_code == 200
    body = session.json()
    assert body["status"] == "awaiting_approval"
    assert len(body["artifacts"]) == 0
    assert len(body["receipts"]) == 0
    assert any(step["state"] == "waiting_approval" for step in body["steps"])

    approve = client.post(
        f"/v1/policy/approvals/{approval_id}/approve",
        json={"decided_by": "smoke-user", "reason": "approved in test"},
    )
    assert approve.status_code == 200
    assert approve.json()["decision"] == "approved"

    history = client.get("/v1/policy/approvals/history", params={"session_id": session_id, "limit": 10})
    assert history.status_code == 200
    assert any(row["approval_id"] == approval_id and row["decision"] == "approved" for row in history.json())

    session_after = client.get(f"/v1/rewrite/sessions/{session_id}")
    assert session_after.status_code == 200
    body_after = session_after.json()
    assert body_after["status"] == "approved_pending_execution"
    assert any(step["state"] == "queued" for step in body_after["steps"])


def test_rewrite_requires_approval_then_expire_flow() -> None:
    client = _client(storage_backend="memory", approval_threshold_chars=5)
    create = client.post("/v1/rewrite/artifact", json={"text": "expire smoke payload"})
    assert create.status_code == 409
    pending = client.get("/v1/policy/approvals/pending", params={"limit": 10})
    assert pending.status_code == 200
    approval_id = pending.json()[0]["approval_id"]
    session_id = pending.json()[0]["session_id"]

    expired = client.post(
        f"/v1/policy/approvals/{approval_id}/expire",
        json={"decided_by": "smoke-user", "reason": "expired in test"},
    )
    assert expired.status_code == 200
    assert expired.json()["decision"] == "expired"

    pending_after = client.get("/v1/policy/approvals/pending", params={"limit": 10})
    assert pending_after.status_code == 200
    assert all(row["approval_id"] != approval_id for row in pending_after.json())

    session_after = client.get(f"/v1/rewrite/sessions/{session_id}")
    assert session_after.status_code == 200
    assert session_after.json()["status"] == "blocked"


def test_rewrite_blocked_policy_flow_has_error_envelope() -> None:
    client = _client(storage_backend="memory")
    blocked = client.post("/v1/rewrite/artifact", json={"text": "x" * 20001})
    assert blocked.status_code == 403
    body = blocked.json()
    assert body["error"]["code"] == "policy_denied:input_too_large"
    assert body["error"]["correlation_id"]


def test_observation_and_delivery_flow() -> None:
    client = _client(storage_backend="memory")

    obs = client.post(
        "/v1/observations/ingest",
        json={
            "principal_id": "exec-1",
            "channel": "email",
            "event_type": "thread.opened",
            "payload": {"subject": "Board prep"},
        },
    )
    assert obs.status_code == 200
    observation_id = obs.json()["observation_id"]

    recent = client.get("/v1/observations/recent", params={"limit": 10})
    assert recent.status_code == 200
    assert any(r["observation_id"] == observation_id for r in recent.json())

    queued = client.post(
        "/v1/delivery/outbox",
        json={"channel": "slack", "recipient": "U1", "content": "Draft ready", "metadata": {"priority": "high"}},
    )
    assert queued.status_code == 200
    delivery_id = queued.json()["delivery_id"]

    pending = client.get("/v1/delivery/outbox/pending", params={"limit": 10})
    assert pending.status_code == 200
    assert any(r["delivery_id"] == delivery_id for r in pending.json())

    sent = client.post(f"/v1/delivery/outbox/{delivery_id}/sent")
    assert sent.status_code == 200
    assert sent.json()["status"] == "sent"


def test_telegram_adapter_ingest() -> None:
    client = _client(storage_backend="memory")
    resp = client.post(
        "/v1/channels/telegram/ingest",
        json={
            "update": {
                "message": {
                    "chat": {"id": 42},
                    "text": "hello",
                    "message_id": 7,
                    "date": 123,
                }
            }
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["channel"] == "telegram"
    assert body["event_type"] == "telegram.message"


def test_auth_allow_and_deny() -> None:
    token = "secret-token"
    client = _client(storage_backend="memory", auth_token=token)

    denied = client.get("/v1/observations/recent")
    assert denied.status_code == 401
    assert denied.json()["error"]["code"] == "auth_required"

    allowed = client.get("/v1/observations/recent", headers=_headers(token))
    assert allowed.status_code == 200

    health = client.get("/health")
    assert health.status_code == 200


def test_ready_fails_when_postgres_backend_without_database_url() -> None:
    client = _client(storage_backend="postgres", database_url="")
    ready = client.get("/health/ready")
    assert ready.status_code == 503
    assert ready.json()["error"]["code"].startswith("not_ready:")
