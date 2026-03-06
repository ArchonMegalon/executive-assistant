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
    assert "policy_step_completed" in event_names
    assert "tool_execution_completed" in event_names
    assert "step_enqueued" in event_names
    assert "queue_item_completed" in event_names
    assert len(body["steps"]) >= 3
    assert body["steps"][0]["input_json"]["plan_step_key"] == "step_input_prepare"
    assert body["steps"][1]["input_json"]["plan_step_key"] == "step_policy_evaluate"
    assert body["steps"][2]["input_json"]["plan_step_key"] == "step_artifact_save"
    assert body["human_task_assignment_history"] == []
    assert all(step["state"] in {"completed", "running", "blocked", "waiting_approval", "queued"} for step in body["steps"])
    assert len(body["queue_items"]) >= 3
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
    assert create.status_code == 202
    assert create.json()["status"] == "awaiting_approval"
    assert create.json()["next_action"] == "poll_or_subscribe"

    pending = client.get("/v1/policy/approvals/pending", params={"limit": 10})
    assert pending.status_code == 200
    rows = pending.json()
    assert len(rows) >= 1
    approval_id = create.json()["approval_id"]
    session_id = create.json()["session_id"]
    assert any(row["approval_id"] == approval_id and row["session_id"] == session_id for row in rows)
    assert rows[0]["status"] == "pending"

    session = client.get(f"/v1/rewrite/sessions/{session_id}")
    assert session.status_code == 200
    body = session.json()
    assert body["status"] == "awaiting_approval"
    assert len(body["artifacts"]) == 0
    assert len(body["queue_items"]) == 2
    assert all(item["state"] == "done" for item in body["queue_items"])
    assert len(body["receipts"]) == 0
    assert body["steps"][0]["state"] == "completed"
    assert body["steps"][1]["state"] == "completed"
    assert body["steps"][2]["state"] == "waiting_approval"

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
    assert "policy_step_completed" in event_names_after
    assert "session_resumed_from_approval" in event_names_after
    assert "step_enqueued" in event_names_after
    assert "queue_item_completed" in event_names_after
    assert "session_completed" in event_names_after
    assert len(body_after["steps"]) >= 3
    assert all(step["state"] == "completed" for step in body_after["steps"])
    assert len(body_after["queue_items"]) == 3
    assert all(item["state"] == "done" for item in body_after["queue_items"])
    assert len(body_after["artifacts"]) == 1
    assert len(body_after["receipts"]) >= 1
    assert len(body_after["run_costs"]) >= 1


def test_rewrite_requires_approval_then_expire_flow() -> None:
    client = _client(storage_backend="memory", approval_threshold_chars=5)
    create = client.post("/v1/rewrite/artifact", json={"text": "expire smoke payload"})
    assert create.status_code == 202
    pending = client.get("/v1/policy/approvals/pending", params={"limit": 10})
    assert pending.status_code == 200
    approval_id = create.json()["approval_id"]
    session_id = create.json()["session_id"]

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


def test_human_task_flow_and_session_projection() -> None:
    client = _client(storage_backend="memory")
    create = client.post("/v1/rewrite/artifact", json={"text": "human task seed"})
    assert create.status_code == 200
    session_id = create.json()["execution_session_id"]

    session = client.get(f"/v1/rewrite/sessions/{session_id}")
    assert session.status_code == 200
    steps = session.json()["steps"]
    assert len(steps) >= 2
    step_id = steps[-1]["step_id"]

    operator_profile = client.post(
        "/v1/human/tasks/operators",
        json={
            "operator_id": "operator-specialist",
            "display_name": "Senior Comms Reviewer",
            "roles": ["communications_reviewer"],
            "skill_tags": ["tone", "accuracy", "stakeholder_sensitivity"],
            "trust_tier": "senior",
            "status": "active",
            "notes": "Specialist in external executive communication.",
        },
    )
    assert operator_profile.status_code == 200
    assert operator_profile.json()["trust_tier"] == "senior"

    operator_low = client.post(
        "/v1/human/tasks/operators",
        json={
            "operator_id": "operator-junior",
            "display_name": "Junior Reviewer",
            "roles": ["communications_reviewer"],
            "skill_tags": ["tone"],
            "trust_tier": "standard",
            "status": "active",
        },
    )
    assert operator_low.status_code == 200

    created = client.post(
        "/v1/human/tasks",
        json={
            "session_id": session_id,
            "step_id": step_id,
            "task_type": "communications_review",
            "role_required": "communications_reviewer",
            "brief": "Review the draft before external send.",
            "authority_required": "send_on_behalf_review",
            "why_human": "External executive communication needs human tone review.",
            "quality_rubric_json": {"checks": ["tone", "accuracy", "stakeholder_sensitivity"]},
            "input_json": {"artifact_id": create.json()["artifact_id"]},
            "desired_output_json": {"format": "review_packet"},
            "priority": "high",
            "sla_due_at": "2000-01-01T00:00:00+00:00",
            "resume_session_on_return": True,
        },
    )
    assert created.status_code == 200
    task = created.json()
    task_id = task["human_task_id"]
    assert task["status"] == "pending"
    assert task["assignment_state"] == "unassigned"
    assert task["assignment_source"] == ""
    assert task["assigned_at"] is None
    assert task["assigned_by_actor_id"] == ""
    assert task["last_transition_event_name"] == "human_task_created"
    assert task["last_transition_at"]
    assert task["last_transition_assignment_state"] == "unassigned"
    assert task["last_transition_operator_id"] == ""
    assert task["last_transition_assignment_source"] == ""
    assert task["last_transition_by_actor_id"] == ""
    assert task["step_id"] == step_id
    assert task["resume_session_on_return"] is True
    assert task["authority_required"] == "send_on_behalf_review"
    assert task["why_human"] == "External executive communication needs human tone review."
    assert task["quality_rubric_json"]["checks"][0] == "tone"
    assert task["routing_hints_json"]["required_skill_tags"] == ["accuracy", "stakeholder_sensitivity", "tone"]
    assert task["routing_hints_json"]["required_trust_tier"] == "senior"
    assert task["routing_hints_json"]["suggested_operator_ids"][0] == "operator-specialist"
    assert task["routing_hints_json"]["auto_assign_operator_id"] == "operator-specialist"

    session_waiting = client.get(f"/v1/rewrite/sessions/{session_id}")
    assert session_waiting.status_code == 200
    waiting_body = session_waiting.json()
    waiting_events = [event["name"] for event in waiting_body["events"]]
    assert waiting_body["status"] == "awaiting_human"
    assert "session_paused_for_human_task" in waiting_events
    assert any(step["step_id"] == step_id and step["state"] == "waiting_human" for step in waiting_body["steps"])
    waiting_history = waiting_body["human_task_assignment_history"]
    assert [row["event_name"] for row in waiting_history] == ["human_task_created"]
    waiting_task = next(row for row in waiting_body["human_tasks"] if row["human_task_id"] == task_id)
    assert waiting_task["routing_hints_json"]["recommended_operator_id"] == "operator-specialist"
    assert waiting_task["routing_hints_json"]["auto_assign_operator_id"] == "operator-specialist"
    assert waiting_task["last_transition_event_name"] == "human_task_created"
    assert waiting_task["last_transition_assignment_state"] == "unassigned"
    assert waiting_task["last_transition_operator_id"] == ""

    listed = client.get("/v1/human/tasks", params={"limit": 10})
    assert listed.status_code == 200
    assert any(row["human_task_id"] == task_id for row in listed.json())

    role_filtered = client.get(
        "/v1/human/tasks",
        params={"limit": 10, "role_required": "communications_reviewer", "overdue_only": True},
    )
    assert role_filtered.status_code == 200
    assert any(row["human_task_id"] == task_id for row in role_filtered.json())

    backlog = client.get(
        "/v1/human/tasks/backlog",
        params={"limit": 10, "role_required": "communications_reviewer", "overdue_only": True},
    )
    assert backlog.status_code == 200
    assert any(row["human_task_id"] == task_id for row in backlog.json())

    unassigned = client.get(
        "/v1/human/tasks/unassigned",
        params={"limit": 10, "role_required": "communications_reviewer", "overdue_only": True},
    )
    assert unassigned.status_code == 200
    assert any(row["human_task_id"] == task_id for row in unassigned.json())

    assigned = client.post(f"/v1/human/tasks/{task_id}/assign", json={})
    assert assigned.status_code == 200
    assert assigned.json()["status"] == "pending"
    assert assigned.json()["assignment_state"] == "assigned"
    assert assigned.json()["assigned_operator_id"] == "operator-specialist"
    assert assigned.json()["assignment_source"] == "recommended"
    assert assigned.json()["assigned_at"]
    assert assigned.json()["assigned_by_actor_id"] == "exec-1"
    assert assigned.json()["last_transition_event_name"] == "human_task_assigned"
    assert assigned.json()["last_transition_at"]
    assert assigned.json()["last_transition_assignment_state"] == "assigned"
    assert assigned.json()["last_transition_operator_id"] == "operator-specialist"
    assert assigned.json()["last_transition_assignment_source"] == "recommended"
    assert assigned.json()["last_transition_by_actor_id"] == "exec-1"

    assigned_backlog = client.get(
        "/v1/human/tasks/backlog",
        params={
            "limit": 10,
            "role_required": "communications_reviewer",
            "overdue_only": True,
            "assignment_state": "assigned",
        },
    )
    assert assigned_backlog.status_code == 200
    assert any(row["human_task_id"] == task_id for row in assigned_backlog.json())

    unassigned_after = client.get(
        "/v1/human/tasks/unassigned",
        params={"limit": 10, "role_required": "communications_reviewer", "overdue_only": True},
    )
    assert unassigned_after.status_code == 200
    assert all(row["human_task_id"] != task_id for row in unassigned_after.json())

    operators = client.get("/v1/human/tasks/operators", params={"limit": 10})
    assert operators.status_code == 200
    assert any(row["operator_id"] == "operator-specialist" for row in operators.json())

    operator_backlog = client.get(
        "/v1/human/tasks/backlog",
        params={"limit": 10, "operator_id": "operator-specialist", "overdue_only": True},
    )
    assert operator_backlog.status_code == 200
    assert any(row["human_task_id"] == task_id for row in operator_backlog.json())

    operator_backlog_low = client.get(
        "/v1/human/tasks/backlog",
        params={"limit": 10, "operator_id": "operator-junior", "overdue_only": True},
    )
    assert operator_backlog_low.status_code == 200
    assert all(row["human_task_id"] != task_id for row in operator_backlog_low.json())

    mine_assigned = client.get("/v1/human/tasks/mine", params={"limit": 10, "operator_id": "operator-specialist"})
    assert mine_assigned.status_code == 200
    assert any(row["human_task_id"] == task_id for row in mine_assigned.json())

    reassigned = client.post(
        f"/v1/human/tasks/{task_id}/assign",
        json={"operator_id": "operator-junior"},
    )
    assert reassigned.status_code == 200
    assert reassigned.json()["status"] == "pending"
    assert reassigned.json()["assignment_state"] == "assigned"
    assert reassigned.json()["assigned_operator_id"] == "operator-junior"
    assert reassigned.json()["assignment_source"] == "manual"
    assert reassigned.json()["assigned_at"]
    assert reassigned.json()["assigned_by_actor_id"] == "exec-1"
    assert reassigned.json()["last_transition_event_name"] == "human_task_assigned"
    assert reassigned.json()["last_transition_assignment_state"] == "assigned"
    assert reassigned.json()["last_transition_operator_id"] == "operator-junior"
    assert reassigned.json()["last_transition_assignment_source"] == "manual"
    assert reassigned.json()["last_transition_by_actor_id"] == "exec-1"

    claimed = client.post(f"/v1/human/tasks/{task_id}/claim", json={"operator_id": "operator-junior"})
    assert claimed.status_code == 200
    assert claimed.json()["status"] == "claimed"
    assert claimed.json()["assignment_state"] == "claimed"
    assert claimed.json()["assignment_source"] == "manual"
    assert claimed.json()["assigned_at"]
    assert claimed.json()["assigned_by_actor_id"] == "operator-junior"
    assert claimed.json()["last_transition_event_name"] == "human_task_claimed"
    assert claimed.json()["last_transition_assignment_state"] == "claimed"
    assert claimed.json()["last_transition_operator_id"] == "operator-junior"
    assert claimed.json()["last_transition_assignment_source"] == "manual"
    assert claimed.json()["last_transition_by_actor_id"] == "operator-junior"

    operator_filtered = client.get(
        "/v1/human/tasks",
        params={"limit": 10, "assigned_operator_id": "operator-junior", "status": "claimed"},
    )
    assert operator_filtered.status_code == 200
    assert any(row["human_task_id"] == task_id for row in operator_filtered.json())

    mine = client.get("/v1/human/tasks/mine", params={"limit": 10, "operator_id": "operator-junior"})
    assert mine.status_code == 200
    assert any(row["human_task_id"] == task_id for row in mine.json())

    returned = client.post(
        f"/v1/human/tasks/{task_id}/return",
        json={
            "operator_id": "operator-junior",
            "resolution": "ready_for_send",
            "returned_payload_json": {"summary": "Reviewed and ready."},
            "provenance_json": {"review_mode": "human"},
        },
    )
    assert returned.status_code == 200
    assert returned.json()["status"] == "returned"
    assert returned.json()["assignment_state"] == "returned"
    assert returned.json()["assignment_source"] == "manual"
    assert returned.json()["assigned_at"]
    assert returned.json()["assigned_by_actor_id"] == "operator-junior"
    assert returned.json()["resolution"] == "ready_for_send"
    assert returned.json()["last_transition_event_name"] == "human_task_returned"
    assert returned.json()["last_transition_assignment_state"] == "returned"
    assert returned.json()["last_transition_operator_id"] == "operator-junior"
    assert returned.json()["last_transition_assignment_source"] == "manual"
    assert returned.json()["last_transition_by_actor_id"] == "operator-junior"

    fetched = client.get(f"/v1/human/tasks/{task_id}")
    assert fetched.status_code == 200
    assert fetched.json()["returned_payload_json"]["summary"] == "Reviewed and ready."
    assert fetched.json()["last_transition_event_name"] == "human_task_returned"
    assert fetched.json()["last_transition_assignment_state"] == "returned"
    assert fetched.json()["last_transition_operator_id"] == "operator-junior"

    history = client.get(f"/v1/human/tasks/{task_id}/assignment-history", params={"limit": 10})
    assert history.status_code == 200
    history_rows = history.json()
    assert [row["event_name"] for row in history_rows] == [
        "human_task_created",
        "human_task_assigned",
        "human_task_assigned",
        "human_task_claimed",
        "human_task_returned",
    ]
    assert [row["assigned_operator_id"] for row in history_rows] == [
        "",
        "operator-specialist",
        "operator-junior",
        "operator-junior",
        "operator-junior",
    ]
    assert history_rows[1]["assignment_source"] == "recommended"
    assert history_rows[1]["assigned_by_actor_id"] == "exec-1"
    assert history_rows[2]["assignment_source"] == "manual"
    assert history_rows[2]["assigned_by_actor_id"] == "exec-1"
    assert history_rows[3]["assigned_by_actor_id"] == "operator-junior"
    assert history_rows[4]["assigned_by_actor_id"] == "operator-junior"

    assigned_history = client.get(
        f"/v1/human/tasks/{task_id}/assignment-history",
        params={"limit": 10, "event_name": "human_task_assigned", "assigned_by_actor_id": "exec-1"},
    )
    assert assigned_history.status_code == 200
    assert [row["assigned_operator_id"] for row in assigned_history.json()] == [
        "operator-specialist",
        "operator-junior",
    ]

    returned_history = client.get(
        f"/v1/human/tasks/{task_id}/assignment-history",
        params={"limit": 10, "event_name": "human_task_returned", "assigned_operator_id": "operator-junior"},
    )
    assert returned_history.status_code == 200
    assert len(returned_history.json()) == 1
    assert returned_history.json()[0]["assigned_by_actor_id"] == "operator-junior"

    recommended_history = client.get(
        f"/v1/human/tasks/{task_id}/assignment-history",
        params={"limit": 10, "assignment_source": "recommended"},
    )
    assert recommended_history.status_code == 200
    recommended_rows = recommended_history.json()
    assert len(recommended_rows) == 1
    assert recommended_rows[0]["event_name"] == "human_task_assigned"
    assert recommended_rows[0]["assignment_source"] == "recommended"
    assert recommended_rows[0]["assigned_operator_id"] == "operator-specialist"

    session_after = client.get(f"/v1/rewrite/sessions/{session_id}")
    assert session_after.status_code == 200
    session_body = session_after.json()
    event_names = [event["name"] for event in session_body["events"]]
    assert session_body["status"] == "completed"
    assert "human_task_created" in event_names
    assert "human_task_assigned" in event_names
    assert "human_task_claimed" in event_names
    assert "human_task_returned" in event_names
    assert "session_resumed_from_human_task" in event_names
    assert [row["event_name"] for row in session_body["human_task_assignment_history"]] == [
        "human_task_created",
        "human_task_assigned",
        "human_task_assigned",
        "human_task_claimed",
        "human_task_returned",
    ]
    assert [row["assigned_operator_id"] for row in session_body["human_task_assignment_history"]] == [
        "",
        "operator-specialist",
        "operator-junior",
        "operator-junior",
        "operator-junior",
    ]
    assert any(
        row["human_task_id"] == task_id
        and row["status"] == "returned"
        and row["assignment_state"] == "returned"
        and row["assignment_source"] == "manual"
        and row["assigned_by_actor_id"] == "operator-junior"
        and row["last_transition_event_name"] == "human_task_returned"
        and row["last_transition_assignment_state"] == "returned"
        and row["last_transition_operator_id"] == "operator-junior"
        and row["last_transition_assignment_source"] == "manual"
        and row["last_transition_by_actor_id"] == "operator-junior"
        for row in session_body["human_tasks"]
    )
    session_manual = client.get(
        f"/v1/rewrite/sessions/{session_id}",
        params={"human_task_assignment_source": "manual"},
    )
    assert session_manual.status_code == 200
    manual_body = session_manual.json()
    assert len(manual_body["human_tasks"]) == 1
    assert manual_body["human_tasks"][0]["human_task_id"] == task_id
    assert [row["event_name"] for row in manual_body["human_task_assignment_history"]] == [
        "human_task_assigned",
        "human_task_claimed",
        "human_task_returned",
    ]
    resumed_step = next(step for step in session_body["steps"] if step["step_id"] == step_id)
    assert resumed_step["state"] == "completed"
    assert resumed_step["output_json"]["human_task_id"] == task_id


def test_human_task_sort_by_last_transition_desc() -> None:
    client = _client(storage_backend="memory")
    create = client.post("/v1/rewrite/artifact", json={"text": "sort seed"})
    assert create.status_code == 200
    session_id = create.json()["execution_session_id"]

    session = client.get(f"/v1/rewrite/sessions/{session_id}")
    assert session.status_code == 200
    step_id = session.json()["steps"][-1]["step_id"]

    older = client.post(
        "/v1/human/tasks",
        json={
            "session_id": session_id,
            "step_id": step_id,
            "task_type": "communications_review",
            "role_required": "communications_reviewer",
            "brief": "Older pending task.",
            "resume_session_on_return": False,
        },
    )
    assert older.status_code == 200
    older_task_id = older.json()["human_task_id"]

    newer = client.post(
        "/v1/human/tasks",
        json={
            "session_id": session_id,
            "step_id": step_id,
            "task_type": "communications_review",
            "role_required": "communications_reviewer",
            "brief": "Newer untouched task.",
            "resume_session_on_return": False,
        },
    )
    assert newer.status_code == 200
    newer_task_id = newer.json()["human_task_id"]

    assigned = client.post(f"/v1/human/tasks/{older_task_id}/assign", json={"operator_id": "operator-sorter"})
    assert assigned.status_code == 200
    assert assigned.json()["last_transition_event_name"] == "human_task_assigned"

    listed = client.get(
        "/v1/human/tasks",
        params={"status": "pending", "sort": "last_transition_desc", "limit": 10},
    )
    assert listed.status_code == 200
    listed_rows = [row for row in listed.json() if row["human_task_id"] in {older_task_id, newer_task_id}]
    assert [row["human_task_id"] for row in listed_rows[:2]] == [older_task_id, newer_task_id]
    assert listed_rows[0]["last_transition_event_name"] == "human_task_assigned"
    assert listed_rows[1]["last_transition_event_name"] == "human_task_created"

    backlog = client.get(
        "/v1/human/tasks/backlog",
        params={"sort": "last_transition_desc", "limit": 10},
    )
    assert backlog.status_code == 200
    backlog_rows = [row for row in backlog.json() if row["human_task_id"] in {older_task_id, newer_task_id}]
    assert [row["human_task_id"] for row in backlog_rows[:2]] == [older_task_id, newer_task_id]
    assert backlog_rows[0]["last_transition_event_name"] == "human_task_assigned"
    assert backlog_rows[1]["last_transition_event_name"] == "human_task_created"


def test_human_task_sort_by_created_asc_across_queue_views() -> None:
    client = _client(storage_backend="memory")
    create = client.post("/v1/rewrite/artifact", json={"text": "created asc seed"})
    assert create.status_code == 200
    session_id = create.json()["execution_session_id"]

    session = client.get(f"/v1/rewrite/sessions/{session_id}")
    assert session.status_code == 200
    step_id = session.json()["steps"][-1]["step_id"]

    oldest_unassigned = client.post(
        "/v1/human/tasks",
        json={
            "session_id": session_id,
            "step_id": step_id,
            "task_type": "communications_review",
            "role_required": "communications_reviewer",
            "brief": "Oldest unassigned task.",
            "resume_session_on_return": False,
        },
    )
    assert oldest_unassigned.status_code == 200
    oldest_unassigned_id = oldest_unassigned.json()["human_task_id"]

    older_mine = client.post(
        "/v1/human/tasks",
        json={
            "session_id": session_id,
            "step_id": step_id,
            "task_type": "communications_review",
            "role_required": "communications_reviewer",
            "brief": "Older assigned task.",
            "resume_session_on_return": False,
        },
    )
    assert older_mine.status_code == 200
    older_mine_id = older_mine.json()["human_task_id"]

    middle_unassigned = client.post(
        "/v1/human/tasks",
        json={
            "session_id": session_id,
            "step_id": step_id,
            "task_type": "communications_review",
            "role_required": "communications_reviewer",
            "brief": "Middle unassigned task.",
            "resume_session_on_return": False,
        },
    )
    assert middle_unassigned.status_code == 200
    middle_unassigned_id = middle_unassigned.json()["human_task_id"]

    newer_mine = client.post(
        "/v1/human/tasks",
        json={
            "session_id": session_id,
            "step_id": step_id,
            "task_type": "communications_review",
            "role_required": "communications_reviewer",
            "brief": "Newer assigned task.",
            "resume_session_on_return": False,
        },
    )
    assert newer_mine.status_code == 200
    newer_mine_id = newer_mine.json()["human_task_id"]

    older_assigned = client.post(f"/v1/human/tasks/{older_mine_id}/assign", json={"operator_id": "operator-sorter"})
    assert older_assigned.status_code == 200
    newer_assigned = client.post(f"/v1/human/tasks/{newer_mine_id}/assign", json={"operator_id": "operator-sorter"})
    assert newer_assigned.status_code == 200

    listed = client.get(
        "/v1/human/tasks",
        params={"status": "pending", "sort": "created_asc", "limit": 10},
    )
    assert listed.status_code == 200
    listed_rows = [
        row
        for row in listed.json()
        if row["human_task_id"] in {oldest_unassigned_id, older_mine_id, middle_unassigned_id, newer_mine_id}
    ]
    assert [row["human_task_id"] for row in listed_rows[:4]] == [
        oldest_unassigned_id,
        older_mine_id,
        middle_unassigned_id,
        newer_mine_id,
    ]

    backlog = client.get(
        "/v1/human/tasks/backlog",
        params={"sort": "created_asc", "limit": 10},
    )
    assert backlog.status_code == 200
    backlog_rows = [
        row
        for row in backlog.json()
        if row["human_task_id"] in {oldest_unassigned_id, older_mine_id, middle_unassigned_id, newer_mine_id}
    ]
    assert [row["human_task_id"] for row in backlog_rows[:4]] == [
        oldest_unassigned_id,
        older_mine_id,
        middle_unassigned_id,
        newer_mine_id,
    ]

    unassigned = client.get(
        "/v1/human/tasks/unassigned",
        params={"sort": "created_asc", "limit": 10},
    )
    assert unassigned.status_code == 200
    unassigned_rows = [
        row for row in unassigned.json() if row["human_task_id"] in {oldest_unassigned_id, middle_unassigned_id}
    ]
    assert [row["human_task_id"] for row in unassigned_rows[:2]] == [oldest_unassigned_id, middle_unassigned_id]

    mine = client.get(
        "/v1/human/tasks/mine",
        params={"operator_id": "operator-sorter", "status": "pending", "sort": "created_asc", "limit": 10},
    )
    assert mine.status_code == 200
    mine_rows = [row for row in mine.json() if row["human_task_id"] in {older_mine_id, newer_mine_id}]
    assert [row["human_task_id"] for row in mine_rows[:2]] == [older_mine_id, newer_mine_id]


def test_human_task_sort_by_priority_then_created_asc_across_queue_views() -> None:
    client = _client(storage_backend="memory")
    create = client.post("/v1/rewrite/artifact", json={"text": "priority sort seed"})
    assert create.status_code == 200
    session_id = create.json()["execution_session_id"]

    session = client.get(f"/v1/rewrite/sessions/{session_id}")
    assert session.status_code == 200
    step_id = session.json()["steps"][-1]["step_id"]

    oldest_normal = client.post(
        "/v1/human/tasks",
        json={
            "session_id": session_id,
            "step_id": step_id,
            "task_type": "communications_review",
            "role_required": "communications_reviewer",
            "brief": "Oldest normal task.",
            "priority": "normal",
            "resume_session_on_return": False,
        },
    )
    assert oldest_normal.status_code == 200
    oldest_normal_id = oldest_normal.json()["human_task_id"]

    older_high_mine = client.post(
        "/v1/human/tasks",
        json={
            "session_id": session_id,
            "step_id": step_id,
            "task_type": "communications_review",
            "role_required": "communications_reviewer",
            "brief": "Older high-priority assigned task.",
            "priority": "high",
            "resume_session_on_return": False,
        },
    )
    assert older_high_mine.status_code == 200
    older_high_mine_id = older_high_mine.json()["human_task_id"]

    middle_high_unassigned = client.post(
        "/v1/human/tasks",
        json={
            "session_id": session_id,
            "step_id": step_id,
            "task_type": "communications_review",
            "role_required": "communications_reviewer",
            "brief": "Middle high-priority unassigned task.",
            "priority": "high",
            "resume_session_on_return": False,
        },
    )
    assert middle_high_unassigned.status_code == 200
    middle_high_unassigned_id = middle_high_unassigned.json()["human_task_id"]

    newer_urgent_mine = client.post(
        "/v1/human/tasks",
        json={
            "session_id": session_id,
            "step_id": step_id,
            "task_type": "communications_review",
            "role_required": "communications_reviewer",
            "brief": "Newer urgent assigned task.",
            "priority": "urgent",
            "resume_session_on_return": False,
        },
    )
    assert newer_urgent_mine.status_code == 200
    newer_urgent_mine_id = newer_urgent_mine.json()["human_task_id"]

    newest_normal = client.post(
        "/v1/human/tasks",
        json={
            "session_id": session_id,
            "step_id": step_id,
            "task_type": "communications_review",
            "role_required": "communications_reviewer",
            "brief": "Newest normal task.",
            "priority": "normal",
            "resume_session_on_return": False,
        },
    )
    assert newest_normal.status_code == 200
    newest_normal_id = newest_normal.json()["human_task_id"]

    older_assigned = client.post(
        f"/v1/human/tasks/{older_high_mine_id}/assign",
        json={"operator_id": "operator-sorter"},
    )
    assert older_assigned.status_code == 200
    newer_assigned = client.post(
        f"/v1/human/tasks/{newer_urgent_mine_id}/assign",
        json={"operator_id": "operator-sorter"},
    )
    assert newer_assigned.status_code == 200

    listed = client.get(
        "/v1/human/tasks",
        params={"status": "pending", "sort": "priority_desc_created_asc", "limit": 10},
    )
    assert listed.status_code == 200
    listed_rows = [
        row
        for row in listed.json()
        if row["human_task_id"]
        in {oldest_normal_id, older_high_mine_id, middle_high_unassigned_id, newer_urgent_mine_id, newest_normal_id}
    ]
    assert [row["human_task_id"] for row in listed_rows[:5]] == [
        newer_urgent_mine_id,
        older_high_mine_id,
        middle_high_unassigned_id,
        oldest_normal_id,
        newest_normal_id,
    ]

    backlog = client.get(
        "/v1/human/tasks/backlog",
        params={"sort": "priority_desc_created_asc", "limit": 10},
    )
    assert backlog.status_code == 200
    backlog_rows = [
        row
        for row in backlog.json()
        if row["human_task_id"]
        in {oldest_normal_id, older_high_mine_id, middle_high_unassigned_id, newer_urgent_mine_id, newest_normal_id}
    ]
    assert [row["human_task_id"] for row in backlog_rows[:5]] == [
        newer_urgent_mine_id,
        older_high_mine_id,
        middle_high_unassigned_id,
        oldest_normal_id,
        newest_normal_id,
    ]

    unassigned = client.get(
        "/v1/human/tasks/unassigned",
        params={"sort": "priority_desc_created_asc", "limit": 10},
    )
    assert unassigned.status_code == 200
    unassigned_rows = [
        row
        for row in unassigned.json()
        if row["human_task_id"] in {middle_high_unassigned_id, oldest_normal_id, newest_normal_id}
    ]
    assert [row["human_task_id"] for row in unassigned_rows[:3]] == [
        middle_high_unassigned_id,
        oldest_normal_id,
        newest_normal_id,
    ]

    mine = client.get(
        "/v1/human/tasks/mine",
        params={"operator_id": "operator-sorter", "status": "pending", "sort": "priority_desc_created_asc", "limit": 10},
    )
    assert mine.status_code == 200
    mine_rows = [row for row in mine.json() if row["human_task_id"] in {older_high_mine_id, newer_urgent_mine_id}]
    assert [row["human_task_id"] for row in mine_rows[:2]] == [newer_urgent_mine_id, older_high_mine_id]


def test_human_task_priority_filter_across_queue_views() -> None:
    client = _client(storage_backend="memory")
    create = client.post("/v1/rewrite/artifact", json={"text": "priority filter seed"})
    assert create.status_code == 200
    session_id = create.json()["execution_session_id"]

    session = client.get(f"/v1/rewrite/sessions/{session_id}")
    assert session.status_code == 200
    step_id = session.json()["steps"][-1]["step_id"]

    normal_unassigned = client.post(
        "/v1/human/tasks",
        json={
            "session_id": session_id,
            "step_id": step_id,
            "task_type": "communications_review",
            "role_required": "communications_reviewer",
            "brief": "Normal unassigned task.",
            "priority": "normal",
            "resume_session_on_return": False,
        },
    )
    assert normal_unassigned.status_code == 200
    normal_unassigned_id = normal_unassigned.json()["human_task_id"]

    high_mine = client.post(
        "/v1/human/tasks",
        json={
            "session_id": session_id,
            "step_id": step_id,
            "task_type": "communications_review",
            "role_required": "communications_reviewer",
            "brief": "High assigned task.",
            "priority": "high",
            "resume_session_on_return": False,
        },
    )
    assert high_mine.status_code == 200
    high_mine_id = high_mine.json()["human_task_id"]

    high_unassigned = client.post(
        "/v1/human/tasks",
        json={
            "session_id": session_id,
            "step_id": step_id,
            "task_type": "communications_review",
            "role_required": "communications_reviewer",
            "brief": "High unassigned task.",
            "priority": "high",
            "resume_session_on_return": False,
        },
    )
    assert high_unassigned.status_code == 200
    high_unassigned_id = high_unassigned.json()["human_task_id"]

    urgent_mine = client.post(
        "/v1/human/tasks",
        json={
            "session_id": session_id,
            "step_id": step_id,
            "task_type": "communications_review",
            "role_required": "communications_reviewer",
            "brief": "Urgent assigned task.",
            "priority": "urgent",
            "resume_session_on_return": False,
        },
    )
    assert urgent_mine.status_code == 200
    urgent_mine_id = urgent_mine.json()["human_task_id"]

    assert client.post(f"/v1/human/tasks/{high_mine_id}/assign", json={"operator_id": "operator-sorter"}).status_code == 200
    assert client.post(f"/v1/human/tasks/{urgent_mine_id}/assign", json={"operator_id": "operator-sorter"}).status_code == 200

    listed = client.get(
        "/v1/human/tasks",
        params={"status": "pending", "priority": "high", "sort": "created_asc", "limit": 10},
    )
    assert listed.status_code == 200
    listed_rows = [row for row in listed.json() if row["human_task_id"] in {high_mine_id, high_unassigned_id}]
    assert [row["human_task_id"] for row in listed_rows[:2]] == [high_mine_id, high_unassigned_id]

    backlog = client.get(
        "/v1/human/tasks/backlog",
        params={"priority": "high", "sort": "created_asc", "limit": 10},
    )
    assert backlog.status_code == 200
    backlog_rows = [row for row in backlog.json() if row["human_task_id"] in {high_mine_id, high_unassigned_id}]
    assert [row["human_task_id"] for row in backlog_rows[:2]] == [high_mine_id, high_unassigned_id]

    unassigned = client.get(
        "/v1/human/tasks/unassigned",
        params={"priority": "high", "sort": "created_asc", "limit": 10},
    )
    assert unassigned.status_code == 200
    unassigned_rows = [row for row in unassigned.json() if row["human_task_id"] == high_unassigned_id]
    assert [row["human_task_id"] for row in unassigned_rows[:1]] == [high_unassigned_id]

    mine = client.get(
        "/v1/human/tasks/mine",
        params={"operator_id": "operator-sorter", "status": "pending", "priority": "urgent", "sort": "created_asc", "limit": 10},
    )
    assert mine.status_code == 200
    mine_rows = [row for row in mine.json() if row["human_task_id"] == urgent_mine_id]
    assert [row["human_task_id"] for row in mine_rows[:1]] == [urgent_mine_id]

    listed_ids = {row["human_task_id"] for row in listed.json()}
    backlog_ids = {row["human_task_id"] for row in backlog.json()}
    unassigned_ids = {row["human_task_id"] for row in unassigned.json()}
    mine_ids = {row["human_task_id"] for row in mine.json()}
    assert normal_unassigned_id not in listed_ids
    assert urgent_mine_id not in listed_ids
    assert normal_unassigned_id not in backlog_ids
    assert urgent_mine_id not in backlog_ids
    assert high_mine_id not in unassigned_ids
    assert normal_unassigned_id not in unassigned_ids
    assert high_mine_id not in mine_ids


def test_human_task_multi_priority_filter_across_queue_views() -> None:
    client = _client(storage_backend="memory")
    create = client.post("/v1/rewrite/artifact", json={"text": "multi priority filter seed"})
    assert create.status_code == 200
    session_id = create.json()["execution_session_id"]

    session = client.get(f"/v1/rewrite/sessions/{session_id}")
    assert session.status_code == 200
    step_id = session.json()["steps"][-1]["step_id"]

    normal_unassigned = client.post(
        "/v1/human/tasks",
        json={
            "session_id": session_id,
            "step_id": step_id,
            "task_type": "communications_review",
            "role_required": "communications_reviewer",
            "brief": "Normal unassigned task.",
            "priority": "normal",
            "resume_session_on_return": False,
        },
    )
    assert normal_unassigned.status_code == 200
    normal_unassigned_id = normal_unassigned.json()["human_task_id"]

    high_mine = client.post(
        "/v1/human/tasks",
        json={
            "session_id": session_id,
            "step_id": step_id,
            "task_type": "communications_review",
            "role_required": "communications_reviewer",
            "brief": "High assigned task.",
            "priority": "high",
            "resume_session_on_return": False,
        },
    )
    assert high_mine.status_code == 200
    high_mine_id = high_mine.json()["human_task_id"]

    high_unassigned = client.post(
        "/v1/human/tasks",
        json={
            "session_id": session_id,
            "step_id": step_id,
            "task_type": "communications_review",
            "role_required": "communications_reviewer",
            "brief": "High unassigned task.",
            "priority": "high",
            "resume_session_on_return": False,
        },
    )
    assert high_unassigned.status_code == 200
    high_unassigned_id = high_unassigned.json()["human_task_id"]

    urgent_mine = client.post(
        "/v1/human/tasks",
        json={
            "session_id": session_id,
            "step_id": step_id,
            "task_type": "communications_review",
            "role_required": "communications_reviewer",
            "brief": "Urgent assigned task.",
            "priority": "urgent",
            "resume_session_on_return": False,
        },
    )
    assert urgent_mine.status_code == 200
    urgent_mine_id = urgent_mine.json()["human_task_id"]

    assert client.post(f"/v1/human/tasks/{high_mine_id}/assign", json={"operator_id": "operator-sorter"}).status_code == 200
    assert client.post(f"/v1/human/tasks/{urgent_mine_id}/assign", json={"operator_id": "operator-sorter"}).status_code == 200

    listed = client.get(
        "/v1/human/tasks",
        params={"status": "pending", "priority": "urgent,high", "sort": "priority_desc_created_asc", "limit": 10},
    )
    assert listed.status_code == 200
    listed_rows = [row for row in listed.json() if row["human_task_id"] in {urgent_mine_id, high_mine_id, high_unassigned_id}]
    assert [row["human_task_id"] for row in listed_rows[:3]] == [urgent_mine_id, high_mine_id, high_unassigned_id]

    backlog = client.get(
        "/v1/human/tasks/backlog",
        params={"priority": "urgent,high", "sort": "priority_desc_created_asc", "limit": 10},
    )
    assert backlog.status_code == 200
    backlog_rows = [row for row in backlog.json() if row["human_task_id"] in {urgent_mine_id, high_mine_id, high_unassigned_id}]
    assert [row["human_task_id"] for row in backlog_rows[:3]] == [urgent_mine_id, high_mine_id, high_unassigned_id]

    unassigned = client.get(
        "/v1/human/tasks/unassigned",
        params={"priority": "urgent,high", "sort": "priority_desc_created_asc", "limit": 10},
    )
    assert unassigned.status_code == 200
    unassigned_rows = [row for row in unassigned.json() if row["human_task_id"] == high_unassigned_id]
    assert [row["human_task_id"] for row in unassigned_rows[:1]] == [high_unassigned_id]

    mine = client.get(
        "/v1/human/tasks/mine",
        params={"operator_id": "operator-sorter", "status": "pending", "priority": "urgent,high", "sort": "priority_desc_created_asc", "limit": 10},
    )
    assert mine.status_code == 200
    mine_rows = [row for row in mine.json() if row["human_task_id"] in {urgent_mine_id, high_mine_id}]
    assert [row["human_task_id"] for row in mine_rows[:2]] == [urgent_mine_id, high_mine_id]

    listed_ids = {row["human_task_id"] for row in listed.json()}
    backlog_ids = {row["human_task_id"] for row in backlog.json()}
    assert normal_unassigned_id not in listed_ids
    assert normal_unassigned_id not in backlog_ids


def test_human_task_priority_summary_view() -> None:
    client = _client(storage_backend="memory")
    create = client.post("/v1/rewrite/artifact", json={"text": "priority summary seed"})
    assert create.status_code == 200
    session_id = create.json()["execution_session_id"]

    session = client.get(f"/v1/rewrite/sessions/{session_id}")
    assert session.status_code == 200
    step_id = session.json()["steps"][-1]["step_id"]
    role_required = "priority_summary_reviewer"

    urgent = client.post(
        "/v1/human/tasks",
        json={
            "session_id": session_id,
            "step_id": step_id,
            "task_type": "communications_review",
            "role_required": role_required,
            "brief": "Urgent task.",
            "priority": "urgent",
            "resume_session_on_return": False,
        },
    )
    assert urgent.status_code == 200

    high_assigned = client.post(
        "/v1/human/tasks",
        json={
            "session_id": session_id,
            "step_id": step_id,
            "task_type": "communications_review",
            "role_required": role_required,
            "brief": "High assigned task.",
            "priority": "high",
            "resume_session_on_return": False,
        },
    )
    assert high_assigned.status_code == 200
    high_assigned_id = high_assigned.json()["human_task_id"]

    high_unassigned = client.post(
        "/v1/human/tasks",
        json={
            "session_id": session_id,
            "step_id": step_id,
            "task_type": "communications_review",
            "role_required": role_required,
            "brief": "High unassigned task.",
            "priority": "high",
            "resume_session_on_return": False,
        },
    )
    assert high_unassigned.status_code == 200

    normal = client.post(
        "/v1/human/tasks",
        json={
            "session_id": session_id,
            "step_id": step_id,
            "task_type": "communications_review",
            "role_required": role_required,
            "brief": "Normal task.",
            "priority": "normal",
            "resume_session_on_return": False,
        },
    )
    assert normal.status_code == 200

    assert client.post(f"/v1/human/tasks/{high_assigned_id}/assign", json={"operator_id": "operator-sorter"}).status_code == 200

    summary = client.get(
        "/v1/human/tasks/priority-summary",
        params={"status": "pending", "role_required": role_required},
    )
    assert summary.status_code == 200
    body = summary.json()
    assert body["total"] == 4
    assert body["highest_priority"] == "urgent"
    assert body["counts_json"]["urgent"] == 1
    assert body["counts_json"]["high"] == 2
    assert body["counts_json"]["normal"] == 1
    assert body["counts_json"]["low"] == 0

    unassigned_summary = client.get(
        "/v1/human/tasks/priority-summary",
        params={"status": "pending", "role_required": role_required, "assignment_state": "unassigned"},
    )
    assert unassigned_summary.status_code == 200
    unassigned_body = unassigned_summary.json()
    assert unassigned_body["total"] == 3
    assert unassigned_body["highest_priority"] == "urgent"
    assert unassigned_body["counts_json"]["urgent"] == 1
    assert unassigned_body["counts_json"]["high"] == 1
    assert unassigned_body["counts_json"]["normal"] == 1


def test_human_task_priority_summary_for_assigned_operator() -> None:
    client = _client(storage_backend="memory")
    create = client.post("/v1/rewrite/artifact", json={"text": "assigned priority summary seed"})
    assert create.status_code == 200
    session_id = create.json()["execution_session_id"]

    session = client.get(f"/v1/rewrite/sessions/{session_id}")
    assert session.status_code == 200
    step_id = session.json()["steps"][-1]["step_id"]
    role_required = "assigned_priority_summary_reviewer"
    operator_id = "operator-priority-summary"

    urgent_assigned = client.post(
        "/v1/human/tasks",
        json={
            "session_id": session_id,
            "step_id": step_id,
            "task_type": "communications_review",
            "role_required": role_required,
            "brief": "Urgent assigned task.",
            "priority": "urgent",
            "resume_session_on_return": False,
        },
    )
    assert urgent_assigned.status_code == 200
    urgent_assigned_id = urgent_assigned.json()["human_task_id"]

    high_assigned = client.post(
        "/v1/human/tasks",
        json={
            "session_id": session_id,
            "step_id": step_id,
            "task_type": "communications_review",
            "role_required": role_required,
            "brief": "High assigned task.",
            "priority": "high",
            "resume_session_on_return": False,
        },
    )
    assert high_assigned.status_code == 200
    high_assigned_id = high_assigned.json()["human_task_id"]

    normal_unassigned = client.post(
        "/v1/human/tasks",
        json={
            "session_id": session_id,
            "step_id": step_id,
            "task_type": "communications_review",
            "role_required": role_required,
            "brief": "Normal unassigned task.",
            "priority": "normal",
            "resume_session_on_return": False,
        },
    )
    assert normal_unassigned.status_code == 200

    assert client.post(f"/v1/human/tasks/{urgent_assigned_id}/assign", json={"operator_id": operator_id}).status_code == 200
    assert client.post(f"/v1/human/tasks/{high_assigned_id}/assign", json={"operator_id": operator_id}).status_code == 200

    summary = client.get(
        "/v1/human/tasks/priority-summary",
        params={"status": "pending", "role_required": role_required, "assigned_operator_id": operator_id},
    )
    assert summary.status_code == 200
    body = summary.json()
    assert body["assigned_operator_id"] == operator_id
    assert body["total"] == 2
    assert body["highest_priority"] == "urgent"
    assert body["counts_json"]["urgent"] == 1
    assert body["counts_json"]["high"] == 1
    assert body["counts_json"]["normal"] == 0


def test_human_task_priority_summary_for_matching_operator_profile() -> None:
    client = _client(storage_backend="memory")
    create = client.post("/v1/rewrite/artifact", json={"text": "operator-matched priority summary seed"})
    assert create.status_code == 200
    session_id = create.json()["execution_session_id"]

    session = client.get(f"/v1/rewrite/sessions/{session_id}")
    assert session.status_code == 200
    step_id = session.json()["steps"][-1]["step_id"]

    specialist = client.post(
        "/v1/human/tasks/operators",
        json={
            "operator_id": "operator-specialist-summary",
            "display_name": "Senior Comms Reviewer",
            "roles": ["communications_reviewer"],
            "skill_tags": ["tone", "accuracy", "stakeholder_sensitivity"],
            "trust_tier": "senior",
            "status": "active",
        },
    )
    assert specialist.status_code == 200
    junior = client.post(
        "/v1/human/tasks/operators",
        json={
            "operator_id": "operator-junior-summary",
            "display_name": "Junior Reviewer",
            "roles": ["communications_reviewer"],
            "skill_tags": ["tone"],
            "trust_tier": "standard",
            "status": "active",
        },
    )
    assert junior.status_code == 200
    scheduler = client.post(
        "/v1/human/tasks/operators",
        json={
            "operator_id": "operator-scheduler-summary",
            "display_name": "Scheduler",
            "roles": ["schedule_coordinator"],
            "skill_tags": ["calendar"],
            "trust_tier": "standard",
            "status": "active",
        },
    )
    assert scheduler.status_code == 200

    for priority in ("urgent", "high"):
        response = client.post(
            "/v1/human/tasks",
            json={
                "session_id": session_id,
                "step_id": step_id,
                "task_type": "communications_review",
                "role_required": "communications_reviewer",
                "brief": f"{priority.title()} specialist-only task.",
                "authority_required": "send_on_behalf_review",
                "quality_rubric_json": {
                    "checks": ["tone", "accuracy", "stakeholder_sensitivity"],
                },
                "priority": priority,
                "resume_session_on_return": False,
            },
        )
        assert response.status_code == 200

    scheduler_task = client.post(
        "/v1/human/tasks",
        json={
            "session_id": session_id,
            "step_id": step_id,
            "task_type": "schedule_review",
            "role_required": "schedule_coordinator",
            "brief": "Normal scheduling task.",
            "priority": "normal",
            "resume_session_on_return": False,
        },
    )
    assert scheduler_task.status_code == 200

    specialist_summary = client.get(
        "/v1/human/tasks/priority-summary",
        params={
            "status": "pending",
            "assignment_state": "unassigned",
            "operator_id": "operator-specialist-summary",
        },
    )
    assert specialist_summary.status_code == 200
    specialist_body = specialist_summary.json()
    assert specialist_body["operator_id"] == "operator-specialist-summary"
    assert specialist_body["total"] == 2
    assert specialist_body["highest_priority"] == "urgent"
    assert specialist_body["counts_json"]["urgent"] == 1
    assert specialist_body["counts_json"]["high"] == 1
    assert specialist_body["counts_json"]["normal"] == 0

    junior_summary = client.get(
        "/v1/human/tasks/priority-summary",
        params={
            "status": "pending",
            "assignment_state": "unassigned",
            "operator_id": "operator-junior-summary",
        },
    )
    assert junior_summary.status_code == 200
    junior_body = junior_summary.json()
    assert junior_body["operator_id"] == "operator-junior-summary"
    assert junior_body["total"] == 0
    assert junior_body["highest_priority"] == ""
    assert junior_body["counts_json"]["urgent"] == 0
    assert junior_body["counts_json"]["high"] == 0
    assert junior_body["counts_json"]["normal"] == 0

    scheduler_summary = client.get(
        "/v1/human/tasks/priority-summary",
        params={
            "status": "pending",
            "assignment_state": "unassigned",
            "operator_id": "operator-scheduler-summary",
        },
    )
    assert scheduler_summary.status_code == 200
    scheduler_body = scheduler_summary.json()
    assert scheduler_body["operator_id"] == "operator-scheduler-summary"
    assert scheduler_body["total"] == 1
    assert scheduler_body["highest_priority"] == "normal"
    assert scheduler_body["counts_json"]["urgent"] == 0
    assert scheduler_body["counts_json"]["high"] == 0
    assert scheduler_body["counts_json"]["normal"] == 1


def test_human_task_priority_summary_for_assignment_source() -> None:
    client = _client(storage_backend="memory")

    contract = client.post(
        "/v1/task-contracts",
        json={
            "task_type": "rewrite_text",
            "description": "Rewrite text with human review and auto-preselection.",
            "deliverable_type": "rewrite_note",
            "default_approval_class": "none",
            "allowed_tools": ["artifact_repository"],
            "evidence_requirements": ["stakeholder_context"],
            "memory_write_policy": "reviewed_only",
            "budget_policy_json": {
                "class": "low",
                "human_review_role": "source_filter_reviewer",
                "human_review_task_type": "communications_review",
                "human_review_brief": "Review the rewrite before finalizing it.",
                "human_review_priority": "high",
                "human_review_sla_minutes": 45,
                "human_review_auto_assign_if_unique": True,
                "human_review_desired_output_json": {
                    "format": "review_packet",
                    "escalation_policy": "manager_review",
                },
                "human_review_authority_required": "send_on_behalf_review",
                "human_review_why_human": "Executive-facing rewrite needs human judgment before finalization.",
                "human_review_quality_rubric_json": {
                    "checks": ["tone", "accuracy", "stakeholder_sensitivity"],
                },
            },
        },
    )
    assert contract.status_code == 200

    operator_profile = client.post(
        "/v1/human/tasks/operators",
        json={
            "operator_id": "operator-auto-summary",
            "display_name": "Senior Comms Reviewer",
            "roles": ["source_filter_reviewer"],
            "skill_tags": ["tone", "accuracy", "stakeholder_sensitivity"],
            "trust_tier": "senior",
            "status": "active",
        },
    )
    assert operator_profile.status_code == 200

    create = client.post("/v1/rewrite/artifact", json={"text": "rewrite with pending auto-preselected review"})
    assert create.status_code == 202
    auto_task_id = create.json()["human_task_id"]
    session_id = create.json()["session_id"]

    session = client.get(f"/v1/rewrite/sessions/{session_id}")
    assert session.status_code == 200
    step_id = session.json()["steps"][-1]["step_id"]

    manual_task = client.post(
        "/v1/human/tasks",
        json={
            "session_id": session_id,
            "step_id": step_id,
            "task_type": "communications_review",
            "role_required": "manual_source_filter_reviewer",
            "brief": "Manual assigned task.",
            "priority": "normal",
            "resume_session_on_return": False,
        },
    )
    assert manual_task.status_code == 200
    manual_task_id = manual_task.json()["human_task_id"]
    assign_manual = client.post(
        f"/v1/human/tasks/{manual_task_id}/assign",
        json={"operator_id": "operator-manual-summary"},
    )
    assert assign_manual.status_code == 200

    auto_summary = client.get(
        "/v1/human/tasks/priority-summary",
        params={"status": "pending", "assignment_source": "auto_preselected"},
    )
    assert auto_summary.status_code == 200
    auto_body = auto_summary.json()
    assert auto_body["assignment_source"] == "auto_preselected"
    assert auto_body["total"] == 1
    assert auto_body["highest_priority"] == "high"
    assert auto_body["counts_json"]["urgent"] == 0
    assert auto_body["counts_json"]["high"] == 1
    assert auto_body["counts_json"]["normal"] == 0

    manual_summary = client.get(
        "/v1/human/tasks/priority-summary",
        params={"status": "pending", "assignment_source": "manual"},
    )
    assert manual_summary.status_code == 200
    manual_body = manual_summary.json()
    assert manual_body["assignment_source"] == "manual"
    assert manual_body["total"] == 1
    assert manual_body["highest_priority"] == "normal"
    assert manual_body["counts_json"]["urgent"] == 0
    assert manual_body["counts_json"]["high"] == 0
    assert manual_body["counts_json"]["normal"] == 1

    manual_list = client.get(
        "/v1/human/tasks",
        params={"status": "pending", "assignment_source": "manual"},
    )
    assert manual_list.status_code == 200
    manual_ids = {row["human_task_id"] for row in manual_list.json()}
    assert manual_task_id in manual_ids
    assert auto_task_id not in manual_ids

    manual_mine = client.get(
        "/v1/human/tasks/mine",
        params={"operator_id": "operator-manual-summary", "assignment_source": "manual"},
    )
    assert manual_mine.status_code == 200
    manual_mine_ids = {row["human_task_id"] for row in manual_mine.json()}
    assert manual_task_id in manual_mine_ids

    auto_backlog = client.get(
        "/v1/human/tasks/backlog",
        params={"operator_id": "operator-auto-summary", "assignment_source": "auto_preselected"},
    )
    assert auto_backlog.status_code == 200
    auto_backlog_ids = {row["human_task_id"] for row in auto_backlog.json()}
    assert auto_task_id in auto_backlog_ids
    assert manual_task_id not in auto_backlog_ids

    session_after = client.get(f"/v1/rewrite/sessions/{session_id}")
    assert session_after.status_code == 200
    auto_task = next(row for row in session_after.json()["human_tasks"] if row["human_task_id"] == auto_task_id)
    assert auto_task["assignment_source"] == "auto_preselected"


def test_human_task_sort_by_sla_due_at_asc() -> None:
    client = _client(storage_backend="memory")
    create = client.post("/v1/rewrite/artifact", json={"text": "sla sort seed"})
    assert create.status_code == 200
    session_id = create.json()["execution_session_id"]

    session = client.get(f"/v1/rewrite/sessions/{session_id}")
    assert session.status_code == 200
    step_id = session.json()["steps"][-1]["step_id"]

    later_due = client.post(
        "/v1/human/tasks",
        json={
            "session_id": session_id,
            "step_id": step_id,
            "task_type": "communications_review",
            "role_required": "communications_reviewer",
            "brief": "Later due task.",
            "sla_due_at": "2100-01-02T00:00:00+00:00",
            "resume_session_on_return": False,
        },
    )
    assert later_due.status_code == 200
    later_due_task_id = later_due.json()["human_task_id"]

    sooner_due = client.post(
        "/v1/human/tasks",
        json={
            "session_id": session_id,
            "step_id": step_id,
            "task_type": "communications_review",
            "role_required": "communications_reviewer",
            "brief": "Sooner due task.",
            "sla_due_at": "2100-01-01T00:00:00+00:00",
            "resume_session_on_return": False,
        },
    )
    assert sooner_due.status_code == 200
    sooner_due_task_id = sooner_due.json()["human_task_id"]

    listed = client.get(
        "/v1/human/tasks",
        params={"status": "pending", "sort": "sla_due_at_asc", "limit": 10},
    )
    assert listed.status_code == 200
    listed_rows = [row for row in listed.json() if row["human_task_id"] in {later_due_task_id, sooner_due_task_id}]
    assert [row["human_task_id"] for row in listed_rows[:2]] == [sooner_due_task_id, later_due_task_id]

    backlog = client.get(
        "/v1/human/tasks/backlog",
        params={"sort": "sla_due_at_asc", "limit": 10},
    )
    assert backlog.status_code == 200
    backlog_rows = [row for row in backlog.json() if row["human_task_id"] in {later_due_task_id, sooner_due_task_id}]
    assert [row["human_task_id"] for row in backlog_rows[:2]] == [sooner_due_task_id, later_due_task_id]


def test_human_task_sort_by_sla_then_last_transition() -> None:
    client = _client(storage_backend="memory")
    create = client.post("/v1/rewrite/artifact", json={"text": "combined sort seed"})
    assert create.status_code == 200
    session_id = create.json()["execution_session_id"]

    session = client.get(f"/v1/rewrite/sessions/{session_id}")
    assert session.status_code == 200
    step_id = session.json()["steps"][-1]["step_id"]

    early_stale = client.post(
        "/v1/human/tasks",
        json={
            "session_id": session_id,
            "step_id": step_id,
            "task_type": "communications_review",
            "role_required": "communications_reviewer",
            "brief": "Earlier due stale task.",
            "sla_due_at": "2100-01-01T00:00:00+00:00",
            "resume_session_on_return": False,
        },
    )
    assert early_stale.status_code == 200
    early_stale_id = early_stale.json()["human_task_id"]

    early_recent = client.post(
        "/v1/human/tasks",
        json={
            "session_id": session_id,
            "step_id": step_id,
            "task_type": "communications_review",
            "role_required": "communications_reviewer",
            "brief": "Earlier due recently touched task.",
            "sla_due_at": "2100-01-01T00:00:00+00:00",
            "resume_session_on_return": False,
        },
    )
    assert early_recent.status_code == 200
    early_recent_id = early_recent.json()["human_task_id"]

    later_due = client.post(
        "/v1/human/tasks",
        json={
            "session_id": session_id,
            "step_id": step_id,
            "task_type": "communications_review",
            "role_required": "communications_reviewer",
            "brief": "Later due task.",
            "sla_due_at": "2100-01-02T00:00:00+00:00",
            "resume_session_on_return": False,
        },
    )
    assert later_due.status_code == 200
    later_due_id = later_due.json()["human_task_id"]

    assigned = client.post(f"/v1/human/tasks/{early_recent_id}/assign", json={"operator_id": "operator-sorter"})
    assert assigned.status_code == 200
    assert assigned.json()["last_transition_event_name"] == "human_task_assigned"

    listed = client.get(
        "/v1/human/tasks",
        params={"status": "pending", "sort": "sla_due_at_asc_last_transition_desc", "limit": 10},
    )
    assert listed.status_code == 200
    listed_rows = [
        row for row in listed.json() if row["human_task_id"] in {early_stale_id, early_recent_id, later_due_id}
    ]
    assert [row["human_task_id"] for row in listed_rows[:3]] == [early_recent_id, early_stale_id, later_due_id]

    backlog = client.get(
        "/v1/human/tasks/backlog",
        params={"sort": "sla_due_at_asc_last_transition_desc", "limit": 10},
    )
    assert backlog.status_code == 200
    backlog_rows = [
        row for row in backlog.json() if row["human_task_id"] in {early_stale_id, early_recent_id, later_due_id}
    ]
    assert [row["human_task_id"] for row in backlog_rows[:3]] == [early_recent_id, early_stale_id, later_due_id]


def test_human_task_unscheduled_fallback_sorting_for_sla_modes() -> None:
    client = _client(storage_backend="memory")
    create = client.post("/v1/rewrite/artifact", json={"text": "unscheduled fallback seed"})
    assert create.status_code == 200
    session_id = create.json()["execution_session_id"]

    session = client.get(f"/v1/rewrite/sessions/{session_id}")
    assert session.status_code == 200
    step_id = session.json()["steps"][-1]["step_id"]

    due_task = client.post(
        "/v1/human/tasks",
        json={
            "session_id": session_id,
            "step_id": step_id,
            "task_type": "communications_review",
            "role_required": "communications_reviewer",
            "brief": "Scheduled task.",
            "sla_due_at": "2100-01-01T00:00:00+00:00",
            "resume_session_on_return": False,
        },
    )
    assert due_task.status_code == 200
    due_task_id = due_task.json()["human_task_id"]

    older_unscheduled = client.post(
        "/v1/human/tasks",
        json={
            "session_id": session_id,
            "step_id": step_id,
            "task_type": "communications_review",
            "role_required": "communications_reviewer",
            "brief": "Older unscheduled task.",
            "resume_session_on_return": False,
        },
    )
    assert older_unscheduled.status_code == 200
    older_unscheduled_id = older_unscheduled.json()["human_task_id"]

    newer_unscheduled = client.post(
        "/v1/human/tasks",
        json={
            "session_id": session_id,
            "step_id": step_id,
            "task_type": "communications_review",
            "role_required": "communications_reviewer",
            "brief": "Newer unscheduled task.",
            "resume_session_on_return": False,
        },
    )
    assert newer_unscheduled.status_code == 200
    newer_unscheduled_id = newer_unscheduled.json()["human_task_id"]

    assigned = client.post(f"/v1/human/tasks/{newer_unscheduled_id}/assign", json={"operator_id": "operator-sorter"})
    assert assigned.status_code == 200
    assert assigned.json()["last_transition_event_name"] == "human_task_assigned"

    sla_list = client.get(
        "/v1/human/tasks",
        params={"status": "pending", "sort": "sla_due_at_asc", "limit": 10},
    )
    assert sla_list.status_code == 200
    sla_list_rows = [
        row for row in sla_list.json() if row["human_task_id"] in {due_task_id, older_unscheduled_id, newer_unscheduled_id}
    ]
    assert [row["human_task_id"] for row in sla_list_rows[:3]] == [due_task_id, older_unscheduled_id, newer_unscheduled_id]

    combined_list = client.get(
        "/v1/human/tasks",
        params={"status": "pending", "sort": "sla_due_at_asc_last_transition_desc", "limit": 10},
    )
    assert combined_list.status_code == 200
    combined_list_rows = [
        row
        for row in combined_list.json()
        if row["human_task_id"] in {due_task_id, older_unscheduled_id, newer_unscheduled_id}
    ]
    assert [row["human_task_id"] for row in combined_list_rows[:3]] == [
        due_task_id,
        older_unscheduled_id,
        newer_unscheduled_id,
    ]

    combined_backlog = client.get(
        "/v1/human/tasks/backlog",
        params={"sort": "sla_due_at_asc_last_transition_desc", "limit": 10},
    )
    assert combined_backlog.status_code == 200
    combined_backlog_rows = [
        row
        for row in combined_backlog.json()
        if row["human_task_id"] in {due_task_id, older_unscheduled_id, newer_unscheduled_id}
    ]
    assert [row["human_task_id"] for row in combined_backlog_rows[:3]] == [
        due_task_id,
        older_unscheduled_id,
        newer_unscheduled_id,
    ]


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
    assert len(compiled.json()["plan"]["steps"]) == 3
    assert compiled.json()["plan"]["steps"][0]["step_key"] == "step_input_prepare"
    assert compiled.json()["plan"]["steps"][1]["step_key"] == "step_policy_evaluate"
    assert compiled.json()["plan"]["steps"][1]["step_kind"] == "policy_check"
    assert compiled.json()["plan"]["steps"][1]["depends_on"] == ["step_input_prepare"]
    assert compiled.json()["plan"]["steps"][1]["output_keys"] == ["allow", "requires_approval", "reason", "retention_policy"]
    assert compiled.json()["plan"]["steps"][2]["tool_name"] == "artifact_repository"
    assert compiled.json()["plan"]["steps"][2]["depends_on"] == ["step_policy_evaluate"]
    assert compiled.json()["plan"]["steps"][2]["approval_required"] is True

    review_contract = client.post(
        "/v1/tasks/contracts",
        json={
            "task_key": "rewrite_review",
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
                "human_review_auto_assign_if_unique": True,
                "human_review_desired_output_json": {
                    "format": "review_packet",
                    "escalation_policy": "manager_review",
                },
                "human_review_authority_required": "send_on_behalf_review",
                "human_review_why_human": "Executive-facing rewrite needs human judgment before finalization.",
                "human_review_quality_rubric_json": {
                    "checks": ["tone", "accuracy", "stakeholder_sensitivity"]
                },
            },
        },
    )
    assert review_contract.status_code == 200

    compiled_review = client.post(
        "/v1/plans/compile",
        json={"task_key": "rewrite_review", "principal_id": "exec-1", "goal": "review this rewrite"},
    )
    assert compiled_review.status_code == 200
    assert len(compiled_review.json()["plan"]["steps"]) == 4
    assert compiled_review.json()["plan"]["steps"][2]["step_key"] == "step_human_review"
    assert compiled_review.json()["plan"]["steps"][2]["step_kind"] == "human_task"
    assert compiled_review.json()["plan"]["steps"][2]["task_type"] == "communications_review"
    assert compiled_review.json()["plan"]["steps"][2]["role_required"] == "communications_reviewer"
    assert compiled_review.json()["plan"]["steps"][2]["priority"] == "high"
    assert compiled_review.json()["plan"]["steps"][2]["sla_minutes"] == 45
    assert compiled_review.json()["plan"]["steps"][2]["auto_assign_if_unique"] is True
    assert compiled_review.json()["plan"]["steps"][2]["desired_output_json"]["escalation_policy"] == "manager_review"
    assert compiled_review.json()["plan"]["steps"][2]["authority_required"] == "send_on_behalf_review"
    assert (
        compiled_review.json()["plan"]["steps"][2]["quality_rubric_json"]["checks"][0] == "tone"
    )
    assert compiled_review.json()["plan"]["steps"][3]["depends_on"] == ["step_human_review"]

    rewrite = client.post("/v1/rewrite/artifact", json={"text": "short rewrite input"})
    assert rewrite.status_code == 202
    assert rewrite.json()["status"] == "awaiting_approval"
    assert rewrite.json()["next_action"] == "poll_or_subscribe"


def test_rewrite_compiled_human_review_branch_pauses_and_resumes() -> None:
    client = _client(storage_backend="memory")
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
                "human_review_auto_assign_if_unique": True,
                "human_review_desired_output_json": {
                    "format": "review_packet",
                    "escalation_policy": "manager_review",
                },
                "human_review_authority_required": "send_on_behalf_review",
                "human_review_why_human": "Executive-facing rewrite needs human judgment before finalization.",
                "human_review_quality_rubric_json": {
                    "checks": ["tone", "accuracy", "stakeholder_sensitivity"]
                },
            },
        },
    )
    assert contract.status_code == 200

    operator_profile = client.post(
        "/v1/human/tasks/operators",
        json={
            "operator_id": "operator-specialist",
            "display_name": "Senior Comms Reviewer",
            "roles": ["communications_reviewer"],
            "skill_tags": ["tone", "accuracy", "stakeholder_sensitivity"],
            "trust_tier": "senior",
            "status": "active",
        },
    )
    assert operator_profile.status_code == 200
    operator_low = client.post(
        "/v1/human/tasks/operators",
        json={
            "operator_id": "operator-junior",
            "display_name": "Junior Reviewer",
            "roles": ["communications_reviewer"],
            "skill_tags": ["tone"],
            "trust_tier": "standard",
            "status": "active",
        },
    )
    assert operator_low.status_code == 200

    create = client.post("/v1/rewrite/artifact", json={"text": "rewrite with human review"})
    assert create.status_code == 202
    assert create.json()["status"] == "awaiting_human"
    assert create.json()["human_task_id"]
    assert create.json()["approval_id"] == ""
    session_id = create.json()["session_id"]
    human_task_id = create.json()["human_task_id"]

    session = client.get(f"/v1/rewrite/sessions/{session_id}")
    assert session.status_code == 200
    body = session.json()
    assert body["status"] == "awaiting_human"
    assert len(body["steps"]) == 4
    assert body["steps"][2]["input_json"]["plan_step_key"] == "step_human_review"
    assert body["steps"][2]["state"] == "waiting_human"
    assert body["steps"][3]["state"] == "queued"
    assert len(body["queue_items"]) == 3
    assert all(item["state"] == "done" for item in body["queue_items"])
    assert any(row["human_task_id"] == human_task_id and row["status"] == "pending" for row in body["human_tasks"])
    review_task = next(row for row in body["human_tasks"] if row["human_task_id"] == human_task_id)
    assert review_task["priority"] == "high"
    assert review_task["sla_due_at"]
    assert review_task["desired_output_json"]["escalation_policy"] == "manager_review"
    assert review_task["authority_required"] == "send_on_behalf_review"
    assert review_task["why_human"] == "Executive-facing rewrite needs human judgment before finalization."
    assert review_task["quality_rubric_json"]["checks"][0] == "tone"
    assert review_task["assignment_state"] == "assigned"
    assert review_task["assigned_operator_id"] == "operator-specialist"
    assert review_task["assignment_source"] == "auto_preselected"
    assert review_task["assigned_at"]
    assert review_task["assigned_by_actor_id"] == "orchestrator:auto_preselected"
    assert review_task["last_transition_event_name"] == "human_task_assigned"
    assert review_task["last_transition_at"]
    assert review_task["last_transition_assignment_state"] == "assigned"
    assert review_task["last_transition_operator_id"] == "operator-specialist"
    assert review_task["last_transition_assignment_source"] == "auto_preselected"
    assert review_task["last_transition_by_actor_id"] == "orchestrator:auto_preselected"
    assert [row["event_name"] for row in body["human_task_assignment_history"]] == [
        "human_task_created",
        "human_task_assigned",
    ]
    assert body["human_task_assignment_history"][1]["assigned_operator_id"] == "operator-specialist"
    assert body["human_task_assignment_history"][1]["assignment_source"] == "auto_preselected"
    assert review_task["routing_hints_json"]["recommended_operator_id"] == "operator-specialist"
    assert review_task["routing_hints_json"]["auto_assign_operator_id"] == ""
    assert review_task["routing_hints_json"]["candidate_count"] == 1

    auto_only = client.get(
        f"/v1/rewrite/sessions/{session_id}",
        params={"human_task_assignment_source": "auto_preselected"},
    )
    assert auto_only.status_code == 200
    auto_only_body = auto_only.json()
    assert len(auto_only_body["human_tasks"]) == 1
    assert auto_only_body["human_tasks"][0]["human_task_id"] == human_task_id
    assert [row["event_name"] for row in auto_only_body["human_task_assignment_history"]] == [
        "human_task_assigned"
    ]

    reviewed_text = "rewrite with human review, edited by reviewer"
    returned = client.post(
        f"/v1/human/tasks/{human_task_id}/return",
        json={
            "operator_id": "reviewer-1",
            "resolution": "ready_for_send",
            "returned_payload_json": {"final_text": reviewed_text},
            "provenance_json": {"review_mode": "human"},
        },
    )
    assert returned.status_code == 200
    assert returned.json()["status"] == "returned"
    assert returned.json()["last_transition_event_name"] == "human_task_returned"
    assert returned.json()["last_transition_assignment_state"] == "returned"
    assert returned.json()["last_transition_operator_id"] == "reviewer-1"
    assert returned.json()["last_transition_assignment_source"] == "manual"
    assert returned.json()["last_transition_by_actor_id"] == "reviewer-1"

    session_after = client.get(f"/v1/rewrite/sessions/{session_id}")
    assert session_after.status_code == 200
    body_after = session_after.json()
    event_names = [row["name"] for row in body_after["events"]]
    assert body_after["status"] == "completed"
    assert "human_task_step_started" in event_names
    assert "human_task_created" in event_names
    assert "human_task_returned" in event_names
    assert "session_resumed_from_human_task" in event_names
    assert "tool_execution_completed" in event_names
    assert len(body_after["queue_items"]) == 4
    assert all(item["state"] == "done" for item in body_after["queue_items"])
    assert len(body_after["artifacts"]) == 1
    assert body_after["artifacts"][0]["content"] == reviewed_text
    assert body_after["steps"][2]["state"] == "completed"
    assert body_after["steps"][3]["state"] == "completed"


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
