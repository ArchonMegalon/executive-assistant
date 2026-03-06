from __future__ import annotations

import os
import uuid

import pytest

from app.domain.models import IntentSpecV3, PolicyDecision, TaskContract, now_utc_iso
from app.repositories.approvals_postgres import PostgresApprovalRepository
from app.repositories.ledger_postgres import PostgresExecutionLedgerRepository
from app.repositories.policy_decisions_postgres import PostgresPolicyDecisionRepository
from app.repositories.task_contracts_postgres import PostgresTaskContractRepository


def _db_url() -> str:
    db_url = (os.environ.get("EA_TEST_DATABASE_URL") or "").strip()
    if not db_url:
        pytest.skip("EA_TEST_DATABASE_URL is not set")
    return db_url


def test_postgres_approvals_create_decide_and_list_history() -> None:
    repo = PostgresApprovalRepository(_db_url(), default_ttl_minutes=60)
    session_id = f"session-{uuid.uuid4()}"
    step_id = f"step-{uuid.uuid4()}"

    request = repo.create_request(
        session_id=session_id,
        step_id=step_id,
        reason="approval_required",
        requested_action_json={"action": "artifact.save", "channel": "email"},
    )

    pending = repo.list_pending(limit=10)
    assert any(row.approval_id == request.approval_id for row in pending)

    found = repo.decide(
        request.approval_id,
        decision="approve",
        decided_by="tester",
        reason="approved in contract matrix",
    )
    assert found is not None
    updated_request, decision = found
    assert updated_request.status == "approved"
    assert decision.decision == "approved"
    assert decision.decided_by == "tester"

    pending_after = repo.list_pending(limit=10)
    assert all(row.approval_id != request.approval_id for row in pending_after)

    history = repo.list_history(limit=10, session_id=session_id)
    assert any(row.approval_id == request.approval_id and row.decision == "approved" for row in history)


def test_postgres_approvals_auto_expire_past_due_request() -> None:
    repo = PostgresApprovalRepository(_db_url(), default_ttl_minutes=60)
    session_id = f"session-{uuid.uuid4()}"
    request = repo.create_request(
        session_id=session_id,
        step_id=f"step-{uuid.uuid4()}",
        reason="approval_required",
        requested_action_json={"action": "delivery.send"},
        expires_at="2000-01-01T00:00:00+00:00",
    )

    pending = repo.list_pending(limit=10)
    assert all(row.approval_id != request.approval_id for row in pending)

    history = repo.list_history(limit=10, session_id=session_id)
    assert any(row.approval_id == request.approval_id and row.decision == "expired" for row in history)


def test_postgres_policy_decisions_append_and_filter_recent() -> None:
    repo = PostgresPolicyDecisionRepository(_db_url())
    session_id = f"session-{uuid.uuid4()}"
    other_session_id = f"session-{uuid.uuid4()}"

    allowed = repo.append(
        session_id,
        PolicyDecision(
            allow=True,
            requires_approval=False,
            reason="allowed",
            retention_policy="standard",
            memory_write_allowed=True,
        ),
    )
    denied = repo.append(
        session_id,
        PolicyDecision(
            allow=False,
            requires_approval=False,
            reason="tool_not_allowed",
            retention_policy="none",
            memory_write_allowed=False,
        ),
    )
    _other = repo.append(
        other_session_id,
        PolicyDecision(
            allow=True,
            requires_approval=True,
            reason="allowed",
            retention_policy="standard",
            memory_write_allowed=False,
        ),
    )

    filtered = repo.list_recent(limit=10, session_id=session_id)
    filtered_ids = {row.decision_id for row in filtered}
    assert allowed.decision_id in filtered_ids
    assert denied.decision_id in filtered_ids
    assert all(row.session_id == session_id for row in filtered)

    listed = repo.list_recent(limit=10)
    listed_ids = {row.decision_id for row in listed}
    assert allowed.decision_id in listed_ids
    assert denied.decision_id in listed_ids


def test_postgres_task_contracts_upsert_get_and_list() -> None:
    repo = PostgresTaskContractRepository(_db_url())
    task_key = f"contract_{uuid.uuid4().hex}"

    row = repo.upsert(
        TaskContract(
            task_key=task_key,
            deliverable_type="rewrite_note",
            default_risk_class="medium",
            default_approval_class="manager",
            allowed_tools=("artifact_repository", "connector.dispatch"),
            evidence_requirements=("source_link",),
            memory_write_policy="reviewed_only",
            budget_policy_json={"class": "medium"},
            updated_at=now_utc_iso(),
        )
    )

    assert row.task_key == task_key
    assert row.allowed_tools == ("artifact_repository", "connector.dispatch")

    found = repo.get(task_key)
    assert found is not None
    assert found.default_approval_class == "manager"
    assert found.evidence_requirements == ("source_link",)

    listed = repo.list_all(limit=20)
    assert any(entry.task_key == task_key for entry in listed)


def test_postgres_execution_queue_enqueue_lease_complete_and_list() -> None:
    repo = PostgresExecutionLedgerRepository(_db_url())
    session = repo.start_session(
        IntentSpecV3(
            principal_id="queue-tester",
            goal="persist a queued rewrite",
            task_type="rewrite_text",
            deliverable_type="rewrite_note",
            risk_class="low",
            approval_class="none",
            budget_class="low",
            allowed_tools=("artifact_repository",),
        )
    )
    step = repo.start_step(
        session.session_id,
        "tool_call",
        input_json={"source_text": "queued contract payload", "tool_name": "artifact_repository"},
        correlation_id=f"corr-{uuid.uuid4()}",
        causation_id=f"cause-{uuid.uuid4()}",
        actor_type="assistant",
        actor_id="contract-test",
    )

    queue_item = repo.enqueue_step(
        session.session_id,
        step.step_id,
        idempotency_key=f"{session.session_id}:{step.step_id}",
    )
    assert queue_item.state == "queued"
    assert queue_item.attempt_count == 0

    leased = repo.lease_next_queue_item(lease_owner="contract-worker", lease_seconds=30)
    assert leased is not None
    assert leased.queue_id == queue_item.queue_id
    assert leased.state == "leased"
    assert leased.attempt_count == 1
    assert leased.lease_owner == "contract-worker"

    updated_step = repo.update_step(step.step_id, state="running", attempt_count=leased.attempt_count, error_json={})
    assert updated_step is not None
    assert updated_step.state == "running"
    assert updated_step.attempt_count == 1

    done = repo.complete_queue_item(queue_item.queue_id, state="done")
    assert done is not None
    assert done.state == "done"
    assert done.lease_owner == ""

    listed = repo.queue_for_session(session.session_id)
    assert len(listed) == 1
    assert listed[0].queue_id == queue_item.queue_id
    assert listed[0].state == "done"
