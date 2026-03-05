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
    assert "plan_compiled" in event_names
    assert "policy_decision" in event_names
    assert len(body["steps"]) >= 1
    assert body["steps"][0]["state"] in {"completed", "running", "blocked", "waiting_approval"}
    assert body["steps"][0]["input_json"]["plan_step_key"]
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
            "source_id": "gmail:account-1",
            "external_id": "msg-1",
            "dedupe_key": "obs-gmail-msg-1",
            "auth_context_json": {"scope": "mail.readonly"},
            "raw_payload_uri": "s3://bucket/raw/msg-1.json",
        },
    )
    assert obs.status_code == 200
    observation_id = obs.json()["observation_id"]
    assert obs.json()["dedupe_key"] == "obs-gmail-msg-1"

    recent = client.get("/v1/observations/recent", params={"limit": 10})
    assert recent.status_code == 200
    assert any(r["observation_id"] == observation_id for r in recent.json())

    obs_dupe = client.post(
        "/v1/observations/ingest",
        json={
            "principal_id": "exec-1",
            "channel": "email",
            "event_type": "thread.opened",
            "payload": {"subject": "Board prep"},
            "source_id": "gmail:account-1",
            "external_id": "msg-1",
            "dedupe_key": "obs-gmail-msg-1",
        },
    )
    assert obs_dupe.status_code == 200
    assert obs_dupe.json()["observation_id"] == observation_id

    queued = client.post(
        "/v1/delivery/outbox",
        json={
            "channel": "slack",
            "recipient": "U1",
            "content": "Draft ready",
            "metadata": {"priority": "high"},
            "idempotency_key": "delivery-msg-1",
        },
    )
    assert queued.status_code == 200
    delivery_id = queued.json()["delivery_id"]
    assert queued.json()["idempotency_key"] == "delivery-msg-1"

    queued_dupe = client.post(
        "/v1/delivery/outbox",
        json={
            "channel": "slack",
            "recipient": "U1",
            "content": "Draft ready duplicate",
            "metadata": {"priority": "high"},
            "idempotency_key": "delivery-msg-1",
        },
    )
    assert queued_dupe.status_code == 200
    assert queued_dupe.json()["delivery_id"] == delivery_id

    failed = client.post(
        f"/v1/delivery/outbox/{delivery_id}/failed",
        json={"error": "temporary channel error", "retry_in_seconds": 0, "dead_letter": False},
    )
    assert failed.status_code == 200
    assert failed.json()["status"] == "retry"
    assert failed.json()["attempt_count"] == 1
    assert failed.json()["last_error"] == "temporary channel error"

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


def test_tool_registry_and_connector_bindings_flow() -> None:
    client = _client(storage_backend="memory")

    tool = client.post(
        "/v1/tools/registry",
        json={
            "tool_name": "email.send",
            "version": "v1",
            "input_schema_json": {"type": "object", "properties": {"to": {"type": "string"}}},
            "output_schema_json": {"type": "object"},
            "policy_json": {"risk": "medium"},
            "allowed_channels": ["email", "slack"],
            "approval_default": "manager",
            "enabled": True,
        },
    )
    assert tool.status_code == 200
    assert tool.json()["tool_name"] == "email.send"

    listed_tools = client.get("/v1/tools/registry", params={"limit": 10})
    assert listed_tools.status_code == 200
    assert any(row["tool_name"] == "email.send" for row in listed_tools.json())

    binding = client.post(
        "/v1/connectors/bindings",
        json={
            "principal_id": "exec-1",
            "connector_name": "gmail",
            "external_account_ref": "acct-1",
            "scope_json": {"scopes": ["mail.readonly"]},
            "auth_metadata_json": {"provider": "google"},
            "status": "enabled",
        },
    )
    assert binding.status_code == 200
    binding_id = binding.json()["binding_id"]

    listed_bindings = client.get("/v1/connectors/bindings", params={"principal_id": "exec-1", "limit": 10})
    assert listed_bindings.status_code == 200
    assert any(row["binding_id"] == binding_id for row in listed_bindings.json())

    disabled = client.post(
        f"/v1/connectors/bindings/{binding_id}/status",
        json={"status": "disabled"},
    )
    assert disabled.status_code == 200
    assert disabled.json()["status"] == "disabled"


def test_task_contracts_flow_and_rewrite_compilation() -> None:
    client = _client(storage_backend="memory", approval_threshold_chars=20000)

    created = client.post(
        "/v1/tasks/contracts",
        json={
            "task_key": "rewrite_text",
            "deliverable_type": "rewrite_note",
            "default_risk_class": "low",
            "default_approval_class": "manager",
            "allowed_tools": ["rewrite_store"],
            "evidence_requirements": [],
            "memory_write_policy": "reviewed_only",
            "budget_policy_json": {"class": "low"},
        },
    )
    assert created.status_code == 200
    assert created.json()["task_key"] == "rewrite_text"

    listed = client.get("/v1/tasks/contracts", params={"limit": 10})
    assert listed.status_code == 200
    assert any(row["task_key"] == "rewrite_text" for row in listed.json())

    fetched = client.get("/v1/tasks/contracts/rewrite_text")
    assert fetched.status_code == 200
    assert fetched.json()["default_approval_class"] == "manager"

    compiled = client.post(
        "/v1/plans/compile",
        json={"task_key": "rewrite_text", "principal_id": "exec-1", "goal": "rewrite this"},
    )
    assert compiled.status_code == 200
    assert compiled.json()["intent"]["task_type"] == "rewrite_text"
    assert compiled.json()["plan"]["steps"][0]["approval_required"] is True

    rewrite = client.post("/v1/rewrite/artifact", json={"text": "short rewrite input"})
    assert rewrite.status_code == 409
    assert rewrite.json()["error"]["code"] == "policy_denied:approval_required"


def test_memory_candidate_promotion_flow() -> None:
    client = _client(storage_backend="memory")

    staged = client.post(
        "/v1/memory/candidates",
        json={
            "principal_id": "exec-1",
            "category": "stakeholder_pref",
            "summary": "CEO prefers concise updates",
            "fact_json": {"tone": "concise"},
            "source_session_id": "session-1",
            "source_event_id": "event-1",
            "source_step_id": "step-1",
            "confidence": 0.72,
            "sensitivity": "internal",
        },
    )
    assert staged.status_code == 200
    candidate_id = staged.json()["candidate_id"]
    assert staged.json()["status"] == "pending"

    listed_candidates = client.get("/v1/memory/candidates", params={"limit": 10, "status": "pending"})
    assert listed_candidates.status_code == 200
    assert any(row["candidate_id"] == candidate_id for row in listed_candidates.json())

    promoted = client.post(
        f"/v1/memory/candidates/{candidate_id}/promote",
        json={"reviewer": "operator-1", "sharing_policy": "private"},
    )
    assert promoted.status_code == 200
    promoted_body = promoted.json()
    assert promoted_body["candidate"]["status"] == "promoted"
    item_id = promoted_body["item"]["item_id"]
    assert promoted_body["item"]["provenance_json"]["candidate_id"] == candidate_id

    listed_items = client.get("/v1/memory/items", params={"limit": 10, "principal_id": "exec-1"})
    assert listed_items.status_code == 200
    assert any(row["item_id"] == item_id for row in listed_items.json())

    fetched_item = client.get(f"/v1/memory/items/{item_id}")
    assert fetched_item.status_code == 200
    assert fetched_item.json()["item_id"] == item_id


def test_memory_entities_relationships_flow() -> None:
    client = _client(storage_backend="memory")

    executive = client.post(
        "/v1/memory/entities",
        json={
            "principal_id": "exec-1",
            "entity_type": "person",
            "canonical_name": "Alex Executive",
            "attributes_json": {"role": "executive"},
            "confidence": 0.9,
            "status": "active",
        },
    )
    assert executive.status_code == 200
    executive_id = executive.json()["entity_id"]

    stakeholder = client.post(
        "/v1/memory/entities",
        json={
            "principal_id": "exec-1",
            "entity_type": "person",
            "canonical_name": "Sam Stakeholder",
            "attributes_json": {"role": "board_member"},
            "confidence": 0.88,
            "status": "active",
        },
    )
    assert stakeholder.status_code == 200
    stakeholder_id = stakeholder.json()["entity_id"]

    relationship = client.post(
        "/v1/memory/relationships",
        json={
            "principal_id": "exec-1",
            "from_entity_id": executive_id,
            "to_entity_id": stakeholder_id,
            "relationship_type": "reports_to",
            "attributes_json": {"strength": "high"},
            "confidence": 0.75,
        },
    )
    assert relationship.status_code == 200
    relationship_id = relationship.json()["relationship_id"]

    listed_entities = client.get("/v1/memory/entities", params={"limit": 10, "principal_id": "exec-1"})
    assert listed_entities.status_code == 200
    assert any(row["entity_id"] == executive_id for row in listed_entities.json())

    fetched_entity = client.get(f"/v1/memory/entities/{executive_id}")
    assert fetched_entity.status_code == 200
    assert fetched_entity.json()["canonical_name"] == "Alex Executive"

    listed_relationships = client.get("/v1/memory/relationships", params={"limit": 10, "principal_id": "exec-1"})
    assert listed_relationships.status_code == 200
    assert any(row["relationship_id"] == relationship_id for row in listed_relationships.json())

    fetched_relationship = client.get(f"/v1/memory/relationships/{relationship_id}")
    assert fetched_relationship.status_code == 200
    assert fetched_relationship.json()["relationship_type"] == "reports_to"


def test_memory_commitments_principal_scope_flow() -> None:
    client = _client(storage_backend="memory")

    created = client.post(
        "/v1/memory/commitments",
        json={
            "principal_id": "exec-1",
            "title": "Send board follow-up",
            "details": "Draft and send by Friday",
            "status": "open",
            "priority": "high",
            "due_at": "2026-03-06T10:00:00+00:00",
            "source_json": {"source": "manual"},
        },
    )
    assert created.status_code == 200
    commitment_id = created.json()["commitment_id"]

    listed = client.get("/v1/memory/commitments", params={"principal_id": "exec-1", "limit": 10})
    assert listed.status_code == 200
    assert any(row["commitment_id"] == commitment_id for row in listed.json())

    fetched = client.get(f"/v1/memory/commitments/{commitment_id}", params={"principal_id": "exec-1"})
    assert fetched.status_code == 200
    assert fetched.json()["title"] == "Send board follow-up"

    wrong_scope = client.get(f"/v1/memory/commitments/{commitment_id}", params={"principal_id": "exec-2"})
    assert wrong_scope.status_code == 404
    assert wrong_scope.json()["error"]["code"] == "commitment_not_found"


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
