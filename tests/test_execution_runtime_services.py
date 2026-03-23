from __future__ import annotations

import pytest

from app.domain.models import Artifact, ExecutionStep, HumanTask, IntentSpecV3, PolicyDecision, ToolInvocationResult
from app.repositories.task_contracts import InMemoryTaskContractRepository
from app.services.execution_async_state_service import ExecutionAsyncStateService
from app.services.execution_approval_resume_service import ExecutionApprovalResumeService
from app.services.execution_runtime_services import ExecutionStepRuntimeService as ExportedExecutionStepRuntimeService
from app.services.execution_approval_pause_service import ExecutionApprovalPauseService
from app.services.execution_human_task_step_service import ExecutionHumanTaskStepService
from app.services.execution_queue_claim_lease_service import MissingReadyStepError
from app.services.execution_queue_runtime_service import ExecutionQueueRuntimeService
from app.services.execution_operator_routing_service import ExecutionOperatorRoutingService
from app.services.execution_step_dependency_service import ExecutionStepDependencyService
from app.services.execution_step_runtime_service import ExecutionStepRuntimeService
from app.services.execution_task_orchestration_service import ExecutionTaskOrchestrationService
from app.services.memory_reasoning_service import ContextPack
from app.services.skills import SkillCatalogService
from app.services.task_contracts import TaskContractService


def _step(
    *,
    step_id: str,
    step_kind: str,
    state: str,
    input_json: dict[str, object],
    output_json: dict[str, object] | None = None,
) -> ExecutionStep:
    return ExecutionStep(
        step_id=step_id,
        session_id="session-1",
        parent_step_id=None,
        step_kind=step_kind,
        state=state,
        attempt_count=0,
        input_json=input_json,
        output_json=output_json or {},
        error_json={},
        correlation_id="corr-1",
        causation_id="cause-1",
        actor_type="assistant",
        actor_id="test",
        created_at="2026-03-10T00:00:00+00:00",
        updated_at="2026-03-10T00:00:00+00:00",
    )


def _human_task(**overrides: object) -> HumanTask:
    base = {
        "human_task_id": "human-1",
        "session_id": "session-1",
        "step_id": "step-human",
        "principal_id": "exec-1",
        "task_type": "communications_review",
        "role_required": "communications_reviewer",
        "brief": "Review this.",
        "authority_required": "",
        "why_human": "",
        "quality_rubric_json": {},
        "input_json": {},
        "desired_output_json": {"format": "review_packet"},
        "priority": "high",
        "sla_due_at": None,
        "status": "pending",
        "assignment_state": "unassigned",
        "assigned_operator_id": "",
        "assignment_source": "",
        "assigned_at": None,
        "assigned_by_actor_id": "",
        "resolution": "",
        "created_at": "2026-03-10T00:00:00+00:00",
        "updated_at": "2026-03-10T00:00:00+00:00",
        "resume_session_on_return": True,
        "routing_hints_json": {"auto_assign_operator_id": "operator-1"},
    }
    base.update(overrides)
    return HumanTask(**base)


def test_execution_runtime_services_exports_execution_step_runtime_service() -> None:
    assert ExportedExecutionStepRuntimeService is ExecutionStepRuntimeService


def test_execution_step_dependency_service_merges_dependency_outputs_and_filters_by_declared_inputs() -> None:
    dependency = _step(
        step_id="step-prepare",
        step_kind="system_task",
        state="completed",
        input_json={"plan_step_key": "step_input_prepare"},
        output_json={"normalized_text": "Prepared text", "text_length": 13, "leaked": "nope"},
    )
    child = _step(
        step_id="step-save",
        step_kind="tool_call",
        state="queued",
        input_json={
            "plan_step_key": "step_artifact_save",
            "depends_on": ["step_input_prepare"],
            "input_keys": ["normalized_text"],
        },
    )
    service = ExecutionStepDependencyService(
        get_step=lambda step_id: dependency if step_id == dependency.step_id else None,
        steps_for_session=lambda session_id: [dependency, child],
    )

    merged = service.merged_step_input_json("session-1", child)

    assert merged["normalized_text"] == "Prepared text"
    assert merged["source_text"] == "Prepared text"
    assert "leaked" not in merged


def test_execution_step_dependency_service_dependency_outputs_override_seeded_task_input_and_synthesize_diff() -> None:
    prepare = _step(
        step_id="step-prepare",
        step_kind="system_task",
        state="completed",
        input_json={"plan_step_key": "step_input_prepare"},
        output_json={"normalized_text": "original text", "source_text": "original text", "text_length": 13},
    )
    structured = _step(
        step_id="step-structured",
        step_kind="tool_call",
        state="completed",
        input_json={"plan_step_key": "step_structured_generate", "depends_on": ["step_input_prepare"]},
        output_json={"normalized_text": "revised text", "preview_text": "revised text"},
    )
    review = _step(
        step_id="step-review",
        step_kind="tool_call",
        state="queued",
        input_json={
            "plan_step_key": "step_reasoned_patch_review",
            "depends_on": ["step_structured_generate"],
            "input_keys": ["normalized_text", "source_text", "diff_text"],
            "source_text": "seeded source",
            "normalized_text": "seeded original",
        },
    )
    service = ExecutionStepDependencyService(
        get_step=lambda step_id: None,
        steps_for_session=lambda session_id: [prepare, structured, review],
    )

    merged = service.merged_step_input_json("session-1", review)

    assert merged["source_text"] == "seeded source"
    assert merged["normalized_text"] == "revised text"
    assert "revised text" in merged["diff_text"] or "+revised text" in merged["diff_text"]


def test_execution_task_orchestration_service_uses_jury_action_kind_for_audit_review_steps() -> None:
    service = ExecutionTaskOrchestrationService.__new__(ExecutionTaskOrchestrationService)
    audit_step = type(
        "PlanStepStub",
        (),
        {
            "step_kind": "tool_call",
            "tool_name": "provider.brain_router.reasoned_patch_review",
            "brain_profile": "audit",
            "posthoc_review_profile": "",
        },
    )()
    review_light_step = type(
        "PlanStepStub",
        (),
        {
            "step_kind": "tool_call",
            "tool_name": "provider.brain_router.reasoned_patch_review",
            "brain_profile": "review_light",
            "posthoc_review_profile": "",
        },
    )()

    assert service.default_action_kind_for_step(audit_step) == "audit.jury"
    assert service.default_action_kind_for_step(review_light_step) == "audit.review_light"


def test_execution_step_dependency_service_selects_latest_approval_target_step() -> None:
    prepare = _step(
        step_id="step-prepare",
        step_kind="system_task",
        state="completed",
        input_json={"plan_step_key": "step_input_prepare"},
    )
    tool = _step(
        step_id="step-tool",
        step_kind="tool_call",
        state="queued",
        input_json={"plan_step_key": "step_tool"},
    )
    human = _step(
        step_id="step-human",
        step_kind="human_task",
        state="queued",
        input_json={"plan_step_key": "step_human", "approval_required": True},
    )
    service = ExecutionStepDependencyService(
        get_step=lambda step_id: None,
        steps_for_session=lambda session_id: [prepare, tool, human],
    )

    assert service.approval_target_step_for_session("session-1") == human


def test_execution_queue_runtime_service_passes_keyword_idempotency_key() -> None:
    calls: list[tuple[str, str, str]] = []
    service = ExecutionQueueRuntimeService(
        enqueue_step=lambda session_id, step_id, *, idempotency_key: calls.append((session_id, step_id, idempotency_key))
        or type("QueueItemStub", (), {"queue_id": "queue-1", "state": "queued"})(),
        retry_queue_item=lambda queue_id, last_error=None, next_attempt_at=None: None,
        update_step=lambda step_id, **kwargs: None,
        set_session_status=lambda session_id, status: None,
        append_event=lambda session_id, name, payload: None,
        step_id_to_retry_key=lambda session_id, step_id: f"retry:{session_id}:{step_id}",
    )

    queue_item = service.enqueue_rewrite_step("session-1", "step-1")

    assert queue_item.queue_id == "queue-1"
    assert calls == [("session-1", "step-1", "retry:session-1:step-1")]


def test_execution_approval_pause_service_updates_waiting_step_and_session() -> None:
    calls: list[tuple[str, object]] = []
    target_step = _step(
        step_id="step-approval",
        step_kind="tool_call",
        state="queued",
        input_json={"plan_step_key": "step_artifact_save"},
    )
    service = ExecutionApprovalPauseService(
        create_request=lambda session_id, step_id, **kwargs: type(
            "ApprovalRequestStub",
            (),
            {"approval_id": "approval-1", "session_id": session_id, "step_id": step_id},
        )(),
        update_step=lambda step_id, **kwargs: calls.append(("update_step", (step_id, kwargs))) or target_step,
        set_session_status=lambda session_id, status: calls.append(("set_session_status", (session_id, status))),
        append_event=lambda session_id, name, payload: calls.append(("append_event", (session_id, name, payload))),
    )

    request = service.pause_for_approval(
        session_id="session-1",
        target_step=target_step,
        reason="approval_required",
        requested_action_json={"action": "artifact.save"},
    )

    assert request.approval_id == "approval-1"
    assert calls[0][0] == "update_step"
    assert calls[1] == ("set_session_status", ("session-1", "awaiting_approval"))
    assert calls[2][0] == "append_event"


def test_execution_human_task_step_service_starts_and_auto_assigns_human_task() -> None:
    created = _human_task()
    assigned = _human_task(
        assignment_state="assigned",
        assigned_operator_id="operator-1",
        assignment_source="auto_preselected",
    )
    events: list[tuple[str, str, dict[str, object]]] = []
    service = ExecutionHumanTaskStepService(
        get_session=lambda session_id: type(
            "SessionStub",
            (),
            {"intent": type("IntentStub", (), {"principal_id": "exec-1"})()},
        )(),
        merged_step_input_json=lambda session_id, step: {
            "task_type": "communications_review",
            "role_required": "communications_reviewer",
            "brief": "Review this.",
            "priority": "high",
            "auto_assign_if_unique": True,
            "source_text": "Prepared text",
            "normalized_text": "Prepared text",
            "text_length": 13,
            "plan_step_key": "step_human_review",
            "desired_output_json": {"format": "review_packet"},
        },
        create_human_task=lambda **kwargs: created,
        assign_human_task=lambda human_task_id, **kwargs: assigned,
        append_event=lambda session_id, name, payload: events.append((session_id, name, payload)),
        decorate_human_task=lambda row: row,
    )

    row = service.start_human_task_step(
        "session-1",
        _step(
            step_id="step-human",
            step_kind="human_task",
            state="running",
            input_json={"plan_step_key": "step_human_review"},
        ),
    )

    assert row.assignment_state == "assigned"
    assert row.assigned_operator_id == "operator-1"
    assert events[-1][1] == "human_task_step_started"


def test_execution_operator_routing_service_return_human_task_by_id_returns_none_when_missing() -> None:
    service = ExecutionOperatorRoutingService(
        human_task_routing=type("RoutingStub", (), {})(),
        operator_task_routing=type("OperatorRoutingStub", (), {})(),
        get_session=lambda session_id: None,
        get_step=lambda step_id: None,
        update_step=lambda step_id, **kwargs: None,
        append_event=lambda session_id, name, payload: None,
        set_session_status=lambda session_id, status: None,
        create_human_task=lambda **kwargs: _human_task(),
        require_session_principal_alignment=lambda session, principal_id: None,
        fetch_human_task=lambda human_task_id: None,
        list_human_tasks_for_session=lambda session_id, limit: [],
        list_human_tasks_for_principal=lambda principal_id, **kwargs: [],
        count_human_tasks_by_priority=lambda principal_id, **kwargs: {},
        fetch_session_for_principal=lambda session_id, principal_id: None,
        fetch_operator_profile=lambda operator_id, principal_id: None,
    )

    returned = service.return_human_task_by_id(
        "human-1",
        principal_id="exec-1",
        operator_id="operator-1",
        resolution="completed",
    )

    assert returned is None


def test_execution_operator_routing_service_return_human_task_by_id_delegates_to_operator_routing() -> None:
    returned = _human_task(status="completed", resolution="approved")
    service = ExecutionOperatorRoutingService(
        human_task_routing=type("RoutingStub", (), {"decorate_human_task": lambda self, row: row})(),
        operator_task_routing=type(
            "OperatorRoutingStub",
            (),
            {
                "return_human_task": lambda self, found, **kwargs: returned,
            },
        )(),
        get_session=lambda session_id: None,
        get_step=lambda step_id: None,
        update_step=lambda step_id, **kwargs: None,
        append_event=lambda session_id, name, payload: None,
        set_session_status=lambda session_id, status: None,
        create_human_task=lambda **kwargs: _human_task(),
        require_session_principal_alignment=lambda session, principal_id: None,
        fetch_human_task=lambda human_task_id: _human_task(human_task_id=human_task_id, principal_id="exec-1"),
        list_human_tasks_for_session=lambda session_id, limit: [],
        list_human_tasks_for_principal=lambda principal_id, **kwargs: [],
        count_human_tasks_by_priority=lambda principal_id, **kwargs: {},
        fetch_session_for_principal=lambda session_id, principal_id: None,
        fetch_operator_profile=lambda operator_id, principal_id: None,
    )

    found = service.return_human_task_by_id(
        "human-1",
        principal_id="exec-1",
        operator_id="operator-1",
        resolution="completed",
    )

    assert found is returned


def test_execution_approval_resume_service_keeps_queued_follow_on_work() -> None:
    service = ExecutionApprovalResumeService(
        decide_approval=lambda approval_id, decision, decided_by, reason: (
            type("ApprovalRequestStub", (), {"approval_id": approval_id, "session_id": "session-1", "step_id": "step-1"})(),
            type(
                "ApprovalDecisionStub",
                (),
                {"decision_id": "decision-1", "approval_id": approval_id, "decision": "approved", "decided_by": decided_by, "reason": reason},
            )(),
        ),
        append_event=lambda session_id, name, payload: None,
        update_step=lambda step_id, **kwargs: type("ExecutionStepStub", (), {"step_id": step_id})(),
        set_session_status=lambda session_id, status: None,
        execute_next_ready_step=lambda session_id: None,
        fetch_session=lambda session_id: type(
            "SnapshotStub",
            (),
            {
                "session": type("SessionStub", (), {"session_id": session_id, "status": "running"})(),
                "queue_items": [type("QueueItemStub", (), {"queue_id": "queue-1", "state": "queued"})()],
            },
        )(),
        delayed_retry_queue_item=lambda snapshot: None,
    )

    found = service.decide_approval(
        "approval-1",
        decision="approved",
        decided_by="operator-1",
        reason="looks good",
    )

    assert found is not None


def test_execution_approval_resume_service_keeps_queued_work_when_ready_step_already_queued() -> None:
    service = ExecutionApprovalResumeService(
        decide_approval=lambda approval_id, decision, decided_by, reason: (
            type("ApprovalRequestStub", (), {"approval_id": approval_id, "session_id": "session-1", "step_id": "step-1"})(),
            type(
                "ApprovalDecisionStub",
                (),
                {"decision_id": "decision-1", "approval_id": approval_id, "decision": "approved", "decided_by": decided_by, "reason": reason},
            )(),
        ),
        append_event=lambda session_id, name, payload: None,
        update_step=lambda step_id, **kwargs: type("ExecutionStepStub", (), {"step_id": step_id})(),
        set_session_status=lambda session_id, status: None,
        execute_next_ready_step=lambda session_id: (_ for _ in ()).throw(
            MissingReadyStepError(
                f"approved queue item did not resolve a ready step: {session_id}",
                session_id=session_id,
            )
        ),
        fetch_session=lambda session_id: type(
            "SnapshotStub",
            (),
            {
                "session": type("SessionStub", (), {"session_id": session_id, "status": "running"})(),
                "queue_items": [type("QueueItemStub", (), {"queue_id": "queue-1", "state": "running"})()],
            },
        )(),
        delayed_retry_queue_item=lambda snapshot: None,
    )

    found = service.decide_approval(
        "approval-1",
        decision="approved",
        decided_by="operator-1",
        reason="looks good",
    )

    assert found is not None


def test_execution_approval_resume_service_keeps_unknown_nonterminal_queue_state() -> None:
    service = ExecutionApprovalResumeService(
        decide_approval=lambda approval_id, decision, decided_by, reason: (
            type("ApprovalRequestStub", (), {"approval_id": approval_id, "session_id": "session-1", "step_id": "step-1"})(),
            type(
                "ApprovalDecisionStub",
                (),
                {"decision_id": "decision-1", "approval_id": approval_id, "decision": "approved", "decided_by": decided_by, "reason": reason},
            )(),
        ),
        append_event=lambda session_id, name, payload: None,
        update_step=lambda step_id, **kwargs: type("ExecutionStepStub", (), {"step_id": step_id})(),
        set_session_status=lambda session_id, status: None,
        execute_next_ready_step=lambda session_id: None,
        fetch_session=lambda session_id: type(
            "SnapshotStub",
            (),
            {
                "session": type("SessionStub", (), {"session_id": session_id, "status": "running"})(),
                "queue_items": [type("QueueItemStub", (), {"queue_id": "queue-1", "state": "waiting_retry"})()],
            },
        )(),
        delayed_retry_queue_item=lambda snapshot: None,
    )

    found = service.decide_approval(
        "approval-1",
        decision="approved",
        decided_by="operator-1",
        reason="looks good",
    )

    assert found is not None


def test_execution_approval_resume_service_keeps_failed_or_blocked_post_resume_status() -> None:
    for status in ("failed", "blocked"):
        service = ExecutionApprovalResumeService(
            decide_approval=lambda approval_id, decision, decided_by, reason: (
                type("ApprovalRequestStub", (), {"approval_id": approval_id, "session_id": "session-1", "step_id": "step-1"})(),
                type(
                    "ApprovalDecisionStub",
                    (),
                    {
                        "decision_id": "decision-1",
                        "approval_id": approval_id,
                        "decision": "approved",
                        "decided_by": decided_by,
                        "reason": reason,
                    },
                )(),
            ),
            append_event=lambda session_id, name, payload: None,
            update_step=lambda step_id, **kwargs: type("ExecutionStepStub", (), {"step_id": step_id})(),
            set_session_status=lambda session_id, status: None,
            execute_next_ready_step=lambda session_id: None,
            fetch_session=lambda session_id: type(
                "SnapshotStub",
                (),
                {
                    "session": type("SessionStub", (), {"session_id": session_id, "status": status})(),
                    "queue_items": [type("QueueItemStub", (), {"queue_id": "queue-1", "state": "done"})()],
                },
            )(),
            delayed_retry_queue_item=lambda snapshot: None,
        )

        found = service.decide_approval(
            "approval-1",
            decision="approved",
            decided_by="operator-1",
            reason="looks good",
        )

        assert found is not None


def test_execution_approval_resume_service_raises_without_async_or_queued_continuation() -> None:
    service = ExecutionApprovalResumeService(
        decide_approval=lambda approval_id, decision, decided_by, reason: (
            type("ApprovalRequestStub", (), {"approval_id": approval_id, "session_id": "session-1", "step_id": "step-1"})(),
            type(
                "ApprovalDecisionStub",
                (),
                {"decision_id": "decision-1", "approval_id": approval_id, "decision": "approved", "decided_by": decided_by, "reason": reason},
            )(),
        ),
        append_event=lambda session_id, name, payload: None,
        update_step=lambda step_id, **kwargs: type("ExecutionStepStub", (), {"step_id": step_id})(),
        set_session_status=lambda session_id, status: None,
        execute_next_ready_step=lambda session_id: None,
        fetch_session=lambda session_id: type(
            "SnapshotStub",
            (),
            {
                "session": type("SessionStub", (), {"session_id": session_id, "status": "running"})(),
                "queue_items": [type("QueueItemStub", (), {"queue_id": "queue-1", "state": "done"})()],
            },
        )(),
        delayed_retry_queue_item=lambda snapshot: None,
    )

    try:
        service.decide_approval(
            "approval-1",
            decision="approved",
            decided_by="operator-1",
            reason="looks good",
        )
        assert False, "expected approved queue item guard to raise"
    except RuntimeError as exc:
        assert "approved queue item did not execute: session-1" in str(exc)


def test_execution_step_runtime_service_completes_input_prepare_with_evidence_pack_projection() -> None:
    calls: list[tuple[str, object]] = []
    step_dependency_service = ExecutionStepDependencyService(
        get_step=lambda step_id: None,
        steps_for_session=lambda session_id: [],
    )
    service = ExecutionStepRuntimeService(
        get_session=lambda session_id: None,
        get_artifact=lambda artifact_id: None,
        update_step=lambda step_id, **kwargs: calls.append(("update_step", (step_id, kwargs))) or None,
        append_event=lambda session_id, name, payload: calls.append(("append_event", (session_id, name, payload))),
        append_policy_decision=lambda session_id, decision: None,
        append_tool_receipt=lambda *args, **kwargs: None,
        append_run_cost=lambda *args, **kwargs: None,
        set_session_status=lambda session_id, status: None,
        approval_target_step_for_session=lambda session_id: None,
        step_dependency_service=step_dependency_service,
        approval_pause_service=ExecutionApprovalPauseService(
            create_request=lambda session_id, step_id, **kwargs: None,
            update_step=lambda step_id, **kwargs: None,
            set_session_status=lambda session_id, status: None,
            append_event=lambda session_id, name, payload: None,
        ),
        human_task_step_service=ExecutionHumanTaskStepService(
            get_session=lambda session_id: None,
            merged_step_input_json=lambda session_id, step: {},
            create_human_task=lambda **kwargs: _human_task(),
            assign_human_task=lambda human_task_id, **kwargs: None,
            append_event=lambda session_id, name, payload: None,
            decorate_human_task=lambda row: row,
        ),
        policy=type("PolicyStub", (), {"evaluate_step": lambda *args, **kwargs: None})(),
        tool_execution=type("ToolStub", (), {"execute_invocation": lambda *args, **kwargs: None})(),
        memory_runtime=None,
    )
    step = _step(
        step_id="step-prepare",
        step_kind="system_task",
        state="running",
        input_json={
            "plan_step_key": "step_input_prepare",
            "source_text": "Prepared text",
            "desired_output_json": {"artifact_output_template": "evidence_pack", "default_confidence": 0.7},
            "claims": ["claim-1"],
            "context_refs": ["evidence-1"],
            "open_questions": ["question-1"],
            "output_keys": ["normalized_text", "text_length", "structured_output_json", "preview_text", "mime_type"],
        },
    )

    service.complete_input_prepare_step("session-1", step)

    update_call = calls[0]
    output_json = update_call[1][1]["output_json"]
    assert output_json["structured_output_json"]["format"] == "evidence_pack"
    assert output_json["structured_output_json"]["confidence"] == 0.7
    assert output_json["preview_text"] == "Prepared text"
    assert calls[1][0] == "append_event"


def test_execution_step_runtime_service_pauses_policy_target_when_approval_required() -> None:
    paused: list[tuple[str, str, dict[str, object]]] = []
    target_step = _step(
        step_id="step-tool",
        step_kind="tool_call",
        state="queued",
        input_json={
            "plan_step_key": "step_artifact_save",
            "tool_name": "artifact_repository",
            "action_kind": "artifact.save",
            "expected_artifact": "rewrite_note",
        },
    )
    policy_step = _step(
        step_id="step-policy",
        step_kind="policy_check",
        state="running",
        input_json={
            "plan_step_key": "step_policy_evaluate",
            "plan_id": "plan-1",
            "output_keys": ["allow", "requires_approval", "reason", "retention_policy", "memory_write_allowed"],
        },
    )
    step_dependency_service = ExecutionStepDependencyService(
        get_step=lambda step_id: target_step if step_id == target_step.step_id else None,
        steps_for_session=lambda session_id: [policy_step, target_step],
    )
    service = ExecutionStepRuntimeService(
        get_session=lambda session_id: type(
            "SessionStub",
            (),
            {
                "intent": IntentSpecV3(
                    principal_id="exec-1",
                    goal="goal",
                    task_type="rewrite_text",
                    deliverable_type="rewrite_note",
                    risk_class="low",
                    approval_class="manager",
                    budget_class="low",
                )
            },
        )(),
        get_artifact=lambda artifact_id: None,
        update_step=lambda step_id, **kwargs: target_step if step_id == target_step.step_id else policy_step,
        append_event=lambda session_id, name, payload: None,
        append_policy_decision=lambda session_id, decision: None,
        append_tool_receipt=lambda *args, **kwargs: None,
        append_run_cost=lambda *args, **kwargs: None,
        set_session_status=lambda session_id, status: None,
        approval_target_step_for_session=lambda session_id: target_step,
        step_dependency_service=step_dependency_service,
        approval_pause_service=type(
            "PauseStub",
            (),
            {
                "pause_for_approval": lambda self, *, session_id, target_step, reason, requested_action_json: paused.append(
                    (session_id, reason, requested_action_json)
                )
            },
        )(),
        human_task_step_service=ExecutionHumanTaskStepService(
            get_session=lambda session_id: None,
            merged_step_input_json=lambda session_id, step: {},
            create_human_task=lambda **kwargs: _human_task(),
            assign_human_task=lambda human_task_id, **kwargs: None,
            append_event=lambda session_id, name, payload: None,
            decorate_human_task=lambda row: row,
        ),
        policy=type(
            "PolicyStub",
            (),
            {
                "evaluate_step": lambda self, intent, normalized_text, **kwargs: PolicyDecision(
                    allow=True,
                    requires_approval=True,
                    reason="approval_required",
                    retention_policy="keep",
                    memory_write_allowed=True,
                )
            },
        )(),
        tool_execution=type("ToolStub", (), {"execute_invocation": lambda *args, **kwargs: None})(),
        memory_runtime=None,
    )

    service.complete_policy_evaluate_step("session-1", policy_step)

    assert paused == [
        (
            "session-1",
            "approval_required",
            {
                "action": "artifact.save",
                "artifact_kind": "rewrite_note",
                "text_length": 0,
                "plan_id": "plan-1",
                "plan_step_key": "step_artifact_save",
                "tool_name": "artifact_repository",
                "channel": "",
                "step_kind": "tool_call",
                "authority_class": "observe",
                "review_class": "none",
            },
        )
    ]


def test_execution_step_runtime_service_completes_tool_step_and_persists_receipt_cost_and_artifact_event() -> None:
    calls: list[tuple[str, object]] = []
    artifact = Artifact(
        artifact_id="artifact-1",
        kind="rewrite_note",
        content="Done",
        execution_session_id="session-1",
        principal_id="exec-1",
    )
    step_dependency_service = ExecutionStepDependencyService(
        get_step=lambda step_id: None,
        steps_for_session=lambda session_id: [],
    )
    service = ExecutionStepRuntimeService(
        get_session=lambda session_id: type(
            "SessionStub",
            (),
            {
                "intent": IntentSpecV3(
                    principal_id="exec-1",
                    goal="goal",
                    task_type="rewrite_text",
                    deliverable_type="rewrite_note",
                    risk_class="low",
                    approval_class="none",
                    budget_class="low",
                )
            },
        )(),
        get_artifact=lambda artifact_id: artifact if artifact_id == "artifact-1" else None,
        update_step=lambda step_id, **kwargs: calls.append(("update_step", (step_id, kwargs))) or None,
        append_event=lambda session_id, name, payload: calls.append(("append_event", (session_id, name, payload))),
        append_policy_decision=lambda session_id, decision: None,
        append_tool_receipt=lambda session_id, step_id, **kwargs: type("ReceiptStub", (), {"receipt_id": "receipt-1"})(),
        append_run_cost=lambda session_id, **kwargs: type("CostStub", (), {"cost_id": "cost-1"})(),
        set_session_status=lambda session_id, status: None,
        approval_target_step_for_session=lambda session_id: None,
        step_dependency_service=step_dependency_service,
        approval_pause_service=ExecutionApprovalPauseService(
            create_request=lambda session_id, step_id, **kwargs: None,
            update_step=lambda step_id, **kwargs: None,
            set_session_status=lambda session_id, status: None,
            append_event=lambda session_id, name, payload: None,
        ),
        human_task_step_service=ExecutionHumanTaskStepService(
            get_session=lambda session_id: None,
            merged_step_input_json=lambda session_id, step: {},
            create_human_task=lambda **kwargs: _human_task(),
            assign_human_task=lambda human_task_id, **kwargs: None,
            append_event=lambda session_id, name, payload: None,
            decorate_human_task=lambda row: row,
        ),
        policy=type("PolicyStub", (), {"evaluate_step": lambda *args, **kwargs: None})(),
        tool_execution=type(
            "ToolStub",
            (),
            {
                "execute_invocation": lambda self, request: ToolInvocationResult(
                    tool_name=request.tool_name,
                    action_kind=request.action_kind,
                    target_ref="artifact://artifact-1",
                    output_json={"artifact_id": "artifact-1"},
                    receipt_json={"ok": True},
                    artifacts=(artifact,),
                    model_name="none",
                    tokens_in=0,
                    tokens_out=0,
                    cost_usd=0.0,
                )
            },
        )(),
        memory_runtime=None,
    )
    step = _step(
        step_id="step-tool",
        step_kind="tool_call",
        state="running",
        input_json={
            "plan_step_key": "step_artifact_save",
            "tool_name": "artifact_repository",
            "action_kind": "artifact.save",
            "output_keys": ["artifact_id", "receipt_id", "cost_id"],
        },
    )

    result = service.complete_tool_step("session-1", step)

    assert result == artifact
    output_json = calls[1][1][1]["output_json"]
    assert output_json["receipt_id"] == "receipt-1"
    assert output_json["cost_id"] == "cost-1"
    assert calls[-1] == (
        "append_event",
        ("session-1", "artifact_persisted", {"artifact_id": "artifact-1", "artifact_kind": "rewrite_note", "plan_id": "", "plan_step_key": ""}),
    )


def test_execution_step_runtime_service_emits_tool_started_before_invocation_failure() -> None:
    calls: list[tuple[str, object]] = []
    step_dependency_service = ExecutionStepDependencyService(
        get_step=lambda step_id: None,
        steps_for_session=lambda session_id: [],
    )
    service = ExecutionStepRuntimeService(
        get_session=lambda session_id: type(
            "SessionStub",
            (),
            {
                "intent": IntentSpecV3(
                    principal_id="exec-1",
                    goal="goal",
                    task_type="rewrite_text",
                    deliverable_type="rewrite_note",
                    risk_class="low",
                    approval_class="none",
                    budget_class="low",
                )
            },
        )(),
        get_artifact=lambda artifact_id: None,
        update_step=lambda step_id, **kwargs: calls.append(("update_step", (step_id, kwargs))) or None,
        append_event=lambda session_id, name, payload: calls.append(("append_event", (session_id, name, payload))),
        append_policy_decision=lambda session_id, decision: None,
        append_tool_receipt=lambda session_id, step_id, **kwargs: type("ReceiptStub", (), {"receipt_id": "receipt-1"})(),
        append_run_cost=lambda session_id, **kwargs: type("CostStub", (), {"cost_id": "cost-1"})(),
        set_session_status=lambda session_id, status: None,
        approval_target_step_for_session=lambda session_id: None,
        step_dependency_service=step_dependency_service,
        approval_pause_service=ExecutionApprovalPauseService(
            create_request=lambda session_id, step_id, **kwargs: None,
            update_step=lambda step_id, **kwargs: None,
            set_session_status=lambda session_id, status: None,
            append_event=lambda session_id, name, payload: None,
        ),
        human_task_step_service=ExecutionHumanTaskStepService(
            get_session=lambda session_id: None,
            merged_step_input_json=lambda session_id, step: {},
            create_human_task=lambda **kwargs: _human_task(),
            assign_human_task=lambda human_task_id, **kwargs: None,
            append_event=lambda session_id, name, payload: None,
            decorate_human_task=lambda row: row,
        ),
        policy=type("PolicyStub", (), {"evaluate_step": lambda *args, **kwargs: None})(),
        tool_execution=type(
            "ToolStub",
            (),
            {
                "execute_invocation": lambda self, request: (_ for _ in ()).throw(RuntimeError("tool_failed")),
            },
        )(),
        memory_runtime=None,
    )
    step = _step(
        step_id="step-tool-fail",
        step_kind="tool_call",
        state="running",
        input_json={
            "plan_step_key": "step_artifact_save",
            "tool_name": "artifact_repository",
            "action_kind": "artifact.save",
        },
    )

    with pytest.raises(RuntimeError, match="tool_failed"):
        service.complete_tool_step("session-1", step)

    event_names = [entry[1][1] for entry in calls if entry[0] == "append_event"]
    assert event_names == ["tool_execution_started"]


def test_execution_task_orchestration_service_materializes_plan_steps_and_returns_direct_artifact() -> None:
    events: list[tuple[str, str, dict[str, object]]] = []
    started_steps: list[tuple[str, str | None, dict[str, object]]] = []
    session = type(
        "SessionStub",
        (),
        {
            "session_id": "session-1",
            "intent": IntentSpecV3(
                principal_id="exec-1",
                goal="goal",
                task_type="rewrite_text",
                deliverable_type="rewrite_note",
                risk_class="low",
                approval_class="none",
                budget_class="low",
            ),
        },
    )()
    artifact = Artifact(
        artifact_id="artifact-1",
        kind="rewrite_note",
        content="Done",
        execution_session_id="session-1",
        principal_id="exec-1",
    )
    service = ExecutionTaskOrchestrationService(
        ledger=type(
            "LedgerStub",
            (),
            {
                "start_session": lambda self, intent: session,
                "append_event": lambda self, session_id, name, payload: events.append((session_id, name, payload)),
                "start_step": lambda self, session_id, step_kind, parent_step_id=None, input_json=None, **kwargs: started_steps.append(
                    (step_kind, parent_step_id, dict(input_json or {}))
                )
                or type("StepStub", (), {"step_id": f"step-{len(started_steps)}"})(),
            },
        )(),
        planner=None,
        task_contracts=None,
        execute_next_ready_step=lambda session_id: artifact,
        fetch_session_snapshot=lambda session_id: type(
            "SnapshotStub",
            (),
            {"session": type("SnapshotSession", (), {"status": "completed"})(), "artifacts": [artifact]},
        )(),
        async_state_service=type("AsyncStateStub", (), {"raise_for_snapshot_state": lambda self, snapshot: None})(),
    )

    result = service.execute_task_artifact(
        type(
            "TaskReq",
            (),
            {
                "task_key": "rewrite_text",
                "principal_id": "exec-1",
                "goal": "",
                "text": "Prepared text",
                "context_refs": (),
                "input_json": {},
            },
        )()
    )

    assert result == artifact
    assert [event[1] for event in events] == ["intent_compiled", "plan_compiled"]
    assert len(started_steps) == 3
    assert started_steps[1][1] == "step-1"
    assert started_steps[2][1] == "step-2"
    assert started_steps[0][2]["source_text"] == "Prepared text"
    assert started_steps[2][2]["action_kind"] == "artifact.save"


def test_execution_task_orchestration_service_returns_snapshot_artifact_when_inline_execute_finishes_without_direct_result() -> None:
    artifact = Artifact(
        artifact_id="artifact-2",
        kind="rewrite_note",
        content="Done",
        execution_session_id="session-2",
        principal_id="exec-1",
    )
    session = type(
        "SessionStub",
        (),
        {
            "session_id": "session-2",
            "intent": IntentSpecV3(
                principal_id="exec-1",
                goal="goal",
                task_type="rewrite_text",
                deliverable_type="rewrite_note",
                risk_class="low",
                approval_class="none",
                budget_class="low",
            ),
        },
    )()
    service = ExecutionTaskOrchestrationService(
        ledger=type(
            "LedgerStub",
            (),
            {
                "start_session": lambda self, intent: session,
                "append_event": lambda self, session_id, name, payload: None,
                "start_step": lambda self, session_id, step_kind, parent_step_id=None, input_json=None, **kwargs: type(
                    "StepStub",
                    (),
                    {"step_id": f"{step_kind}-{parent_step_id or 'root'}"},
                )(),
            },
        )(),
        planner=None,
        task_contracts=None,
        execute_next_ready_step=lambda session_id: None,
        fetch_session_snapshot=lambda session_id: type(
            "SnapshotStub",
            (),
            {"session": type("SnapshotSession", (), {"status": "completed"})(), "artifacts": [artifact]},
        )(),
        async_state_service=type("AsyncStateStub", (), {"raise_for_snapshot_state": lambda self, snapshot: None})(),
    )

    result = service.execute_task_artifact(
        type(
            "TaskReq",
            (),
            {
                "task_key": "rewrite_text",
                "principal_id": "exec-1",
                "goal": "",
                "text": "Prepared text",
                "context_refs": (),
                "input_json": {},
            },
        )()
    )

    assert result == artifact


def test_execution_task_orchestration_service_adds_context_pack_to_task_input() -> None:
    service = ExecutionTaskOrchestrationService(
        ledger=type("LedgerStub", (), {})(),
        planner=None,
        task_contracts=None,
        execute_next_ready_step=lambda session_id: None,
        fetch_session_snapshot=lambda session_id: None,
        async_state_service=type("AsyncStateStub", (), {"raise_for_snapshot_state": lambda self, snapshot: None})(),
        memory_reasoning_service=type(
            "ReasoningStub",
            (),
            {
                "build_context_pack": lambda self, **kwargs: ContextPack(
                    principal_id=kwargs["principal_id"],
                    task_key=kwargs["task_key"],
                    goal=kwargs["goal"],
                    context_refs=kwargs["context_refs"],
                    summary="1 active commitment",
                )
            },
        )(),
    )

    payload = service.normalized_task_input_json(
        type(
            "TaskReq",
            (),
            {
                "task_key": "rewrite_text",
                "principal_id": "exec-1",
                "goal": "Draft board follow-up",
                "text": "Prepared text",
                "context_refs": ("memory:item:item-1",),
                "input_json": {},
            },
        )(),
        principal_id="exec-1",
        task_key="rewrite_text",
        goal="Draft board follow-up",
    )

    assert payload["context_pack"]["principal_id"] == "exec-1"
    assert payload["context_pack"]["task_key"] == "rewrite_text"
    assert payload["context_pack"]["context_refs"] == ["memory:item:item-1"]


def test_execution_task_orchestration_service_resolves_skill_key_through_catalog() -> None:
    contracts = TaskContractService(InMemoryTaskContractRepository())
    skills = SkillCatalogService(contracts)
    skills.upsert_skill(
        skill_key="browseract_bootstrap_manager",
        task_key="browseract_bootstrap_manager",
        name="BrowserAct Bootstrap Manager",
        description="Build BrowserAct workflow spec packets.",
        deliverable_type="browseract_workflow_spec_packet",
        workflow_template="tool_then_artifact",
        allowed_tools=("browseract.build_workflow_spec", "artifact_repository"),
        memory_write_policy="none",
        budget_policy_json={
            "class": "medium",
            "workflow_template": "tool_then_artifact",
            "pre_artifact_capability_key": "workflow_spec_build",
        },
    )
    started_steps: list[tuple[str, str | None, dict[str, object]]] = []
    session = type(
        "SessionStub",
        (),
        {
            "session_id": "session-skill-1",
            "intent": IntentSpecV3(
                principal_id="exec-1",
                goal="goal",
                task_type="browseract_bootstrap_manager",
                deliverable_type="browseract_workflow_spec_packet",
                risk_class="medium",
                approval_class="none",
                budget_class="medium",
            ),
        },
    )()
    artifact = Artifact(
        artifact_id="artifact-skill-1",
        kind="browseract_workflow_spec_packet",
        content="Done",
        execution_session_id="session-skill-1",
        principal_id="exec-1",
    )
    service = ExecutionTaskOrchestrationService(
        ledger=type(
            "LedgerStub",
            (),
            {
                "start_session": lambda self, intent: session,
                "append_event": lambda self, session_id, name, payload: None,
                "start_step": lambda self, session_id, step_kind, parent_step_id=None, input_json=None, **kwargs: started_steps.append(
                    (step_kind, parent_step_id, dict(input_json or {}))
                )
                or type("StepStub", (), {"step_id": f"step-{len(started_steps)}"})(),
            },
        )(),
        planner=None,
        task_contracts=contracts,
        skills=skills,
        execute_next_ready_step=lambda session_id: artifact,
        fetch_session_snapshot=lambda session_id: type(
            "SnapshotStub",
            (),
            {"session": type("SnapshotSession", (), {"status": "completed"})(), "artifacts": [artifact]},
        )(),
        async_state_service=type("AsyncStateStub", (), {"raise_for_snapshot_state": lambda self, snapshot: None})(),
    )

    result = service.execute_task_artifact(
        type(
            "TaskReq",
            (),
            {
                "task_key": "",
                "skill_key": "browseract_bootstrap_manager",
                "principal_id": "exec-1",
                "goal": "",
                "text": "",
                "context_refs": (),
                "input_json": {
                    "workflow_name": "Prompt Forge",
                    "purpose": "Build a BrowserAct workflow spec.",
                    "login_url": "https://browseract.example/login",
                    "tool_url": "https://browseract.example/tool",
                },
            },
        )()
    )

    assert result == artifact
    assert started_steps[0][2]["skill_key"] == "browseract_bootstrap_manager"
    assert started_steps[0][2]["workflow_name"] == "Prompt Forge"


def test_execution_async_state_service_raises_approval_with_matching_request() -> None:
    snapshot = type(
        "SnapshotStub",
        (),
        {
            "session": type("SessionStub", (), {"session_id": "session-1", "status": "awaiting_approval"})(),
            "human_tasks": [],
        },
    )()
    approvals = [
        type("ApprovalStub", (), {"approval_id": "approval-1", "session_id": "session-1"})(),
        type("ApprovalStub", (), {"approval_id": "approval-2", "session_id": "session-2"})(),
    ]
    raised: list[tuple[str, str]] = []
    service = ExecutionAsyncStateService(
        list_pending_approvals=lambda limit: approvals,
        list_recent_policy_decisions=lambda limit, session_id=None: [],
        delayed_retry_queue_item=lambda snapshot: None,
        raise_human_task_required=lambda snapshot: None,
        raise_approval_required=lambda snapshot, approval_id: raised.append((snapshot.session.session_id, approval_id)),
        raise_policy_denied=lambda reason: None,
        raise_async_execution_queued=lambda snapshot, next_attempt_at: None,
    )

    service.raise_for_snapshot_state(snapshot)

    assert raised == [("session-1", "approval-1")]
