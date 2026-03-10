from __future__ import annotations

from app.domain.models import ExecutionStep, HumanTask
from app.services.execution_approval_pause_service import ExecutionApprovalPauseService
from app.services.execution_human_task_step_service import ExecutionHumanTaskStepService
from app.services.execution_step_dependency_service import ExecutionStepDependencyService


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
