from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Callable

from app.domain.models import ExecutionSession, ExecutionStep, HumanTask


class ExecutionHumanTaskStepService:
    def __init__(
        self,
        *,
        get_session: Callable[[str], ExecutionSession | None],
        merged_step_input_json: Callable[[str, ExecutionStep], dict[str, object]],
        create_human_task: Callable[..., HumanTask],
        assign_human_task: Callable[..., HumanTask | None],
        append_event: Callable[[str, str, dict[str, object]], object],
        decorate_human_task: Callable[[HumanTask], HumanTask],
    ) -> None:
        self._get_session = get_session
        self._merged_step_input_json = merged_step_input_json
        self._create_human_task = create_human_task
        self._assign_human_task = assign_human_task
        self._append_event = append_event
        self._decorate_human_task = decorate_human_task

    def start_human_task_step(self, session_id: str, rewrite_step: ExecutionStep) -> HumanTask:
        session = self._get_session(session_id)
        if session is None:
            raise RuntimeError(f"session missing for human-task step: {session_id}")
        input_json = self._merged_step_input_json(session_id, rewrite_step)
        desired_output_json = dict(input_json.get("desired_output_json") or {})
        if not str(desired_output_json.get("format") or "").strip():
            desired_output_json["format"] = str(input_json.get("expected_artifact") or "review_packet")
        priority = str(input_json.get("priority") or "normal").strip() or "normal"
        sla_due_at = str(input_json.get("sla_due_at") or "").strip()
        if not sla_due_at:
            try:
                sla_minutes = int(input_json.get("sla_minutes") or 0)
            except (TypeError, ValueError):
                sla_minutes = 0
            if sla_minutes > 0:
                sla_due_at = (datetime.now(timezone.utc) + timedelta(minutes=sla_minutes)).isoformat()
        row = self._create_human_task(
            session_id=session_id,
            step_id=rewrite_step.step_id,
            principal_id=session.intent.principal_id,
            task_type=str(input_json.get("task_type") or "communications_review"),
            role_required=str(input_json.get("role_required") or "communications_reviewer"),
            brief=str(input_json.get("brief") or "Review the prepared rewrite before finalizing the artifact."),
            authority_required=str(input_json.get("authority_required") or ""),
            why_human=str(input_json.get("why_human") or ""),
            quality_rubric_json=dict(input_json.get("quality_rubric_json") or {}),
            input_json={
                "source_text": str(input_json.get("source_text") or ""),
                "normalized_text": str(input_json.get("normalized_text") or input_json.get("source_text") or ""),
                "text_length": int(input_json.get("text_length") or 0),
                "plan_id": str(input_json.get("plan_id") or ""),
                "plan_step_key": str(input_json.get("plan_step_key") or ""),
            },
            desired_output_json=desired_output_json,
            priority=priority,
            sla_due_at=sla_due_at or None,
            resume_session_on_return=True,
        )
        if bool(input_json.get("auto_assign_if_unique")):
            auto_assign_operator_id = str((row.routing_hints_json or {}).get("auto_assign_operator_id") or "").strip()
            if auto_assign_operator_id:
                updated = self._assign_human_task(
                    row.human_task_id,
                    principal_id=session.intent.principal_id,
                    operator_id=auto_assign_operator_id,
                    assignment_source="auto_preselected",
                    assigned_by_actor_id="orchestrator:auto_preselected",
                )
                if updated is not None:
                    row = updated
        self._append_event(
            session_id,
            "human_task_step_started",
            {
                "step_id": rewrite_step.step_id,
                "human_task_id": row.human_task_id,
                "task_type": row.task_type,
                "role_required": row.role_required,
                "authority_required": row.authority_required,
                "priority": row.priority,
                "sla_due_at": row.sla_due_at or "",
                "assignment_state": row.assignment_state,
                "assigned_operator_id": row.assigned_operator_id,
                "assignment_source": row.assignment_source,
                "assigned_at": row.assigned_at or "",
                "assigned_by_actor_id": row.assigned_by_actor_id,
            },
        )
        return self._decorate_human_task(row)
