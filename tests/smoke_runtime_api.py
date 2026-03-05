from __future__ import annotations

import os

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient


def _client() -> TestClient:
    os.environ["EA_LEDGER_BACKEND"] = "memory"
    from app.api.app import create_app

    return TestClient(create_app())


def test_rewrite_and_policy_audit_flow() -> None:
    client = _client()
    create = client.post("/v1/rewrite/artifact", json={"text": "smoke"})
    assert create.status_code == 200
    payload = create.json()
    session_id = payload["execution_session_id"]

    session = client.get(f"/v1/rewrite/sessions/{session_id}")
    assert session.status_code == 200
    event_names = [e["name"] for e in session.json()["events"]]
    assert "policy_decision" in event_names

    policy = client.get("/v1/policy/decisions/recent", params={"session_id": session_id, "limit": 5})
    assert policy.status_code == 200
    decisions = policy.json()
    assert len(decisions) >= 1
    assert decisions[0]["reason"] == "allowed"


def test_rewrite_blocked_policy_flow() -> None:
    client = _client()
    blocked = client.post("/v1/rewrite/artifact", json={"text": "x" * 20001})
    assert blocked.status_code == 403
    assert blocked.json()["detail"] == "policy_denied:input_too_large"


def test_observation_and_delivery_flow() -> None:
    client = _client()

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
    client = _client()
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
