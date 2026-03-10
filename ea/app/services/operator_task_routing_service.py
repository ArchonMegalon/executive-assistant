from __future__ import annotations

from typing import Callable

from app.domain.models import HumanTask

FetchHumanTaskFn = Callable[[str, str], HumanTask | None]
ClaimHumanTaskFn = Callable[[str, str, str | None], HumanTask | None]
AssignHumanTaskFn = Callable[[str, str, str, str | None], HumanTask | None]
AppendEventFn = Callable[[str, str, dict[str, object]], object]


class OperatorTaskRoutingService:
    def __init__(
        self,
        *,
        fetch_human_task: FetchHumanTaskFn,
        claim_human_task: ClaimHumanTaskFn,
        assign_human_task: AssignHumanTaskFn,
        append_event: AppendEventFn,
    ) -> None:
        self._fetch_human_task = fetch_human_task
        self._claim_human_task = claim_human_task
        self._assign_human_task = assign_human_task
        self._append_event = append_event

    def claim_human_task(
        self,
        human_task_id: str,
        *,
        principal_id: str,
        operator_id: str,
        assigned_by_actor_id: str | None = None,
    ) -> HumanTask | None:
        found = self._fetch_human_task(human_task_id, principal_id)
        if found is None:
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
        found = self._fetch_human_task(human_task_id, principal_id)
        if found is None:
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
