from __future__ import annotations

from app.domain.models import ExecutionQueueItem, ExecutionSessionSnapshot, HumanTask
from app.services.execution_queue_runtime_facade import ExecutionQueueRuntimeFacade
from app.services.human_task_routing_runtime_service import HumanTaskRoutingService
from app.services.operator_task_routing_service import OperatorTaskRoutingService


class ExecutionQueueClaimLeaseService:
    def __init__(self, runtime: ExecutionQueueRuntimeFacade) -> None:
        self._runtime = runtime

    def delayed_retry_queue_item(self, snapshot: ExecutionSessionSnapshot) -> ExecutionQueueItem | None:
        return self._runtime.delayed_retry_queue_item(snapshot)

    def active_queue_step_ids(self, session_id: str) -> set[str]:
        return self._runtime.active_queue_step_ids(session_id)

    def queue_item_is_eligible_now(self, row: ExecutionQueueItem) -> bool:
        return self._runtime.queue_item_is_eligible_now(row)

    def next_eligible_queue_item_for_session(self, session_id: str) -> ExecutionQueueItem | None:
        return self._runtime.next_eligible_queue_item_for_session(session_id)

    def drain_session_inline(
        self,
        session_id: str,
        *,
        stop_before_step_id: str | None = None,
    ):
        return self._runtime.drain_session_inline(
            session_id,
            stop_before_step_id=stop_before_step_id,
        )

    def ready_steps(
        self,
        session_id: str,
        *,
        stop_before_step_id: str | None = None,
    ):
        return self._runtime.ready_steps(
            session_id,
            stop_before_step_id=stop_before_step_id,
        )

    def next_ready_step(
        self,
        session_id: str,
        *,
        stop_before_step_id: str | None = None,
    ):
        return self._runtime.next_ready_step(
            session_id,
            stop_before_step_id=stop_before_step_id,
        )

    def queue_next_step_after(
        self,
        session_id: str,
        step_id: str,
        *,
        lease_owner: str,
        stop_before_step_id: str | None = None,
    ):
        return self._runtime.queue_next_step_after(
            session_id,
            step_id,
            lease_owner=lease_owner,
            stop_before_step_id=stop_before_step_id,
        )

    def execute_leased_queue_item(
        self,
        queue_item: ExecutionQueueItem,
        *,
        stop_before_step_id: str | None = None,
    ):
        return self._runtime.execute_leased_queue_item(
            queue_item,
            stop_before_step_id=stop_before_step_id,
        )

    def run_queue_item(
        self,
        queue_id: str,
        *,
        lease_owner: str = "inline",
        stop_before_step_id: str | None = None,
    ):
        return self._runtime.run_queue_item(
            queue_id,
            lease_owner=lease_owner,
            stop_before_step_id=stop_before_step_id,
        )

    def run_next_queue_item(
        self,
        *,
        lease_owner: str = "worker",
    ):
        return self._runtime.run_next_queue_item(lease_owner=lease_owner)


class ExecutionOperatorRoutingService:
    def __init__(
        self,
        *,
        human_task_routing: HumanTaskRoutingService,
        operator_task_routing: OperatorTaskRoutingService,
    ) -> None:
        self._human_task_routing = human_task_routing
        self._operator_task_routing = operator_task_routing

    def required_skill_tags(self, row: HumanTask) -> tuple[str, ...]:
        return self._human_task_routing.required_skill_tags(row)

    def required_trust_rank(self, authority_required: str) -> int:
        return self._human_task_routing.required_trust_rank(authority_required)

    def required_trust_tier(self, authority_required: str) -> str:
        return self._human_task_routing.required_trust_tier(authority_required)

    def operator_match_details(self, profile, row: HumanTask) -> dict[str, object]:
        return self._human_task_routing.operator_match_details(profile, row)

    def build_human_task_routing_hints(self, row: HumanTask) -> dict[str, object]:
        return self._human_task_routing.build_human_task_routing_hints(row)

    def human_task_assignment_events(self, row: HumanTask) -> list:
        return self._human_task_routing.human_task_assignment_events(row)

    def build_human_task_last_transition_summary(self, row: HumanTask) -> dict[str, object]:
        return self._human_task_routing.build_human_task_last_transition_summary(row)

    def decorate_human_task(self, row: HumanTask) -> HumanTask:
        return self._human_task_routing.decorate_human_task(row)

    def sort_human_tasks(
        self,
        rows: list[HumanTask],
        *,
        sort: str | None = None,
    ) -> list[HumanTask]:
        return self._human_task_routing.sort_human_tasks(rows, sort=sort)

    def filter_human_task_rows(
        self,
        rows: list[HumanTask],
        *,
        principal_id: str,
        status: str | None = None,
        role_required: str | None = None,
        priority: str | None = None,
        assigned_operator_id: str | None = None,
        assignment_state: str | None = None,
        assignment_source: str | None = None,
        overdue_only: bool = False,
    ) -> list[HumanTask]:
        return self._human_task_routing.filter_human_task_rows(
            rows,
            principal_id=principal_id,
            status=status,
            role_required=role_required,
            priority=priority,
            assigned_operator_id=assigned_operator_id,
            assignment_state=assignment_state,
            assignment_source=assignment_source,
            overdue_only=overdue_only,
        )

    def operator_matches_human_task(self, profile, row: HumanTask) -> bool:
        return self._human_task_routing.operator_matches_human_task(profile, row)

    def claim_human_task(
        self,
        human_task_id: str,
        *,
        principal_id: str,
        operator_id: str,
        assigned_by_actor_id: str | None = None,
    ) -> HumanTask | None:
        return self._operator_task_routing.claim_human_task(
            human_task_id,
            principal_id=principal_id,
            operator_id=operator_id,
            assigned_by_actor_id=assigned_by_actor_id,
        )

    def assign_human_task(
        self,
        human_task_id: str,
        *,
        principal_id: str,
        operator_id: str,
        assignment_source: str = "manual",
        assigned_by_actor_id: str | None = None,
    ) -> HumanTask | None:
        return self._operator_task_routing.assign_human_task(
            human_task_id,
            principal_id=principal_id,
            operator_id=operator_id,
            assignment_source=assignment_source,
            assigned_by_actor_id=assigned_by_actor_id,
        )

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
        return self._operator_task_routing.return_human_task(
            found,
            principal_id=principal_id,
            operator_id=operator_id,
            resolution=resolution,
            returned_payload_json=returned_payload_json,
            provenance_json=provenance_json,
        )
