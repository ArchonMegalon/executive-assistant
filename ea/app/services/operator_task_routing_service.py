from __future__ import annotations

from typing import Callable

from app.domain.models import ExecutionStep, HumanTask

FetchHumanTaskFn = Callable[[str], HumanTask | None]
ClaimHumanTaskFn = Callable[[str, str, str | None], HumanTask | None]
AssignHumanTaskFn = Callable[[str, str, str, str | None], HumanTask | None]
ReturnHumanTaskFn = Callable[
    [str, str, str | None, dict[str, object] | None, dict[str, object] | None], HumanTask | None
]
GetStepFn = Callable[[str], ExecutionStep | None]
UpdateStepFn = Callable[[str, ...], ExecutionStep | None]
ValidateStepOutputFn = Callable[[ExecutionStep, dict[str, object]], dict[str, object]]
SetSessionStatusFn = Callable[[str, str], object]
AppendEventFn = Callable[[str, str, dict[str, object]], object]
DecorateHumanTaskFn = Callable[[HumanTask], HumanTask]
QueueNextStepAfterFn = Callable[[str, str, str], object]
DrainSessionInlineFn = Callable[[str], object]
AfterHumanTaskReturnFn = Callable[[HumanTask, ExecutionStep], object]
FetchOperatorProfileFn = Callable[[str, str], object | None]


class OperatorTaskRoutingService:
    def __init__(
        self,
        *,
        fetch_human_task: FetchHumanTaskFn,
        claim_human_task: ClaimHumanTaskFn,
        assign_human_task: AssignHumanTaskFn,
        append_event: AppendEventFn,
        return_human_task: ReturnHumanTaskFn | None = None,
        get_step: GetStepFn | None = None,
        update_step: UpdateStepFn | None = None,
        validate_step_output_contract: ValidateStepOutputFn | None = None,
        set_session_status: SetSessionStatusFn | None = None,
        queue_next_step_after: QueueNextStepAfterFn | None = None,
        drain_session_inline: DrainSessionInlineFn | None = None,
        decorate_human_task: DecorateHumanTaskFn | None = None,
        after_human_task_return: AfterHumanTaskReturnFn | None = None,
        fetch_operator_profile: FetchOperatorProfileFn | None = None,
    ) -> None:
        self._fetch_human_task = fetch_human_task
        self._claim_human_task = claim_human_task
        self._assign_human_task = assign_human_task
        self._return_human_task = return_human_task
        self._get_step = get_step
        self._update_step = update_step
        self._validate_step_output_contract = validate_step_output_contract
        self._set_session_status = set_session_status
        self._append_event = append_event
        self._queue_next_step_after = queue_next_step_after
        self._drain_session_inline = drain_session_inline
        self._decorate_human_task = decorate_human_task
        self._after_human_task_return = after_human_task_return
        self._fetch_operator_profile = fetch_operator_profile

    def _operator_profile_exists(self, *, principal_id: str, operator_id: str) -> bool:
        normalized_operator_id = str(operator_id or "").strip()
        if not normalized_operator_id:
            return False
        if self._fetch_operator_profile is None:
            return True
        return self._fetch_operator_profile(normalized_operator_id, str(principal_id or "").strip()) is not None

    def claim_human_task(
        self,
        human_task_id: str,
        *,
        principal_id: str,
        operator_id: str,
        assigned_by_actor_id: str | None = None,
    ) -> HumanTask | None:
        found = self._fetch_human_task(human_task_id)
        if found is None or found.principal_id != str(principal_id or ""):
            return None
        if not self._operator_profile_exists(principal_id=principal_id, operator_id=operator_id):
            return None
        updated = self._claim_human_task(
            human_task_id,
            operator_id=operator_id,
            assigned_by_actor_id=assigned_by_actor_id,
        )
        if updated is None:
            return None

        self._append_event(
            updated.session_id,
            "human_task_claimed",
            {
                "human_task_id": updated.human_task_id,
                "operator_id": updated.assigned_operator_id,
                "assigned_operator_id": updated.assigned_operator_id,
                "assignment_state": updated.assignment_state,
                "assignment_source": "manual",
                "assigned_at": updated.assigned_at or "",
                "assigned_by_actor_id": str(assigned_by_actor_id or operator_id or ""),
                "step_id": updated.step_id or "",
            },
        )
        return updated

    def assign_human_task(
        self,
        human_task_id: str,
        *,
        principal_id: str,
        operator_id: str,
        assignment_source: str = "manual",
        assigned_by_actor_id: str | None = None,
    ) -> HumanTask | None:
        found = self._fetch_human_task(human_task_id)
        if found is None or found.principal_id != str(principal_id or ""):
            return None
        if not self._operator_profile_exists(principal_id=principal_id, operator_id=operator_id):
            return None
        updated = self._assign_human_task(
            human_task_id,
            operator_id=operator_id,
            assignment_source=assignment_source,
            assigned_by_actor_id=assigned_by_actor_id,
        )
        if updated is None:
            return None

        self._append_event(
            updated.session_id,
            "human_task_assigned",
            {
                "human_task_id": updated.human_task_id,
                "operator_id": updated.assigned_operator_id,
                "assigned_operator_id": updated.assigned_operator_id,
                "assignment_state": updated.assignment_state,
                "assignment_source": updated.assignment_source,
                "assigned_at": updated.assigned_at or "",
                "assigned_by_actor_id": updated.assigned_by_actor_id,
                "step_id": updated.step_id or "",
            },
        )
        return updated

    def return_human_task(
        self,
        found: HumanTask,
        *,
        principal_id: str,
        operator_id: str,
        resolution: str,
        returned_payload_json: dict[str, object] | None = None,
        provenance_json: dict[str, object] | None = None,
    ) -> HumanTask | None:
        if (
            self._return_human_task is None
            or self._get_step is None
            or self._update_step is None
            or self._validate_step_output_contract is None
            or self._set_session_status is None
            or self._queue_next_step_after is None
            or self._drain_session_inline is None
            or self._decorate_human_task is None
        ):
            return None
        if found.principal_id != str(principal_id or ""):
            return None
        if not self._operator_profile_exists(principal_id=principal_id, operator_id=operator_id):
            return None
        updated = self._return_human_task(
            found.human_task_id,
            operator_id=operator_id,
            resolution=resolution,
            returned_payload_json=returned_payload_json,
            provenance_json=provenance_json,
        )
        if updated is None:
            return None
        self._append_event(
            updated.session_id,
            "human_task_returned",
            {
                "human_task_id": updated.human_task_id,
                "operator_id": updated.assigned_operator_id,
                "assigned_operator_id": updated.assigned_operator_id,
                "resolution": updated.resolution,
                "assignment_state": updated.assignment_state,
                "assignment_source": "manual",
                "assigned_at": updated.assigned_at or "",
                "assigned_by_actor_id": str(operator_id or ""),
                "step_id": updated.step_id or "",
            },
        )

        if not updated.resume_session_on_return or not updated.step_id:
            return self._decorate_human_task(updated)

        step = self._get_step(updated.step_id)
        if step is None:
            return self._decorate_human_task(updated)

        output_json = dict(step.output_json or {})
        output_json.update(
            {
                "human_task_id": updated.human_task_id,
                "human_resolution": updated.resolution,
                "human_returned_payload_json": updated.returned_payload_json,
                "human_provenance_json": updated.provenance_json,
            }
        )
        output_json = self._validate_step_output_contract(step, output_json)
        self._update_step(
            updated.step_id,
            state="completed",
            output_json=output_json,
            error_json={},
            attempt_count=step.attempt_count,
        )
        refreshed_step = self._get_step(updated.step_id) or step
        if self._after_human_task_return is not None:
            self._after_human_task_return(updated, refreshed_step)
        self._set_session_status(updated.session_id, "running")
        self._append_event(
            updated.session_id,
            "session_resumed_from_human_task",
            {
                "human_task_id": updated.human_task_id,
                "step_id": updated.step_id,
                "resolution": updated.resolution,
            },
        )
        _ = self._queue_next_step_after(updated.session_id, updated.step_id, lease_owner="inline")
        _ = self._drain_session_inline(updated.session_id)
        return self._decorate_human_task(updated)
