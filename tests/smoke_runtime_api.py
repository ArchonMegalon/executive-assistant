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
    principal_id: str = "exec-1",
) -> TestClient:
    os.environ["EA_STORAGE_BACKEND"] = storage_backend
    os.environ.pop("EA_LEDGER_BACKEND", None)
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

    client = TestClient(create_app())
    if principal_id:
        client.headers.update({"X-EA-Principal-ID": principal_id})
    return client


def _headers(token: str = "", principal_id: str = "") -> dict[str, str]:
    headers: dict[str, str] = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if principal_id:
        headers["X-EA-Principal-ID"] = principal_id
    return headers


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
    artifact_id = payload["artifact_id"]
    session_id = payload["execution_session_id"]

    session = client.get(f"/v1/rewrite/sessions/{session_id}")
    assert session.status_code == 200
    body = session.json()
    event_names = [e["name"] for e in body["events"]]
    assert "plan_compiled" in event_names
    assert "policy_decision" in event_names
    assert "input_prepared" in event_names
    assert "tool_execution_completed" in event_names
    assert "step_enqueued" in event_names
    assert "queue_item_completed" in event_names
    assert len(body["steps"]) >= 2
    assert body["steps"][0]["input_json"]["plan_step_key"] == "step_input_prepare"
    assert body["steps"][1]["input_json"]["plan_step_key"] in {"step_artifact_save", "step_rewrite_fallback"}
    assert all(step["state"] in {"completed", "running", "blocked", "waiting_approval", "queued"} for step in body["steps"])
    assert len(body["queue_items"]) >= 2
    assert all(item["state"] == "done" for item in body["queue_items"])
    assert len(body["receipts"]) >= 1
    receipt_id = body["receipts"][0]["receipt_id"]
    assert body["artifacts"][0]["artifact_id"] == payload["artifact_id"]
    assert len(body["run_costs"]) >= 1
    cost_id = body["run_costs"][0]["cost_id"]

    fetched_artifact = client.get(f"/v1/rewrite/artifacts/{artifact_id}")
    assert fetched_artifact.status_code == 200
    assert fetched_artifact.json()["artifact_id"] == artifact_id
    assert fetched_artifact.json()["execution_session_id"] == session_id
    assert fetched_artifact.json()["content"] == "smoke"

    fetched_receipt = client.get(f"/v1/rewrite/receipts/{receipt_id}")
    assert fetched_receipt.status_code == 200
    assert fetched_receipt.json()["receipt_id"] == receipt_id
    assert fetched_receipt.json()["target_ref"] == artifact_id
    assert fetched_receipt.json()["receipt_json"]["handler_key"] == "artifact_repository"
    assert fetched_receipt.json()["receipt_json"]["invocation_contract"] == "tool.v1"

    fetched_cost = client.get(f"/v1/rewrite/run-costs/{cost_id}")
    assert fetched_cost.status_code == 200
    assert fetched_cost.json()["cost_id"] == cost_id
    assert fetched_cost.json()["model_name"] == "none"

    policy = client.get("/v1/policy/decisions/recent", params={"session_id": session_id, "limit": 5})
    assert policy.status_code == 200
    decisions = policy.json()
    assert len(decisions) >= 1
    assert decisions[0]["reason"] == "allowed"

    missing_artifact = client.get("/v1/rewrite/artifacts/not-a-real-artifact-id")
    assert missing_artifact.status_code == 404
    assert missing_artifact.json()["error"]["code"] == "artifact_not_found"

    missing_receipt = client.get("/v1/rewrite/receipts/not-a-real-receipt-id")
    assert missing_receipt.status_code == 404
    assert missing_receipt.json()["error"]["code"] == "receipt_not_found"

    missing_cost = client.get("/v1/rewrite/run-costs/not-a-real-cost-id")
    assert missing_cost.status_code == 404
    assert missing_cost.json()["error"]["code"] == "run_cost_not_found"


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
    assert len(body["queue_items"]) == 0
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
    event_names_after = [event["name"] for event in body_after["events"]]
    assert body_after["status"] == "completed"
    assert "input_prepared" in event_names_after
    assert "tool_execution_completed" in event_names_after
    assert "session_resumed_from_approval" in event_names_after
    assert "step_enqueued" in event_names_after
    assert "queue_item_completed" in event_names_after
    assert "session_completed" in event_names_after
    assert len(body_after["steps"]) >= 2
    assert all(step["state"] == "completed" for step in body_after["steps"])
    assert len(body_after["queue_items"]) == 2
    assert all(item["state"] == "done" for item in body_after["queue_items"])
    assert len(body_after["artifacts"]) == 1
    assert len(body_after["receipts"]) >= 1
    assert len(body_after["run_costs"]) >= 1


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


def test_policy_evaluate_external_send_requires_approval() -> None:
    client = _client(storage_backend="memory")
    resp = client.post(
        "/v1/policy/evaluate",
        json={
            "content": "Send the board update to the distribution list.",
            "tool_name": "connector.dispatch",
            "action_kind": "delivery.send",
            "channel": "email",
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["allow"] is True
    assert body["requires_approval"] is True
    assert body["reason"] == "allowed"
    assert body["tool_name"] == "connector.dispatch"
    assert body["action_kind"] == "delivery.send"
    assert body["channel"] == "email"
    assert body["allowed_tools"] == ["connector.dispatch"]


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
    assert any(row["tool_name"] == "artifact_repository" for row in listed_tools.json())
    assert any(row["tool_name"] == "connector.dispatch" for row in listed_tools.json())
    assert any(row["tool_name"] == "email.send" for row in listed_tools.json())

    binding = client.post(
        "/v1/connectors/bindings",
        json={
            "connector_name": "gmail",
            "external_account_ref": "acct-1",
            "scope_json": {"scopes": ["mail.readonly"]},
            "auth_metadata_json": {"provider": "google"},
            "status": "enabled",
        },
    )
    assert binding.status_code == 200
    binding_id = binding.json()["binding_id"]
    assert binding.json()["principal_id"] == "exec-1"

    listed_bindings = client.get("/v1/connectors/bindings", params={"limit": 10})
    assert listed_bindings.status_code == 200
    assert any(row["binding_id"] == binding_id for row in listed_bindings.json())

    executed = client.post(
        "/v1/tools/execute",
        json={
            "tool_name": "connector.dispatch",
            "action_kind": "delivery.send",
            "payload_json": {
                "binding_id": binding_id,
                "channel": "email",
                "recipient": "ops@example.com",
                "content": "Queued from tool runtime",
                "metadata": {"source": "tool-execute"},
                "idempotency_key": "tool-dispatch-1",
            },
        },
    )
    assert executed.status_code == 200
    assert executed.json()["tool_name"] == "connector.dispatch"
    assert executed.json()["output_json"]["status"] == "queued"
    assert executed.json()["output_json"]["binding_id"] == binding_id
    assert executed.json()["receipt_json"]["handler_key"] == "connector.dispatch"
    assert executed.json()["receipt_json"]["invocation_contract"] == "tool.v1"
    pending_after_execute = client.get("/v1/delivery/outbox/pending", params={"limit": 10})
    assert pending_after_execute.status_code == 200
    assert any(row["delivery_id"] == executed.json()["target_ref"] for row in pending_after_execute.json())

    execute_mismatch = client.post(
        "/v1/tools/execute",
        json={
            "tool_name": "connector.dispatch",
            "action_kind": "delivery.send",
            "payload_json": {
                "binding_id": binding_id,
                "channel": "email",
                "recipient": "ops@example.com",
                "content": "Should not queue",
            },
        },
        headers=_headers(principal_id="exec-2"),
    )
    assert execute_mismatch.status_code == 403
    assert execute_mismatch.json()["error"]["code"] == "principal_scope_mismatch"

    mismatch = client.get("/v1/connectors/bindings", params={"principal_id": "exec-2", "limit": 10})
    assert mismatch.status_code == 403
    assert mismatch.json()["error"]["code"] == "principal_scope_mismatch"

    foreign_status = client.post(
        f"/v1/connectors/bindings/{binding_id}/status",
        json={"status": "disabled"},
        headers=_headers(principal_id="exec-2"),
    )
    assert foreign_status.status_code == 404
    assert foreign_status.json()["error"]["code"] == "binding_not_found"

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
            "allowed_tools": ["artifact_repository"],
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
    assert len(compiled.json()["plan"]["steps"]) == 2
    assert compiled.json()["plan"]["steps"][0]["step_key"] == "step_input_prepare"
    assert compiled.json()["plan"]["steps"][1]["tool_name"] == "artifact_repository"
    assert compiled.json()["plan"]["steps"][1]["approval_required"] is True

    rewrite = client.post("/v1/rewrite/artifact", json={"text": "short rewrite input"})
    assert rewrite.status_code == 409
    assert rewrite.json()["error"]["code"] == "policy_denied:approval_required"


def test_memory_candidate_promotion_flow() -> None:
    client = _client(storage_backend="memory")

    staged = client.post(
        "/v1/memory/candidates",
        json={
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
    assert staged.json()["principal_id"] == "exec-1"
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

    listed_items = client.get("/v1/memory/items", params={"limit": 10})
    assert listed_items.status_code == 200
    assert any(row["item_id"] == item_id for row in listed_items.json())

    fetched_item = client.get(f"/v1/memory/items/{item_id}")
    assert fetched_item.status_code == 200
    assert fetched_item.json()["item_id"] == item_id

    mismatch = client.get("/v1/memory/items", params={"limit": 10, "principal_id": "exec-2"})
    assert mismatch.status_code == 403
    assert mismatch.json()["error"]["code"] == "principal_scope_mismatch"


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
    assert wrong_scope.status_code == 403
    assert wrong_scope.json()["error"]["code"] == "principal_scope_mismatch"


def test_memory_authority_bindings_principal_scope_flow() -> None:
    client = _client(storage_backend="memory")

    created = client.post(
        "/v1/memory/authority-bindings",
        json={
            "principal_id": "exec-1",
            "subject_ref": "assistant",
            "action_scope": "calendar.write",
            "approval_level": "manager",
            "channel_scope": ["email", "slack"],
            "policy_json": {"quiet_hours_enforced": True},
            "status": "active",
        },
    )
    assert created.status_code == 200
    binding_id = created.json()["binding_id"]

    listed = client.get("/v1/memory/authority-bindings", params={"principal_id": "exec-1", "limit": 10})
    assert listed.status_code == 200
    assert any(row["binding_id"] == binding_id for row in listed.json())

    fetched = client.get(f"/v1/memory/authority-bindings/{binding_id}", params={"principal_id": "exec-1"})
    assert fetched.status_code == 200
    assert fetched.json()["action_scope"] == "calendar.write"

    wrong_scope = client.get(f"/v1/memory/authority-bindings/{binding_id}", params={"principal_id": "exec-2"})
    assert wrong_scope.status_code == 403
    assert wrong_scope.json()["error"]["code"] == "principal_scope_mismatch"


def test_memory_delivery_preferences_principal_scope_flow() -> None:
    client = _client(storage_backend="memory")

    created = client.post(
        "/v1/memory/delivery-preferences",
        json={
            "principal_id": "exec-1",
            "channel": "email",
            "recipient_ref": "ceo@example.com",
            "cadence": "urgent_only",
            "quiet_hours_json": {"start": "22:00", "end": "07:00"},
            "format_json": {"style": "concise"},
            "status": "active",
        },
    )
    assert created.status_code == 200
    preference_id = created.json()["preference_id"]

    listed = client.get("/v1/memory/delivery-preferences", params={"principal_id": "exec-1", "limit": 10})
    assert listed.status_code == 200
    assert any(row["preference_id"] == preference_id for row in listed.json())

    fetched = client.get(f"/v1/memory/delivery-preferences/{preference_id}", params={"principal_id": "exec-1"})
    assert fetched.status_code == 200
    assert fetched.json()["channel"] == "email"

    wrong_scope = client.get(f"/v1/memory/delivery-preferences/{preference_id}", params={"principal_id": "exec-2"})
    assert wrong_scope.status_code == 403
    assert wrong_scope.json()["error"]["code"] == "principal_scope_mismatch"


def test_memory_follow_ups_principal_scope_flow() -> None:
    client = _client(storage_backend="memory")

    created = client.post(
        "/v1/memory/follow-ups",
        json={
            "principal_id": "exec-1",
            "stakeholder_ref": "ceo@example.com",
            "topic": "Board follow-up",
            "status": "open",
            "due_at": "2026-03-07T09:00:00+00:00",
            "channel_hint": "email",
            "notes": "Send summary after prep call",
            "source_json": {"source": "manual"},
        },
    )
    assert created.status_code == 200
    follow_up_id = created.json()["follow_up_id"]

    listed = client.get("/v1/memory/follow-ups", params={"principal_id": "exec-1", "limit": 10})
    assert listed.status_code == 200
    assert any(row["follow_up_id"] == follow_up_id for row in listed.json())

    fetched = client.get(f"/v1/memory/follow-ups/{follow_up_id}", params={"principal_id": "exec-1"})
    assert fetched.status_code == 200
    assert fetched.json()["topic"] == "Board follow-up"

    wrong_scope = client.get(f"/v1/memory/follow-ups/{follow_up_id}", params={"principal_id": "exec-2"})
    assert wrong_scope.status_code == 403
    assert wrong_scope.json()["error"]["code"] == "principal_scope_mismatch"


def test_memory_follow_up_rules_principal_scope_flow() -> None:
    client = _client(storage_backend="memory")

    created = client.post(
        "/v1/memory/follow-up-rules",
        json={
            "principal_id": "exec-1",
            "name": "Board reminder escalation",
            "trigger_kind": "deadline_risk",
            "channel_scope": ["email", "slack"],
            "delay_minutes": 120,
            "max_attempts": 3,
            "escalation_policy": "notify_exec",
            "conditions_json": {"priority": "high"},
            "action_json": {"action": "draft_follow_up"},
            "status": "active",
            "notes": "Escalate if follow-up is late",
        },
    )
    assert created.status_code == 200
    rule_id = created.json()["rule_id"]

    listed = client.get("/v1/memory/follow-up-rules", params={"principal_id": "exec-1", "limit": 10})
    assert listed.status_code == 200
    assert any(row["rule_id"] == rule_id for row in listed.json())

    fetched = client.get(f"/v1/memory/follow-up-rules/{rule_id}", params={"principal_id": "exec-1"})
    assert fetched.status_code == 200
    assert fetched.json()["name"] == "Board reminder escalation"

    wrong_scope = client.get(f"/v1/memory/follow-up-rules/{rule_id}", params={"principal_id": "exec-2"})
    assert wrong_scope.status_code == 403
    assert wrong_scope.json()["error"]["code"] == "principal_scope_mismatch"


def test_memory_interruption_budgets_principal_scope_flow() -> None:
    client = _client(storage_backend="memory")

    created = client.post(
        "/v1/memory/interruption-budgets",
        json={
            "principal_id": "exec-1",
            "scope": "workday",
            "window_kind": "daily",
            "budget_minutes": 120,
            "used_minutes": 30,
            "reset_at": "2026-03-07T00:00:00+00:00",
            "quiet_hours_json": {"start": "22:00", "end": "07:00"},
            "status": "active",
            "notes": "Keep non-critical interruptions bounded",
        },
    )
    assert created.status_code == 200
    budget_id = created.json()["budget_id"]

    listed = client.get("/v1/memory/interruption-budgets", params={"principal_id": "exec-1", "limit": 10})
    assert listed.status_code == 200
    assert any(row["budget_id"] == budget_id for row in listed.json())

    fetched = client.get(f"/v1/memory/interruption-budgets/{budget_id}", params={"principal_id": "exec-1"})
    assert fetched.status_code == 200
    assert fetched.json()["scope"] == "workday"

    wrong_scope = client.get(f"/v1/memory/interruption-budgets/{budget_id}", params={"principal_id": "exec-2"})
    assert wrong_scope.status_code == 403
    assert wrong_scope.json()["error"]["code"] == "principal_scope_mismatch"


def test_memory_deadline_windows_principal_scope_flow() -> None:
    client = _client(storage_backend="memory")

    created = client.post(
        "/v1/memory/deadline-windows",
        json={
            "principal_id": "exec-1",
            "title": "Board prep delivery window",
            "start_at": "2026-03-07T08:30:00+00:00",
            "end_at": "2026-03-07T10:00:00+00:00",
            "status": "open",
            "priority": "high",
            "notes": "Draft must be ready before board sync",
            "source_json": {"source": "manual"},
        },
    )
    assert created.status_code == 200
    window_id = created.json()["window_id"]

    listed = client.get("/v1/memory/deadline-windows", params={"principal_id": "exec-1", "limit": 10})
    assert listed.status_code == 200
    assert any(row["window_id"] == window_id for row in listed.json())

    fetched = client.get(f"/v1/memory/deadline-windows/{window_id}", params={"principal_id": "exec-1"})
    assert fetched.status_code == 200
    assert fetched.json()["title"] == "Board prep delivery window"

    wrong_scope = client.get(f"/v1/memory/deadline-windows/{window_id}", params={"principal_id": "exec-2"})
    assert wrong_scope.status_code == 403
    assert wrong_scope.json()["error"]["code"] == "principal_scope_mismatch"


def test_memory_stakeholders_principal_scope_flow() -> None:
    client = _client(storage_backend="memory")

    created = client.post(
        "/v1/memory/stakeholders",
        json={
            "principal_id": "exec-1",
            "display_name": "Sam Stakeholder",
            "channel_ref": "email:sam@example.com",
            "authority_level": "approver",
            "importance": "high",
            "response_cadence": "fast",
            "tone_pref": "diplomatic",
            "sensitivity": "confidential",
            "escalation_policy": "notify_exec",
            "open_loops_json": {"board_follow_up": "open"},
            "friction_points_json": {"scheduling": "tight"},
            "last_interaction_at": "2026-03-06T15:30:00+00:00",
            "status": "active",
            "notes": "Needs concise summaries",
        },
    )
    assert created.status_code == 200
    stakeholder_id = created.json()["stakeholder_id"]

    listed = client.get("/v1/memory/stakeholders", params={"principal_id": "exec-1", "limit": 10})
    assert listed.status_code == 200
    assert any(row["stakeholder_id"] == stakeholder_id for row in listed.json())

    fetched = client.get(f"/v1/memory/stakeholders/{stakeholder_id}", params={"principal_id": "exec-1"})
    assert fetched.status_code == 200
    assert fetched.json()["display_name"] == "Sam Stakeholder"

    wrong_scope = client.get(f"/v1/memory/stakeholders/{stakeholder_id}", params={"principal_id": "exec-2"})
    assert wrong_scope.status_code == 403
    assert wrong_scope.json()["error"]["code"] == "principal_scope_mismatch"


def test_memory_decision_windows_principal_scope_flow() -> None:
    client = _client(storage_backend="memory")

    created = client.post(
        "/v1/memory/decision-windows",
        json={
            "principal_id": "exec-1",
            "title": "Board response decision",
            "context": "Choose timing and channel for reply",
            "opens_at": "2026-03-06T08:00:00+00:00",
            "closes_at": "2026-03-06T12:00:00+00:00",
            "urgency": "high",
            "authority_required": "exec",
            "status": "open",
            "notes": "Needs decision before board prep",
            "source_json": {"source": "manual"},
        },
    )
    assert created.status_code == 200
    decision_window_id = created.json()["decision_window_id"]

    listed = client.get("/v1/memory/decision-windows", params={"principal_id": "exec-1", "limit": 10})
    assert listed.status_code == 200
    assert any(row["decision_window_id"] == decision_window_id for row in listed.json())

    fetched = client.get(
        f"/v1/memory/decision-windows/{decision_window_id}",
        params={"principal_id": "exec-1"},
    )
    assert fetched.status_code == 200
    assert fetched.json()["title"] == "Board response decision"

    wrong_scope = client.get(
        f"/v1/memory/decision-windows/{decision_window_id}",
        params={"principal_id": "exec-2"},
    )
    assert wrong_scope.status_code == 403
    assert wrong_scope.json()["error"]["code"] == "principal_scope_mismatch"


def test_memory_communication_policies_principal_scope_flow() -> None:
    client = _client(storage_backend="memory")

    created = client.post(
        "/v1/memory/communication-policies",
        json={
            "principal_id": "exec-1",
            "scope": "board_threads",
            "preferred_channel": "email",
            "tone": "concise_diplomatic",
            "max_length": 1200,
            "quiet_hours_json": {"start": "22:00", "end": "07:00"},
            "escalation_json": {"on_high_urgency": "notify_exec"},
            "status": "active",
            "notes": "Board-facing communication defaults",
        },
    )
    assert created.status_code == 200
    policy_id = created.json()["policy_id"]

    listed = client.get("/v1/memory/communication-policies", params={"principal_id": "exec-1", "limit": 10})
    assert listed.status_code == 200
    assert any(row["policy_id"] == policy_id for row in listed.json())

    fetched = client.get(f"/v1/memory/communication-policies/{policy_id}", params={"principal_id": "exec-1"})
    assert fetched.status_code == 200
    assert fetched.json()["scope"] == "board_threads"

    wrong_scope = client.get(f"/v1/memory/communication-policies/{policy_id}", params={"principal_id": "exec-2"})
    assert wrong_scope.status_code == 403
    assert wrong_scope.json()["error"]["code"] == "principal_scope_mismatch"


def test_memory_routes_use_default_principal_when_header_and_body_are_omitted() -> None:
    client = _client(storage_backend="memory", principal_id="")

    staged = client.post(
        "/v1/memory/candidates",
        json={
            "category": "stakeholder_pref",
            "summary": "Default principal candidate",
            "fact_json": {"channel": "email"},
        },
    )
    assert staged.status_code == 200
    assert staged.json()["principal_id"] == "local-user"

    listed = client.get("/v1/memory/candidates", params={"limit": 10})
    assert listed.status_code == 200
    assert any(row["candidate_id"] == staged.json()["candidate_id"] for row in listed.json())


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
