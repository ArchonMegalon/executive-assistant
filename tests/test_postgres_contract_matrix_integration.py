from __future__ import annotations

import os
import uuid

import pytest

from app.domain.models import IntentSpecV3, PolicyDecision, TaskContract, TaskExecutionRequest, now_utc_iso
from app.repositories.artifacts import InMemoryArtifactRepository
from app.repositories.approvals_postgres import PostgresApprovalRepository
from app.repositories.human_tasks_postgres import PostgresHumanTaskRepository
from app.repositories.ledger_postgres import PostgresExecutionLedgerRepository
from app.repositories.operator_profiles_postgres import PostgresOperatorProfileRepository
from app.repositories.policy_decisions_postgres import PostgresPolicyDecisionRepository
from app.repositories.task_contracts_postgres import PostgresTaskContractRepository
from app.services.orchestrator import RewriteOrchestrator
from app.services.planner import PlannerService
from app.services.task_contracts import TaskContractService


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


def test_postgres_orchestrator_executes_non_rewrite_task_contract() -> None:
    ledger = PostgresExecutionLedgerRepository(_db_url())
    repo = PostgresTaskContractRepository(_db_url())
    service = TaskContractService(repo)
    task_key = f"stakeholder_briefing_{uuid.uuid4().hex}"
    service.upsert_contract(
        task_key=task_key,
        deliverable_type="stakeholder_briefing",
        default_risk_class="low",
        default_approval_class="none",
        allowed_tools=("artifact_repository",),
        evidence_requirements=("stakeholder_context",),
        memory_write_policy="reviewed_only",
        budget_policy_json={"class": "low"},
    )
    orchestrator = RewriteOrchestrator(
        artifacts=InMemoryArtifactRepository(),
        ledger=ledger,
        task_contracts=service,
        planner=PlannerService(service),
    )

    artifact = orchestrator.execute_task_artifact(
        TaskExecutionRequest(
            task_key=task_key,
            text="Board context and stakeholder sensitivities.",
            principal_id="exec-briefing",
            goal="prepare a stakeholder briefing",
        )
    )

    assert artifact.kind == "stakeholder_briefing"
    assert artifact.content == "Board context and stakeholder sensitivities."

    session = ledger.get_session(artifact.execution_session_id)
    assert session is not None
    assert session.status == "completed"

    steps = ledger.steps_for(session.session_id)
    assert len(steps) == 3
    assert steps[0].input_json["plan_step_key"] == "step_input_prepare"
    assert steps[-1].input_json["tool_name"] == "artifact_repository"


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


def test_postgres_orchestrator_dependency_scheduler_waits_for_all_dependencies() -> None:
    ledger = PostgresExecutionLedgerRepository(_db_url())
    orchestrator = RewriteOrchestrator(ledger=ledger)
    session = ledger.start_session(
        IntentSpecV3(
            principal_id="dependency-tester",
            goal="verify dependency-aware queue advancement",
            task_type="rewrite_text",
            deliverable_type="rewrite_note",
            risk_class="low",
            approval_class="none",
            budget_class="low",
            allowed_tools=("artifact_repository",),
        )
    )
    root = ledger.start_step(
        session.session_id,
        "system_task",
        input_json={"plan_step_key": "step_root", "depends_on": [], "step_index": 0},
        correlation_id=f"corr-{uuid.uuid4()}",
        causation_id=f"cause-{uuid.uuid4()}",
        actor_type="assistant",
        actor_id="contract-test",
    )
    join = ledger.start_step(
        session.session_id,
        "tool_call",
        parent_step_id=root.step_id,
        input_json={"plan_step_key": "step_join", "depends_on": ["step_branch_a", "step_branch_b"], "step_index": 1},
        correlation_id=f"corr-{uuid.uuid4()}",
        causation_id=f"cause-{uuid.uuid4()}",
        actor_type="assistant",
        actor_id="contract-test",
    )
    branch_a = ledger.start_step(
        session.session_id,
        "system_task",
        parent_step_id=join.step_id,
        input_json={"plan_step_key": "step_branch_a", "depends_on": ["step_root"], "step_index": 2},
        correlation_id=f"corr-{uuid.uuid4()}",
        causation_id=f"cause-{uuid.uuid4()}",
        actor_type="assistant",
        actor_id="contract-test",
    )
    branch_b = ledger.start_step(
        session.session_id,
        "system_task",
        parent_step_id=branch_a.step_id,
        input_json={"plan_step_key": "step_branch_b", "depends_on": ["step_root"], "step_index": 3},
        correlation_id=f"corr-{uuid.uuid4()}",
        causation_id=f"cause-{uuid.uuid4()}",
        actor_type="assistant",
        actor_id="contract-test",
    )

    ledger.update_step(root.step_id, state="completed", output_json={"done": True}, error_json={})
    orchestrator._queue_next_step_after(session.session_id, root.step_id, lease_owner="worker")
    first_ready = ledger.queue_for_session(session.session_id)
    assert [row.step_id for row in first_ready] == [branch_a.step_id]

    ledger.update_step(branch_a.step_id, state="completed", output_json={"done": True}, error_json={})
    orchestrator._queue_next_step_after(session.session_id, branch_a.step_id, lease_owner="worker")
    second_ready = ledger.queue_for_session(session.session_id)
    assert [row.step_id for row in second_ready] == [branch_a.step_id, branch_b.step_id]
    assert all(row.step_id != join.step_id for row in second_ready)

    ledger.update_step(branch_b.step_id, state="completed", output_json={"done": True}, error_json={})
    orchestrator._queue_next_step_after(session.session_id, branch_b.step_id, lease_owner="worker")
    final_ready = ledger.queue_for_session(session.session_id)
    assert [row.step_id for row in final_ready] == [branch_a.step_id, branch_b.step_id, join.step_id]


def test_postgres_human_task_step_merges_dependency_outputs() -> None:
    ledger = PostgresExecutionLedgerRepository(_db_url())
    human_tasks = PostgresHumanTaskRepository(_db_url())
    orchestrator = RewriteOrchestrator(ledger=ledger, human_tasks=human_tasks)
    session = ledger.start_session(
        IntentSpecV3(
            principal_id="dependency-human-tester",
            goal="merge branch output into human review packet",
            task_type="rewrite_text",
            deliverable_type="rewrite_note",
            risk_class="low",
            approval_class="none",
            budget_class="low",
            allowed_tools=("artifact_repository",),
        )
    )
    prepare = ledger.start_step(
        session.session_id,
        "system_task",
        input_json={"plan_step_key": "step_input_prepare", "depends_on": [], "step_index": 0},
        correlation_id=f"corr-{uuid.uuid4()}",
        causation_id=f"cause-{uuid.uuid4()}",
        actor_type="assistant",
        actor_id="contract-test",
    )
    merged_text = "merged branch review text"
    ledger.update_step(
        prepare.step_id,
        state="completed",
        output_json={"normalized_text": merged_text, "text_length": len(merged_text)},
        error_json={},
    )
    human_step = ledger.start_step(
        session.session_id,
        "human_task",
        parent_step_id=prepare.step_id,
        input_json={
            "plan_step_key": "step_human_review",
            "depends_on": ["step_input_prepare"],
            "task_type": "communications_review",
            "role_required": "communications_reviewer",
            "brief": "Review merged dependency text.",
            "expected_artifact": "review_packet",
        },
        correlation_id=f"corr-{uuid.uuid4()}",
        causation_id=f"cause-{uuid.uuid4()}",
        actor_type="assistant",
        actor_id="contract-test",
    )

    created = orchestrator._start_human_task_step(session.session_id, human_step)
    assert created.input_json["source_text"] == merged_text
    assert created.input_json["normalized_text"] == merged_text
    assert created.input_json["text_length"] == len(merged_text)


def test_postgres_human_tasks_create_claim_return_and_list() -> None:
    ledger = PostgresExecutionLedgerRepository(_db_url())
    repo = PostgresHumanTaskRepository(_db_url())
    session = ledger.start_session(
        IntentSpecV3(
            principal_id="human-task-tester",
            goal="collect a structured human review packet",
            task_type="rewrite_text",
            deliverable_type="rewrite_note",
            risk_class="medium",
            approval_class="none",
            budget_class="low",
            allowed_tools=("artifact_repository",),
        )
    )
    step = ledger.start_step(
        session.session_id,
        "human_task",
        input_json={"task_type": "communications_review"},
        correlation_id=f"corr-{uuid.uuid4()}",
        causation_id=f"cause-{uuid.uuid4()}",
        actor_type="assistant",
        actor_id="contract-test",
    )

    created = repo.create(
        session_id=session.session_id,
        step_id=step.step_id,
        principal_id=session.intent.principal_id,
        task_type="communications_review",
        role_required="communications_reviewer",
        brief="Review the executive reply before send.",
        authority_required="send_on_behalf_review",
        why_human="External executive-facing communication needs human tone review.",
        quality_rubric_json={"checks": ["tone", "accuracy", "stakeholder_sensitivity"]},
        input_json={"artifact_id": "artifact-1"},
        desired_output_json={"format": "review_packet"},
        priority="high",
        sla_due_at="2000-01-01T00:00:00+00:00",
        resume_session_on_return=True,
    )
    assert created.status == "pending"
    assert created.assignment_state == "unassigned"
    assert created.assignment_source == ""
    assert created.step_id == step.step_id
    assert created.resume_session_on_return is True
    assert created.authority_required == "send_on_behalf_review"
    assert created.why_human == "External executive-facing communication needs human tone review."
    assert created.quality_rubric_json["checks"][0] == "tone"

    listed_principal = repo.list_for_principal(session.intent.principal_id, limit=10)
    assert any(row.human_task_id == created.human_task_id for row in listed_principal)

    listed_role = repo.list_for_principal(
        session.intent.principal_id,
        role_required="communications_reviewer",
        overdue_only=True,
        limit=10,
    )
    assert any(row.human_task_id == created.human_task_id for row in listed_role)

    ownerless_rows = repo.list_for_principal(
        session.intent.principal_id,
        status="pending",
        assignment_state="unassigned",
        assignment_source="none",
        limit=10,
    )
    assert any(row.human_task_id == created.human_task_id for row in ownerless_rows)

    ownerless_counts = repo.count_by_priority_for_principal(
        session.intent.principal_id,
        status="pending",
        assignment_state="unassigned",
        assignment_source="none",
    )
    assert ownerless_counts["high"] == 1

    assigned = repo.assign(
        created.human_task_id,
        operator_id="operator-1",
        assignment_source="manual",
        assigned_by_actor_id="principal-1",
    )
    assert assigned is not None
    assert assigned.assignment_state == "assigned"
    assert assigned.assignment_source == "manual"
    assert assigned.assigned_at
    assert assigned.assigned_by_actor_id == "principal-1"

    claimed = repo.claim(
        created.human_task_id,
        operator_id="operator-1",
        assigned_by_actor_id="operator-1",
    )
    assert claimed is not None
    assert claimed.status == "claimed"
    assert claimed.assignment_state == "claimed"
    assert claimed.assignment_source == "manual"
    assert claimed.assigned_at
    assert claimed.assigned_by_actor_id == "operator-1"
    assert claimed.assigned_operator_id == "operator-1"

    listed_operator = repo.list_for_principal(
        session.intent.principal_id,
        status="claimed",
        assigned_operator_id="operator-1",
        limit=10,
    )
    assert any(row.human_task_id == created.human_task_id for row in listed_operator)

    returned = repo.return_task(
        created.human_task_id,
        operator_id="operator-1",
        resolution="ready_for_send",
        returned_payload_json={"summary": "Reviewed and tightened tone."},
        provenance_json={"review_mode": "human"},
    )
    assert returned is not None
    assert returned.status == "returned"
    assert returned.assignment_state == "returned"
    assert returned.assignment_source == "manual"
    assert returned.assigned_at
    assert returned.assigned_by_actor_id == "operator-1"
    assert returned.resolution == "ready_for_send"
    assert returned.returned_payload_json["summary"] == "Reviewed and tightened tone."
    assert returned.resume_session_on_return is True

    listed_session = repo.list_for_session(session.session_id, limit=10)
    assert any(row.human_task_id == created.human_task_id and row.status == "returned" for row in listed_session)


def test_postgres_operator_profiles_upsert_get_and_list() -> None:
    repo = PostgresOperatorProfileRepository(_db_url())
    operator_id = f"operator-{uuid.uuid4().hex}"

    created = repo.upsert_profile(
        principal_id="exec-1",
        operator_id=operator_id,
        display_name="Senior Reviewer",
        roles=("communications_reviewer",),
        skill_tags=("tone", "accuracy", "stakeholder_sensitivity"),
        trust_tier="senior",
        status="active",
        notes="Primary reviewer for outbound executive comms.",
    )
    assert created.operator_id == operator_id
    assert created.skill_tags[0] == "tone"

    found = repo.get(operator_id)
    assert found is not None
    assert found.trust_tier == "senior"
    assert found.roles == ("communications_reviewer",)

    listed = repo.list_for_principal(principal_id="exec-1", status="active", limit=10)
    assert any(row.operator_id == operator_id for row in listed)


def test_postgres_human_task_operator_assignment_hints() -> None:
    db_url = _db_url()
    ledger = PostgresExecutionLedgerRepository(db_url)
    human_tasks = PostgresHumanTaskRepository(db_url)
    operator_profiles = PostgresOperatorProfileRepository(db_url)
    orchestrator = RewriteOrchestrator(ledger=ledger, human_tasks=human_tasks, operator_profiles=operator_profiles)
    session = ledger.start_session(
        IntentSpecV3(
            principal_id=f"hint-tester-{uuid.uuid4().hex}",
            goal="route a human review packet",
            task_type="rewrite_text",
            deliverable_type="rewrite_note",
            risk_class="medium",
            approval_class="none",
            budget_class="low",
            allowed_tools=("artifact_repository",),
        )
    )
    step = ledger.start_step(
        session.session_id,
        "human_task",
        input_json={"task_type": "communications_review"},
        correlation_id=f"corr-{uuid.uuid4()}",
        causation_id=f"cause-{uuid.uuid4()}",
        actor_type="assistant",
        actor_id="contract-test",
    )
    operator_profiles.upsert_profile(
        principal_id=session.intent.principal_id,
        operator_id="operator-specialist",
        display_name="Senior Reviewer",
        roles=("communications_reviewer",),
        skill_tags=("tone", "accuracy", "stakeholder_sensitivity"),
        trust_tier="senior",
        status="active",
    )
    operator_profiles.upsert_profile(
        principal_id=session.intent.principal_id,
        operator_id="operator-junior",
        display_name="Junior Reviewer",
        roles=("communications_reviewer",),
        skill_tags=("tone",),
        trust_tier="standard",
        status="active",
    )

    created = orchestrator.create_human_task(
        session_id=session.session_id,
        step_id=step.step_id,
        principal_id=session.intent.principal_id,
        task_type="communications_review",
        role_required="communications_reviewer",
        brief="Review the executive draft before send.",
        authority_required="send_on_behalf_review",
        why_human="External executive communication needs human tone review.",
        quality_rubric_json={"checks": ["tone", "accuracy", "stakeholder_sensitivity"]},
        input_json={"artifact_id": "artifact-1"},
        desired_output_json={"format": "review_packet"},
        priority="high",
        sla_due_at="2000-01-01T00:00:00+00:00",
        resume_session_on_return=True,
    )

    assert created.routing_hints_json["required_trust_tier"] == "senior"
    assert created.routing_hints_json["suggested_operator_ids"] == ["operator-specialist"]
    assert created.routing_hints_json["recommended_operator_id"] == "operator-specialist"
    assert created.routing_hints_json["auto_assign_operator_id"] == "operator-specialist"
