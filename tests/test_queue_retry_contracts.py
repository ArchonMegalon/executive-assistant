from __future__ import annotations

import uuid

import pytest

from app.domain.models import (
    ApprovalRequest,
    Artifact,
    IntentSpecV3,
    PlanSpec,
    PlanStepSpec,
    TaskExecutionRequest,
    ToolInvocationResult,
    now_utc_iso,
)
from app.repositories.approvals import InMemoryApprovalRepository
from app.repositories.artifacts import InMemoryArtifactRepository
from app.repositories.task_contracts import InMemoryTaskContractRepository
from app.repositories.ledger import InMemoryExecutionLedgerRepository
from app.repositories.connector_bindings import InMemoryConnectorBindingRepository
from app.repositories.tool_registry import InMemoryToolRegistryRepository
from app.services.orchestrator import RewriteOrchestrator
from app.services.orchestrator import AsyncExecutionQueuedError
from app.services.policy import ApprovalRequiredError
from app.services.planner import PlannerService
from app.services.task_contracts import TaskContractService
from app.services.tool_execution import ToolExecutionService
from app.services.tool_runtime import ToolRuntimeService


class _RecordingLedger(InMemoryExecutionLedgerRepository):
    def __init__(self) -> None:
        super().__init__()
        self.status_updates: list[str] = []
        self.completion_updates: list[str] = []

    def set_session_status(self, session_id: str, status: str):
        self.status_updates.append(str(status))
        return super().set_session_status(session_id, status)

    def complete_session(self, session_id: str, status: str = "completed"):
        self.completion_updates.append(str(status))
        return super().complete_session(session_id, status=status)


def _build_retry_orchestrator(handler):
    ledger = InMemoryExecutionLedgerRepository()
    tool_runtime = ToolRuntimeService(
        tool_registry=InMemoryToolRegistryRepository(),
        connector_bindings=InMemoryConnectorBindingRepository(),
    )
    tool_runtime.upsert_tool(
        tool_name="flaky_tool",
        version="v1",
        input_schema_json={"type": "object"},
        output_schema_json={"type": "object"},
        policy_json={"builtin": False},
        approval_default="none",
        enabled=True,
    )
    tool_execution = ToolExecutionService(tool_runtime=tool_runtime, artifacts=InMemoryArtifactRepository())
    tool_execution.register_handler("flaky_tool", handler)
    orchestrator = RewriteOrchestrator(
        ledger=ledger,
        tool_execution=tool_execution,
    )
    return orchestrator, ledger


def _build_retry_orchestrator_with_ledger(handler, ledger):
    tool_runtime = ToolRuntimeService(
        tool_registry=InMemoryToolRegistryRepository(),
        connector_bindings=InMemoryConnectorBindingRepository(),
    )
    tool_runtime.upsert_tool(
        tool_name="flaky_tool",
        version="v1",
        input_schema_json={"type": "object"},
        output_schema_json={"type": "object"},
        policy_json={"builtin": False},
        approval_default="none",
        enabled=True,
    )
    tool_execution = ToolExecutionService(tool_runtime=tool_runtime, artifacts=InMemoryArtifactRepository())
    tool_execution.register_handler("flaky_tool", handler)
    orchestrator = RewriteOrchestrator(
        ledger=ledger,
        tool_execution=tool_execution,
    )
    return orchestrator, ledger


def _start_retry_step(
    orchestrator: RewriteOrchestrator,
    ledger: InMemoryExecutionLedgerRepository,
    *,
    max_attempts: int,
    retry_backoff_seconds: int,
):
    session = ledger.start_session(
        IntentSpecV3(
            principal_id="exec-1",
            goal="exercise retry runtime",
            task_type="retry_task",
            deliverable_type="retry_note",
            risk_class="low",
            approval_class="none",
            budget_class="low",
            allowed_tools=("flaky_tool",),
        )
    )
    step = ledger.start_step(
        session.session_id,
        "tool_call",
        input_json={
            "plan_id": "plan-retry",
            "plan_step_key": "step_flaky_tool",
            "tool_name": "flaky_tool",
            "action_kind": "flaky.execute",
            "failure_strategy": "retry",
            "max_attempts": max_attempts,
            "retry_backoff_seconds": retry_backoff_seconds,
            "depends_on": [],
            "input_keys": [],
            "output_keys": ["status"],
        },
    )
    queue_item = orchestrator._queue_runtime.enqueue_rewrite_step(session.session_id, step.step_id)
    return session, step, queue_item


def _snapshot_queue_state(snapshot):
    return {
        "session_status": snapshot.session.status,
        "session_events": [row.name for row in snapshot.events],
        "steps": [
            {
                "step_id": row.step_id,
                "state": row.state,
                "attempt_count": row.attempt_count,
                "error_json": row.error_json,
                "output_json": row.output_json,
            }
            for row in snapshot.steps
        ],
        "queue_items": [
            {
                "queue_id": row.queue_id,
                "state": row.state,
                "attempt_count": row.attempt_count,
                "last_error": row.last_error,
                "next_attempt_at": row.next_attempt_at,
                "lease_owner": row.lease_owner,
            }
            for row in snapshot.queue_items
        ],
    }


def _snapshot_human_routing_state(snapshot):
    return {
        "session_status": snapshot.session.status,
        "session_events": [row.name for row in snapshot.events],
        "human_tasks": [
            {
                "human_task_id": row.human_task_id,
                "status": row.status,
                "assignment_state": row.assignment_state,
                "assignment_source": row.assignment_source,
                "assigned_operator_id": row.assigned_operator_id,
                "resume_session_on_return": row.resume_session_on_return,
            }
            for row in snapshot.human_tasks
        ],
    }


def _build_operator_route_snapshot_orchestrator():
    ledger = InMemoryExecutionLedgerRepository()
    orchestrator = RewriteOrchestrator(ledger=ledger)
    orchestrator.upsert_operator_profile(
        principal_id="exec-1",
        operator_id="operator-1",
        display_name="Operator One",
        roles=("reviewer",),
        skill_tags=("policy",),
        trust_tier="standard",
    )
    return orchestrator, ledger


def test_retry_failure_strategy_requeues_a_failed_step_until_it_succeeds() -> None:
    calls = {"count": 0}

    def handler(request, definition):
        calls["count"] += 1
        if calls["count"] == 1:
            raise RuntimeError("temporary_failure")
        return ToolInvocationResult(
            tool_name=definition.tool_name,
            action_kind=str(request.action_kind or "flaky.execute") or "flaky.execute",
            target_ref="retry-target",
            output_json={"status": "ok"},
            receipt_json={"handler_key": definition.tool_name},
        )

    orchestrator, ledger = _build_retry_orchestrator(handler)
    session, step, queue_item = _start_retry_step(
        orchestrator,
        ledger,
        max_attempts=2,
        retry_backoff_seconds=0,
    )

    assert orchestrator.run_queue_item(queue_item.queue_id, lease_owner="worker") is None

    queued_step = ledger.get_step(step.step_id)
    assert queued_step is not None
    assert queued_step.state == "queued"
    assert queued_step.attempt_count == 1
    assert queued_step.error_json["reason"] == "retry_scheduled"
    assert queued_step.error_json["detail"] == "temporary_failure"
    queued_item = ledger.queue_for_session(session.session_id)[0]
    assert queued_item.state == "queued"
    assert queued_item.attempt_count == 1
    assert queued_item.last_error == "temporary_failure"
    assert queued_item.next_attempt_at is not None
    assert ledger.get_session(session.session_id).status == "queued"
    assert "step_retry_scheduled" in [row.name for row in ledger.events_for(session.session_id)]

    assert orchestrator.run_queue_item(queue_item.queue_id, lease_owner="worker") is None

    completed_step = ledger.get_step(step.step_id)
    assert completed_step is not None
    assert completed_step.state == "completed"
    assert completed_step.attempt_count == 2
    completed_item = ledger.queue_for_session(session.session_id)[0]
    assert completed_item.state == "done"
    assert completed_item.attempt_count == 2
    assert ledger.get_session(session.session_id).status == "completed"
    receipts = ledger.receipts_for(session.session_id)
    assert len(receipts) == 1
    assert receipts[0].tool_name == "flaky_tool"
    assert calls["count"] == 2


def test_retry_scheduling_uses_explicit_session_status_transition_api() -> None:
    def handler(request, definition):
        raise RuntimeError("temporary_failure")

    ledger = _RecordingLedger()
    orchestrator, _ = _build_retry_orchestrator_with_ledger(handler, ledger)
    session, step, queue_item = _start_retry_step(
        orchestrator,
        ledger,
        max_attempts=2,
        retry_backoff_seconds=0,
    )

    assert orchestrator.run_queue_item(queue_item.queue_id, lease_owner="worker") is None

    assert ledger.get_session(session.session_id).status == "queued"
    assert ledger.status_updates == ["running", "queued"]
    assert ledger.completion_updates == []
    queued_step = ledger.get_step(step.step_id)
    assert queued_step is not None
    assert queued_step.state == "queued"


def test_retry_failure_strategy_exhausts_into_terminal_session_failure() -> None:
    def handler(request, definition):
        raise RuntimeError("still_broken")

    orchestrator, ledger = _build_retry_orchestrator(handler)
    session, step, queue_item = _start_retry_step(
        orchestrator,
        ledger,
        max_attempts=2,
        retry_backoff_seconds=0,
    )

    assert orchestrator.run_queue_item(queue_item.queue_id, lease_owner="worker") is None

    with pytest.raises(RuntimeError, match="still_broken"):
        orchestrator.run_queue_item(queue_item.queue_id, lease_owner="worker")

    failed_step = ledger.get_step(step.step_id)
    assert failed_step is not None
    assert failed_step.state == "failed"
    assert failed_step.attempt_count == 2
    assert failed_step.error_json["reason"] == "execution_failed"
    failed_item = ledger.queue_for_session(session.session_id)[0]
    assert failed_item.state == "failed"
    assert failed_item.attempt_count == 2
    assert failed_item.last_error == "still_broken"
    assert ledger.get_session(session.session_id).status == "failed"
    event_names = [row.name for row in ledger.events_for(session.session_id)]
    assert event_names.count("step_retry_scheduled") == 1
    assert "session_failed" in event_names


class _StaticRetryPlanner:
    def __init__(self, *, approval_class: str, retry_backoff_seconds: int = 0) -> None:
        self._approval_class = approval_class
        self._retry_backoff_seconds = retry_backoff_seconds

    def build_plan(self, *, task_key: str, principal_id: str, goal: str):
        intent = IntentSpecV3(
            principal_id=principal_id,
            goal=goal,
            task_type=task_key,
            deliverable_type="rewrite_note",
            risk_class="low",
            approval_class=self._approval_class,
            budget_class="low",
            allowed_tools=("artifact_repository",),
        )
        plan = PlanSpec(
            plan_id=str(uuid.uuid4()),
            task_key=task_key,
            principal_id=principal_id,
            created_at=now_utc_iso(),
            steps=(
                PlanStepSpec(
                    step_key="step_input_prepare",
                    step_kind="system_task",
                    tool_name="",
                    evidence_required=(),
                    approval_required=False,
                    reversible=False,
                    expected_artifact="",
                    fallback="request_human_intervention",
                    input_keys=("source_text",),
                    output_keys=("normalized_text", "text_length"),
                ),
                PlanStepSpec(
                    step_key="step_policy_evaluate",
                    step_kind="policy_check",
                    tool_name="",
                    evidence_required=(),
                    approval_required=False,
                    reversible=False,
                    expected_artifact="",
                    fallback="pause_for_approval_or_block",
                    depends_on=("step_input_prepare",),
                    input_keys=("normalized_text", "text_length"),
                    output_keys=("allow", "requires_approval", "reason", "retention_policy", "memory_write_allowed"),
                ),
                PlanStepSpec(
                    step_key="step_artifact_save",
                    step_kind="tool_call",
                    tool_name="artifact_repository",
                    evidence_required=(),
                    approval_required=self._approval_class not in {"", "none"},
                    reversible=False,
                    depends_on=("step_policy_evaluate",),
                    input_keys=("normalized_text",),
                    output_keys=("artifact_id", "receipt_id", "cost_id"),
                    expected_artifact="rewrite_note",
                    fallback="request_human_intervention",
                    owner="tool",
                    authority_class="draft",
                    review_class="none",
                    failure_strategy="retry",
                    max_attempts=2,
                    retry_backoff_seconds=self._retry_backoff_seconds,
                ),
            ),
        )
        return intent, plan


def _build_inline_retry_orchestrator(*, approval_class: str, retry_backoff_seconds: int = 0):
    artifacts = InMemoryArtifactRepository()
    approvals = InMemoryApprovalRepository()
    tool_runtime = ToolRuntimeService(
        tool_registry=InMemoryToolRegistryRepository(),
        connector_bindings=InMemoryConnectorBindingRepository(),
    )
    tool_execution = ToolExecutionService(tool_runtime=tool_runtime, artifacts=artifacts)
    calls = {"count": 0}

    def handler(request, definition):
        calls["count"] += 1
        if calls["count"] == 1:
            raise RuntimeError("temporary_failure")
        artifact = Artifact(
            artifact_id=str(uuid.uuid4()),
            kind=str(request.payload_json.get("expected_artifact") or "rewrite_note"),
            content=str(request.payload_json.get("normalized_text") or request.payload_json.get("source_text") or ""),
            execution_session_id=request.session_id,
            principal_id=str(request.context_json.get("principal_id") or ""),
        )
        artifacts.save(artifact)
        return ToolInvocationResult(
            tool_name=definition.tool_name,
            action_kind=str(request.action_kind or "artifact.save") or "artifact.save",
            target_ref=artifact.artifact_id,
            output_json={"artifact_id": artifact.artifact_id},
            receipt_json={"handler_key": definition.tool_name},
            artifacts=(artifact,),
        )

    tool_execution.register_handler("artifact_repository", handler)
    orchestrator = RewriteOrchestrator(
        artifacts=artifacts,
        approvals=approvals,
        ledger=InMemoryExecutionLedgerRepository(),
        planner=_StaticRetryPlanner(
            approval_class=approval_class,
            retry_backoff_seconds=retry_backoff_seconds,
        ),
        tool_execution=tool_execution,
    )
    return orchestrator, approvals, calls


def test_execute_task_artifact_drains_zero_backoff_retries_inline_to_completion() -> None:
    orchestrator, _approvals, calls = _build_inline_retry_orchestrator(approval_class="none")

    artifact = orchestrator.execute_task_artifact(
        TaskExecutionRequest(
            task_key="retry_inline_rewrite",
            principal_id="exec-1",
            goal="retry inline rewrite",
            input_json={"source_text": "retry me inline"},
        )
    )

    assert artifact.content == "retry me inline"
    snapshot = orchestrator.fetch_session(artifact.execution_session_id)
    assert snapshot is not None
    assert snapshot.session.status == "completed"
    assert snapshot.steps[-1].state == "completed"
    assert snapshot.steps[-1].attempt_count == 2
    assert snapshot.queue_items[-1].state == "done"
    assert snapshot.queue_items[-1].attempt_count == 2
    assert calls["count"] == 2


def test_execute_task_artifact_returns_queued_async_state_for_delayed_retry() -> None:
    orchestrator, _approvals, calls = _build_inline_retry_orchestrator(
        approval_class="none",
        retry_backoff_seconds=30,
    )

    with pytest.raises(AsyncExecutionQueuedError) as exc:
        orchestrator.execute_task_artifact(
            TaskExecutionRequest(
                task_key="retry_delayed_rewrite",
                principal_id="exec-1",
                goal="retry delayed rewrite",
                input_json={"source_text": "retry me later"},
            )
        )

    assert exc.value.status == "queued"
    snapshot = orchestrator.fetch_session(exc.value.session_id)
    assert snapshot is not None
    assert snapshot.session.status == "queued"
    artifact_step = next(row for row in snapshot.steps if row.input_json.get("plan_step_key") == "step_artifact_save")
    assert artifact_step.state == "queued"
    assert artifact_step.attempt_count == 1
    assert artifact_step.error_json["reason"] == "retry_scheduled"
    assert snapshot.queue_items[-1].state == "queued"
    assert snapshot.queue_items[-1].attempt_count == 1
    assert snapshot.queue_items[-1].next_attempt_at
    assert calls["count"] == 1


def test_approval_resume_drains_zero_backoff_retries_inline_to_completion() -> None:
    orchestrator, approvals, calls = _build_inline_retry_orchestrator(approval_class="manager")

    with pytest.raises(ApprovalRequiredError) as exc:
        orchestrator.execute_task_artifact(
            TaskExecutionRequest(
                task_key="retry_inline_approval",
                principal_id="exec-1",
                goal="retry inline rewrite after approval",
                input_json={"source_text": "approval gated retry"},
            )
        )

    pending = approvals.list_pending(limit=10)
    request = next(row for row in pending if row.approval_id == exc.value.approval_id)

    decided = orchestrator.decide_approval(
        request.approval_id,
        decision="approved",
        decided_by="operator",
        reason="approve retry inline",
    )

    assert decided is not None
    snapshot = orchestrator.fetch_session(request.session_id)
    assert snapshot is not None
    assert snapshot.session.status == "completed"
    assert snapshot.steps[-1].state == "completed"
    assert snapshot.steps[-1].attempt_count == 2
    assert snapshot.queue_items[-1].state == "done"
    assert snapshot.queue_items[-1].attempt_count == 2
    assert len(snapshot.artifacts) == 1
    assert snapshot.artifacts[0].content == "approval gated retry"
    assert calls["count"] == 2


def test_approval_resume_keeps_delayed_retry_sessions_async_instead_of_erroring() -> None:
    orchestrator, approvals, calls = _build_inline_retry_orchestrator(
        approval_class="manager",
        retry_backoff_seconds=45,
    )

    with pytest.raises(ApprovalRequiredError) as exc:
        orchestrator.execute_task_artifact(
            TaskExecutionRequest(
                task_key="retry_delayed_approval",
                principal_id="exec-1",
                goal="retry delayed rewrite after approval",
                input_json={"source_text": "approval gated delayed retry"},
            )
        )

    pending = approvals.list_pending(limit=10)
    request = next(row for row in pending if row.approval_id == exc.value.approval_id)

    decided = orchestrator.decide_approval(
        request.approval_id,
        decision="approved",
        decided_by="operator",
        reason="approve delayed retry",
    )

    assert decided is not None
    snapshot = orchestrator.fetch_session(request.session_id)
    assert snapshot is not None
    assert snapshot.session.status == "queued"
    assert snapshot.steps[-1].state == "queued"
    assert snapshot.steps[-1].attempt_count == 1
    assert snapshot.steps[-1].error_json["reason"] == "retry_scheduled"
    assert snapshot.queue_items[-1].state == "queued"
    assert snapshot.queue_items[-1].next_attempt_at
    assert calls["count"] == 1


def test_approval_resume_snapshot_is_stable_for_retry_session_replay() -> None:
    orchestrator, approvals, calls = _build_inline_retry_orchestrator(
        approval_class="manager",
        retry_backoff_seconds=0,
    )

    with pytest.raises(ApprovalRequiredError) as exc:
        orchestrator.execute_task_artifact(
            TaskExecutionRequest(
                task_key="retry_approval_snapshot",
                principal_id="exec-1",
                goal="snapshot approval-driven retry replay",
                input_json={"source_text": "snapshot retry"},
            )
        )

    pending = approvals.list_pending(limit=10)
    request = next(row for row in pending if row.approval_id == exc.value.approval_id)
    pre_approve = _snapshot_queue_state(orchestrator.fetch_session(request.session_id))
    assert pre_approve["session_status"] == "awaiting_approval"
    assert pre_approve["steps"][-1]["state"] == "waiting_approval"
    assert pre_approve["steps"][-1]["attempt_count"] == 1
    assert pre_approve["queue_items"][-1]["state"] == "queued"

    decided = orchestrator.decide_approval(
        request.approval_id,
        decision="approved",
        decided_by="operator",
        reason="replay approval",
    )
    assert decided is not None

    post_approve = _snapshot_queue_state(orchestrator.fetch_session(request.session_id))
    assert post_approve["session_status"] == "completed"
    assert post_approve["steps"][-1]["state"] == "completed"
    assert post_approve["steps"][-1]["attempt_count"] == 2
    assert post_approve["queue_items"][-1]["state"] == "done"
    assert "session_resumed_from_approval" in post_approve["session_events"]
    assert "queue_item_completed" in post_approve["session_events"]
    assert calls["count"] == 2


def test_approval_resume_service_snapshot_is_stable_for_retry_session_replay() -> None:
    orchestrator, approvals, calls = _build_inline_retry_orchestrator(
        approval_class="manager",
        retry_backoff_seconds=0,
    )

    with pytest.raises(ApprovalRequiredError) as exc:
        orchestrator.execute_task_artifact(
            TaskExecutionRequest(
                task_key="retry_approval_service_snapshot",
                principal_id="exec-1",
                goal="snapshot service approval replay",
                input_json={"source_text": "snapshot retry"},
            )
        )

    pending = approvals.list_pending(limit=10)
    request = next(row for row in pending if row.approval_id == exc.value.approval_id)
    pre_approve = _snapshot_queue_state(orchestrator.fetch_session(request.session_id))
    assert pre_approve["session_status"] == "awaiting_approval"
    assert pre_approve["steps"][-1]["state"] == "waiting_approval"
    assert pre_approve["queue_items"][-1]["state"] == "queued"

    decided = orchestrator._approval_resume_service.decide_approval(
        request.approval_id,
        decision="approved",
        decided_by="operator",
        reason="replay approval via service",
    )
    assert decided is not None

    post_approve = _snapshot_queue_state(orchestrator.fetch_session(request.session_id))
    assert post_approve["session_status"] == "completed"
    assert post_approve["steps"][-1]["state"] == "completed"
    assert post_approve["steps"][-1]["attempt_count"] == 2
    assert post_approve["queue_items"][-1]["state"] == "done"
    assert "session_resumed_from_approval" in post_approve["session_events"]
    assert "queue_item_completed" in post_approve["session_events"]
    assert calls["count"] == 2


def test_approval_resume_delayed_retry_snapshot_is_stable_for_async_replay() -> None:
    orchestrator, approvals, calls = _build_inline_retry_orchestrator(
        approval_class="manager",
        retry_backoff_seconds=45,
    )

    with pytest.raises(ApprovalRequiredError) as exc:
        orchestrator.execute_task_artifact(
            TaskExecutionRequest(
                task_key="retry_approval_snapshot_delayed",
                principal_id="exec-1",
                goal="snapshot delayed approval replay",
                input_json={"source_text": "snapshot delayed retry"},
            )
        )

    pending = approvals.list_pending(limit=10)
    request = next(row for row in pending if row.approval_id == exc.value.approval_id)
    pre_approve = _snapshot_queue_state(orchestrator.fetch_session(request.session_id))
    assert pre_approve["session_status"] == "awaiting_approval"
    assert pre_approve["steps"][-1]["state"] == "waiting_approval"
    assert pre_approve["steps"][-1]["attempt_count"] == 1
    assert pre_approve["queue_items"][-1]["state"] == "queued"
    assert pre_approve["queue_items"][-1]["attempt_count"] == 1

    decided = orchestrator.decide_approval(
        request.approval_id,
        decision="approved",
        decided_by="operator",
        reason="replay delayed approval",
    )
    assert decided is not None

    post_approve = _snapshot_queue_state(orchestrator.fetch_session(request.session_id))
    assert post_approve["session_status"] == "queued"
    assert post_approve["steps"][-1]["state"] == "queued"
    assert post_approve["steps"][-1]["attempt_count"] == 1
    assert post_approve["steps"][-1]["error_json"]["reason"] == "retry_scheduled"
    assert post_approve["queue_items"][-1]["state"] == "queued"
    assert post_approve["queue_items"][-1]["attempt_count"] == 1
    assert post_approve["queue_items"][-1]["next_attempt_at"]
    assert "session_resumed_from_approval" in post_approve["session_events"]
    assert "step_retry_scheduled" in post_approve["session_events"]
    assert calls["count"] == 1


def test_execute_task_artifact_uses_compiled_artifact_retry_policy_from_contract_metadata() -> None:
    artifacts = InMemoryArtifactRepository()
    contracts = TaskContractService(InMemoryTaskContractRepository())
    contracts.upsert_contract(
        task_key="rewrite_retry_contract",
        deliverable_type="rewrite_note",
        default_risk_class="low",
        default_approval_class="none",
        allowed_tools=("artifact_repository",),
        memory_write_policy="reviewed_only",
        budget_policy_json={
            "class": "low",
            "artifact_failure_strategy": "retry",
            "artifact_max_attempts": 2,
            "artifact_retry_backoff_seconds": 0,
        },
    )
    tool_runtime = ToolRuntimeService(
        tool_registry=InMemoryToolRegistryRepository(),
        connector_bindings=InMemoryConnectorBindingRepository(),
    )
    tool_execution = ToolExecutionService(tool_runtime=tool_runtime, artifacts=artifacts)
    calls = {"count": 0}

    def handler(request, definition):
        calls["count"] += 1
        if calls["count"] == 1:
            raise RuntimeError("temporary_failure")
        artifact = Artifact(
            artifact_id=str(uuid.uuid4()),
            kind=str(request.payload_json.get("expected_artifact") or "rewrite_note"),
            content=str(request.payload_json.get("normalized_text") or request.payload_json.get("source_text") or ""),
            execution_session_id=request.session_id,
            principal_id=str(request.context_json.get("principal_id") or ""),
        )
        artifacts.save(artifact)
        return ToolInvocationResult(
            tool_name=definition.tool_name,
            action_kind=str(request.action_kind or "artifact.save") or "artifact.save",
            target_ref=artifact.artifact_id,
            output_json={"artifact_id": artifact.artifact_id},
            receipt_json={"handler_key": definition.tool_name},
            artifacts=(artifact,),
        )

    tool_execution.register_handler("artifact_repository", handler)
    orchestrator = RewriteOrchestrator(
        artifacts=artifacts,
        approvals=InMemoryApprovalRepository(),
        ledger=InMemoryExecutionLedgerRepository(),
        task_contracts=contracts,
        planner=PlannerService(contracts),
        tool_execution=tool_execution,
    )

    artifact = orchestrator.execute_task_artifact(
        TaskExecutionRequest(
            task_key="rewrite_retry_contract",
            principal_id="exec-1",
            goal="retry compiled rewrite",
            input_json={"source_text": "compiled retry"},
        )
    )

    assert artifact.content == "compiled retry"
    snapshot = orchestrator.fetch_session(artifact.execution_session_id)
    assert snapshot is not None
    assert snapshot.steps[-1].input_json["failure_strategy"] == "retry"
    assert snapshot.steps[-1].input_json["max_attempts"] == 2
    assert snapshot.steps[-1].input_json["retry_backoff_seconds"] == 0
    assert snapshot.steps[-1].attempt_count == 2
    assert calls["count"] == 2


def test_retry_runtime_snapshot_contract_is_stable_for_queued_retry_flow() -> None:
    calls = {"count": 0}

    def handler(request, definition):
        calls["count"] += 1
        if calls["count"] == 1:
            raise RuntimeError("temporary_failure")
        return ToolInvocationResult(
            tool_name=definition.tool_name,
            action_kind=str(request.action_kind or "flaky.execute") or "flaky.execute",
            target_ref="snapshot-target",
            output_json={"status": "ok"},
            receipt_json={"handler_key": definition.tool_name},
        )

    orchestrator, ledger = _build_retry_orchestrator(handler)
    session, step, queue_item = _start_retry_step(
        orchestrator,
        ledger,
        max_attempts=2,
        retry_backoff_seconds=0,
    )

    assert orchestrator.run_queue_item(queue_item.queue_id, lease_owner="worker") is None
    queued_item = ledger.queue_for_session(session.session_id)[-1]
    assert queued_item.state == "queued"
    assert queued_item.attempt_count == 1

    assert orchestrator.run_queue_item(queue_item.queue_id, lease_owner="worker") is None

    snapshot = orchestrator.fetch_session(session.session_id)
    assert snapshot is not None
    assert snapshot.session.session_id == session.session_id
    assert snapshot.session.status == "completed"
    assert snapshot.steps[-1].attempt_count == 2
    assert snapshot.steps[-1].state == "completed"
    assert snapshot.queue_items[-1].state == "done"
    assert snapshot.receipts and snapshot.receipts[0].tool_name == "flaky_tool"
    event_names = [row.name for row in snapshot.events]
    assert "step_execution_started" in event_names
    assert "step_retry_scheduled" in event_names
    assert "queue_item_completed" in event_names
    assert "session_completed" in event_names


def test_execution_queue_control_snapshot_is_stable_for_retry_leasing_flow() -> None:
    calls = {"count": 0}

    def handler(request, definition):
        calls["count"] += 1
        if calls["count"] == 1:
            raise RuntimeError("temporary_failure")
        return ToolInvocationResult(
            tool_name=definition.tool_name,
            action_kind=str(request.action_kind or "flaky.execute") or "flaky.execute",
            target_ref="snapshot-target",
            output_json={"status": "ok"},
            receipt_json={"handler_key": definition.tool_name},
        )

    orchestrator, ledger = _build_retry_orchestrator(handler)
    session, step, queue_item = _start_retry_step(
        orchestrator,
        ledger,
        max_attempts=2,
        retry_backoff_seconds=0,
    )

    assert orchestrator.run_queue_item(queue_item.queue_id, lease_owner="worker") is None

    snapshot_after_retry = _snapshot_queue_state(orchestrator.fetch_session(session.session_id))
    assert snapshot_after_retry["session_status"] == "queued"
    assert snapshot_after_retry["queue_items"][0]["state"] == "queued"
    assert snapshot_after_retry["queue_items"][0]["lease_owner"] == "worker"
    assert snapshot_after_retry["queue_items"][0]["attempt_count"] == 1
    assert snapshot_after_retry["queue_items"][0]["last_error"] == "temporary_failure"
    assert snapshot_after_retry["steps"][-1]["step_id"] == step.step_id
    assert snapshot_after_retry["steps"][-1]["state"] == "queued"
    assert snapshot_after_retry["steps"][-1]["attempt_count"] == 1
    assert snapshot_after_retry["steps"][-1]["error_json"]["reason"] == "retry_scheduled"
    assert snapshot_after_retry["session_events"][-2:] == [
        "step_execution_started",
        "step_retry_scheduled",
    ]

    assert orchestrator.run_queue_item(queue_item.queue_id, lease_owner="worker") is None

    snapshot_after_completion = _snapshot_queue_state(orchestrator.fetch_session(session.session_id))
    assert snapshot_after_completion["session_status"] == "completed"
    assert snapshot_after_completion["session_events"][-2:] == [
        "queue_item_completed",
        "session_completed",
    ]
    assert snapshot_after_completion["queue_items"][-1]["state"] == "done"
    assert snapshot_after_completion["queue_items"][-1]["attempt_count"] == 2
    assert snapshot_after_completion["queue_items"][-1]["lease_owner"] == ""
    assert snapshot_after_completion["steps"][-1]["state"] == "completed"
    assert snapshot_after_completion["steps"][-1]["attempt_count"] == 2


def test_execute_next_ready_step_can_drains_retry_flow_from_service_boundary() -> None:
    calls = {"count": 0}

    def handler(request, definition):
        calls["count"] += 1
        if calls["count"] == 1:
            raise RuntimeError("temporary_failure")
        return ToolInvocationResult(
            tool_name=definition.tool_name,
            action_kind=str(request.action_kind or "flaky.execute") or "flaky.execute",
            target_ref="snapshot-target",
            output_json={"status": "ok"},
            receipt_json={"handler_key": definition.tool_name},
        )

    orchestrator, ledger = _build_retry_orchestrator(handler)
    session, step, queue_item = _start_retry_step(
        orchestrator,
        ledger,
        max_attempts=2,
        retry_backoff_seconds=0,
    )

    artifact = orchestrator._queue_claim_lease_service.execute_next_ready_step(
        session.session_id,
        lease_owner="inline",
        missing_step_error=f"next step missing for session: {session.session_id}",
    )
    assert artifact is None

    snapshot_after_completion = _snapshot_queue_state(orchestrator.fetch_session(session.session_id))
    assert snapshot_after_completion["session_status"] == "completed"
    assert snapshot_after_completion["queue_items"][-1]["state"] == "done"
    assert snapshot_after_completion["queue_items"][-1]["attempt_count"] == 2
    assert snapshot_after_completion["steps"][-1]["state"] == "completed"
    assert snapshot_after_completion["steps"][-1]["attempt_count"] == 2
    assert calls["count"] == 2


def test_queue_next_step_after_public_wrapper_preserves_service_snapshot_contract() -> None:
    calls = {"count": 0}

    def handler(request, definition):
        calls["count"] += 1
        if calls["count"] == 1:
            raise RuntimeError("temporary_failure")
        return ToolInvocationResult(
            tool_name=definition.tool_name,
            action_kind=str(request.action_kind or "flaky.execute") or "flaky.execute",
            target_ref="snapshot-target",
            output_json={"status": "ok"},
            receipt_json={"handler_key": definition.tool_name},
        )

    orchestrator, ledger = _build_retry_orchestrator(handler)
    session, step, _queue_item = _start_retry_step(
        orchestrator,
        ledger,
        max_attempts=2,
        retry_backoff_seconds=0,
    )

    assert orchestrator._queue_next_step_after(
        session.session_id,
        step.step_id,
        lease_owner="worker",
    ) is None

    snapshot_after_completion = _snapshot_queue_state(orchestrator.fetch_session(session.session_id))
    assert snapshot_after_completion["session_status"] == "completed"
    assert snapshot_after_completion["queue_items"][-1]["state"] == "done"
    assert snapshot_after_completion["queue_items"][-1]["attempt_count"] == 2
    assert snapshot_after_completion["steps"][-1]["state"] == "completed"
    assert snapshot_after_completion["steps"][-1]["attempt_count"] == 2
    assert calls["count"] == 2


def test_execute_next_ready_step_raises_without_ready_step() -> None:
    orchestrator, ledger = _build_retry_orchestrator(lambda request, definition: None)
    session = ledger.start_session(
        IntentSpecV3(
            principal_id="exec-1",
            goal="no-step snapshot replay",
            task_type="none",
            deliverable_type="note",
            risk_class="low",
            approval_class="none",
            budget_class="low",
            allowed_tools=("artifact_repository",),
        )
    )

    with pytest.raises(RuntimeError, match=f"next step missing for session: {session.session_id}"):
        orchestrator._queue_claim_lease_service.execute_next_ready_step(
            session.session_id,
            lease_owner="inline",
            missing_step_error=f"next step missing for session: {session.session_id}",
        )


def test_run_next_queue_item_leased_retry_flow_preserves_queue_snapshot() -> None:
    calls = {"count": 0}

    def handler(request, definition):
        calls["count"] += 1
        if calls["count"] == 1:
            raise RuntimeError("temporary_failure")
        return ToolInvocationResult(
            tool_name=definition.tool_name,
            action_kind=str(request.action_kind or "flaky.execute") or "flaky.execute",
            target_ref="snapshot-target",
            output_json={"status": "ok"},
            receipt_json={"handler_key": definition.tool_name},
        )

    orchestrator, _ledger = _build_retry_orchestrator(handler)
    session, _, _ = _start_retry_step(
        orchestrator,
        _ledger,
        max_attempts=2,
        retry_backoff_seconds=0,
    )

    assert orchestrator.run_next_queue_item(lease_owner="worker") is None

    snapshot_after_retry = _snapshot_queue_state(orchestrator.fetch_session(session.session_id))
    assert snapshot_after_retry["session_status"] == "queued"
    assert snapshot_after_retry["queue_items"][-1]["state"] == "queued"
    assert snapshot_after_retry["queue_items"][-1]["lease_owner"] == "worker"
    assert snapshot_after_retry["queue_items"][-1]["attempt_count"] == 1
    assert snapshot_after_retry["steps"][-1]["state"] == "queued"
    assert snapshot_after_retry["steps"][-1]["attempt_count"] == 1

    assert orchestrator.run_next_queue_item(lease_owner="worker") is None

    snapshot_after_completion = _snapshot_queue_state(orchestrator.fetch_session(session.session_id))
    assert snapshot_after_completion["session_status"] == "completed"
    assert snapshot_after_completion["queue_items"][-1]["state"] == "done"
    assert snapshot_after_completion["queue_items"][-1]["attempt_count"] == 2
    assert snapshot_after_completion["queue_items"][-1]["lease_owner"] == ""
    assert snapshot_after_completion["steps"][-1]["state"] == "completed"
    assert snapshot_after_completion["steps"][-1]["attempt_count"] == 2


def test_operator_routing_snapshot_is_stable_for_claim_and_return() -> None:
    orchestrator, ledger = _build_operator_route_snapshot_orchestrator()
    session = ledger.start_session(
        IntentSpecV3(
            principal_id="exec-1",
            goal="operator routing snapshot lock",
            task_type="human_review",
            deliverable_type="review_packet",
            risk_class="low",
            approval_class="none",
            budget_class="low",
            allowed_tools=("artifact_repository",),
        )
    )
    task = orchestrator.create_human_task(
        session_id=session.session_id,
        principal_id="exec-1",
        task_type="human_review",
        role_required="reviewer",
        brief="snapshot route review",
        authority_required="observe",
        quality_rubric_json={"checks": ["evidence", "privacy"]},
        input_json={"source_text": "snapshot operator payload"},
        desired_output_json={"format": "review_packet"},
    )

    baseline = _snapshot_human_routing_state(orchestrator.fetch_session(session.session_id))
    assert baseline["session_status"] == "running"
    assert baseline["human_tasks"][0]["status"] == "pending"
    assert baseline["human_tasks"][0]["assignment_state"] == "unassigned"
    assert baseline["human_tasks"][0]["assignment_source"] == ""
    assert "human_task_created" in baseline["session_events"]

    claimed = orchestrator.claim_human_task(
        task.human_task_id,
        principal_id="exec-1",
        operator_id="operator-1",
        assigned_by_actor_id="op-webhook",
    )
    assert claimed is not None
    after_claim = _snapshot_human_routing_state(orchestrator.fetch_session(session.session_id))
    assert after_claim["human_tasks"][0]["status"] == "claimed"
    assert after_claim["human_tasks"][0]["assignment_state"] == "claimed"
    assert after_claim["human_tasks"][0]["assigned_operator_id"] == "operator-1"
    assert "human_task_claimed" in after_claim["session_events"]

    assigned = orchestrator.assign_human_task(
        task.human_task_id,
        principal_id="exec-1",
        operator_id="operator-1",
        assignment_source="manual",
        assigned_by_actor_id="op-assign",
    )
    assert assigned is not None
    after_assign = _snapshot_human_routing_state(orchestrator.fetch_session(session.session_id))
    assert after_assign["human_tasks"][0]["assignment_source"] == "manual"
    assert "human_task_assigned" in after_assign["session_events"]

    returned = orchestrator.return_human_task(
        task.human_task_id,
        principal_id="exec-1",
        operator_id="operator-1",
        resolution="needs_rework",
        returned_payload_json={"notes": "needs context"},
        provenance_json={"reviewer": "operator-1"},
    )
    assert returned is not None
    after_return = _snapshot_human_routing_state(orchestrator.fetch_session(session.session_id))
    assert after_return["human_tasks"][0]["status"] == "returned"
    assert after_return["human_tasks"][0]["assignment_source"] == "manual"
    assert "human_task_returned" in after_return["session_events"]


def test_operator_routing_service_snapshot_is_stable_for_claim_and_return() -> None:
    orchestrator, ledger = _build_operator_route_snapshot_orchestrator()
    session = ledger.start_session(
        IntentSpecV3(
            principal_id="exec-1",
            goal="operator service routing snapshot lock",
            task_type="human_review",
            deliverable_type="review_packet",
            risk_class="low",
            approval_class="none",
            budget_class="low",
            allowed_tools=("artifact_repository",),
        )
    )
    task = orchestrator._operator_routing_service.create_human_task(
        session_id=session.session_id,
        principal_id="exec-1",
        task_type="human_review",
        role_required="reviewer",
        brief="snapshot route review",
        authority_required="observe",
        quality_rubric_json={"checks": ["evidence", "privacy"]},
        input_json={"source_text": "snapshot operator payload"},
        desired_output_json={"format": "review_packet"},
    )

    baseline = _snapshot_human_routing_state(orchestrator.fetch_session(session.session_id))
    assert baseline["session_status"] == "running"
    assert baseline["human_tasks"][0]["status"] == "pending"
    assert baseline["human_tasks"][0]["assignment_state"] == "unassigned"
    assert baseline["human_tasks"][0]["assignment_source"] == ""

    claimed = orchestrator._operator_routing_service.claim_human_task(
        task.human_task_id,
        principal_id="exec-1",
        operator_id="operator-1",
        assigned_by_actor_id="op-webhook",
    )
    assert claimed is not None
    after_claim = _snapshot_human_routing_state(orchestrator.fetch_session(session.session_id))
    assert after_claim["human_tasks"][0]["status"] == "claimed"
    assert after_claim["human_tasks"][0]["assignment_state"] == "claimed"
    assert after_claim["human_tasks"][0]["assigned_operator_id"] == "operator-1"
    assert "human_task_claimed" in after_claim["session_events"]

    assigned = orchestrator._operator_routing_service.assign_human_task(
        task.human_task_id,
        principal_id="exec-1",
        operator_id="operator-1",
        assignment_source="manual",
        assigned_by_actor_id="op-assign",
    )
    assert assigned is not None
    after_assign = _snapshot_human_routing_state(orchestrator.fetch_session(session.session_id))
    assert after_assign["human_tasks"][0]["assignment_source"] == "manual"
    assert "human_task_assigned" in after_assign["session_events"]

    found = orchestrator._operator_routing_service.fetch_human_task(task.human_task_id, principal_id="exec-1")
    assert found is not None
    returned = orchestrator._operator_routing_service.return_human_task(
        found,
        principal_id="exec-1",
        operator_id="operator-1",
        resolution="needs_rework",
        returned_payload_json={"notes": "needs context"},
        provenance_json={"reviewer": "operator-1"},
    )
    assert returned is not None
    after_return = _snapshot_human_routing_state(orchestrator.fetch_session(session.session_id))
    assert after_return["human_tasks"][0]["status"] == "returned"
    assert after_return["human_tasks"][0]["assignment_source"] == "manual"
    assert "human_task_returned" in after_return["session_events"]


def test_operator_profile_service_preserves_principal_scoped_snapshot_contract() -> None:
    orchestrator, _ledger = _build_operator_route_snapshot_orchestrator()

    created = orchestrator._operator_profile_service.upsert_operator_profile(
        principal_id="exec-1",
        operator_id="operator-2",
        display_name="Operator Two",
        roles=("reviewer", "approver"),
        skill_tags=("policy", "privacy"),
        trust_tier="elevated",
        notes="snapshot contract",
    )

    assert created.operator_id == "operator-2"
    fetched = orchestrator._operator_profile_service.fetch_operator_profile(
        "operator-2",
        principal_id="exec-1",
    )
    assert fetched is not None
    assert fetched.display_name == "Operator Two"
    assert orchestrator._operator_profile_service.fetch_operator_profile(
        "operator-2",
        principal_id="other-principal",
    ) is None

    listed = orchestrator._operator_profile_service.list_operator_profiles(
        principal_id="exec-1",
        status="active",
        limit=10,
    )
    assert [row.operator_id for row in listed] == ["operator-1", "operator-2"]
