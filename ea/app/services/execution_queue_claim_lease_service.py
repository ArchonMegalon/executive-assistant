from __future__ import annotations

from typing import Any

from app.domain.models import ExecutionQueueItem
from app.services.execution_queue_runtime_facade import ExecutionQueueRuntimeFacade
from app.services.execution_queue_runtime_service import ExecutionQueueRuntimeService


class MissingReadyStepError(RuntimeError):
    def __init__(self, message: str, *, session_id: str) -> None:
        super().__init__(message)
        self.session_id = session_id


class ExecutionQueueClaimLeaseService:
    def __init__(
        self,
        runtime: ExecutionQueueRuntimeFacade,
        queue_runtime: ExecutionQueueRuntimeService,
    ) -> None:
        self._runtime = runtime
        self._queue_runtime = queue_runtime

    def delayed_retry_queue_item(self, snapshot: Any) -> ExecutionQueueItem | None:
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

    def execute_next_ready_step(
        self,
        session_id: str,
        *,
        lease_owner: str = "inline",
        missing_step_error: str,
        stop_before_step_id: str | None = None,
    ):
        existing = self.next_eligible_queue_item_for_session(session_id)
        if existing is not None:
            artifact = self.run_queue_item(
                existing.queue_id,
                lease_owner=lease_owner,
                stop_before_step_id=stop_before_step_id,
            )
            drained_artifact = self.drain_session_inline(session_id, stop_before_step_id=stop_before_step_id)
            if drained_artifact is not None:
                return drained_artifact
            return artifact
        next_step = self.next_ready_step(session_id, stop_before_step_id=stop_before_step_id)
        if next_step is None:
            raise MissingReadyStepError(missing_step_error, session_id=session_id)
        queue_item = self._queue_runtime.enqueue_rewrite_step(session_id, next_step.step_id)
        artifact = self.run_queue_item(
            queue_item.queue_id,
            lease_owner=lease_owner,
            stop_before_step_id=stop_before_step_id,
        )
        drained_artifact = self.drain_session_inline(session_id, stop_before_step_id=stop_before_step_id)
        if drained_artifact is not None:
            return drained_artifact
        return artifact
