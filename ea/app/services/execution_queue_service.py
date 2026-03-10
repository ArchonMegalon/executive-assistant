from __future__ import annotations

from datetime import datetime, timezone
from typing import Callable

from app.domain.models import Artifact, ExecutionQueueItem, ExecutionSession, ExecutionStep

ExecuteStepFn = Callable[[str, ExecutionStep], Artifact | None]
GetStepFn = Callable[[str], ExecutionStep | None]
GetSessionFn = Callable[[str], ExecutionSession | None]
AppendEventFn = Callable[[str, str, dict[str, object] | None], object]
UpdateStepFn = Callable[[str, ...], ExecutionStep | None]
LeaseQueueFn = Callable[[str, ...], ExecutionQueueItem | None]
NextQueueFn = Callable[[str], ExecutionQueueItem | None]
CompleteQueueItemFn = Callable[[str, ...], ExecutionQueueItem | None]
FailQueueItemFn = Callable[[str, ...], ExecutionQueueItem | None]
RetryDeciderFn = Callable[[ExecutionQueueItem, ExecutionStep, Exception], bool]
SetSessionStatusFn = Callable[[str, str], ExecutionSession | None]
QueueForSessionFn = Callable[[str], list[ExecutionQueueItem]]
ContinuePipelineFn = Callable[[str, str, str, str | None], Artifact | None]


class ExecutionQueueService:
    def __init__(
        self,
        *,
        lease_queue_item: LeaseQueueFn,
        lease_next_queue_item: NextQueueFn,
        queue_for_session: QueueForSessionFn,
        get_session: GetSessionFn,
        get_step: GetStepFn,
        update_step: UpdateStepFn,
        append_event: AppendEventFn,
        complete_queue_item: CompleteQueueItemFn,
        fail_queue_item: FailQueueItemFn,
        set_session_status: SetSessionStatusFn,
        execute_step: ExecuteStepFn,
        continue_session_queue: ContinuePipelineFn,
        schedule_retry: RetryDeciderFn,
    ) -> None:
        self._lease_queue_item = lease_queue_item
        self._lease_next_queue_item = lease_next_queue_item
        self._queue_for_session = queue_for_session
        self._get_session = get_session
        self._get_step = get_step
        self._update_step = update_step
        self._append_event = append_event
        self._complete_queue_item = complete_queue_item
        self._fail_queue_item = fail_queue_item
        self._set_session_status = set_session_status
        self._execute_step = execute_step
        self._continue_session_queue = continue_session_queue
        self._schedule_retry = schedule_retry

    def _queue_item_is_eligible_now(self, row: ExecutionQueueItem) -> bool:
        now = datetime.now(timezone.utc)
        state = str(row.state or "")
        if state == "queued":
            if row.next_attempt_at:
                try:
                    if datetime.fromisoformat(row.next_attempt_at) > now:
                        return False
                except ValueError:
                    return False
            return True
        if state == "leased" and row.lease_expires_at:
            try:
                return datetime.fromisoformat(row.lease_expires_at) <= now
            except ValueError:
                return False
        return False

    def _next_eligible_queue_item_for_session(self, session_id: str) -> ExecutionQueueItem | None:
        session = self._get_session(session_id)
        if session is None or str(session.status or "") not in {"queued", "running"}:
            return None
        eligible = sorted(
            (row for row in self._queue_for_session(session_id) if self._queue_item_is_eligible_now(row)),
            key=lambda row: (str(row.created_at or ""), str(row.queue_id or "")),
        )
        return eligible[0] if eligible else None

    def run_queue_item(
        self,
        queue_id: str,
        *,
        lease_owner: str = "inline",
        stop_before_step_id: str | None = None,
    ) -> Artifact | None:
        queue_item = self._lease_queue_item(queue_id, lease_owner=lease_owner)
        if queue_item is None:
            return None
        return self._execute_leased_queue_item(queue_item, stop_before_step_id=stop_before_step_id)

    def run_next_queue_item(self, *, lease_owner: str = "worker") -> Artifact | None:
        queue_item = self._lease_next_queue_item(lease_owner=lease_owner)
        if queue_item is None:
            return None
        return self._execute_leased_queue_item(queue_item)

    def _execute_leased_queue_item(
        self,
        queue_item: ExecutionQueueItem,
        *,
        stop_before_step_id: str | None = None,
    ) -> Artifact | None:
        step = self._get_step(queue_item.step_id)
        if step is None:
            self._fail_queue_item(queue_item.queue_id, last_error="step_not_found")
            raise RuntimeError(f"queued step missing: {queue_item.step_id}")

        self._set_session_status(queue_item.session_id, "running")
        running_step = self._update_step(
            step.step_id,
            state="running",
            error_json={},
            attempt_count=queue_item.attempt_count,
        )
        if running_step is None:
            self._fail_queue_item(queue_item.queue_id, last_error="step_not_found")
            raise RuntimeError(f"unable to mark step running: {queue_item.step_id}")

        self._append_event(
            queue_item.session_id,
            "step_execution_started",
            {
                "queue_id": queue_item.queue_id,
                "step_id": queue_item.step_id,
                "lease_owner": queue_item.lease_owner,
                "attempt_count": queue_item.attempt_count,
            },
        )

        try:
            artifact = self._execute_step(queue_item.session_id, running_step)
        except Exception as exc:
            if self._schedule_retry(queue_item, running_step, exc):
                return None
            self._fail_queue_item(queue_item.queue_id, last_error=str(exc))
            self._update_step(
                queue_item.step_id,
                state="failed",
                error_json={"reason": "execution_failed", "detail": str(exc)},
                attempt_count=queue_item.attempt_count,
            )
            self._set_session_status(queue_item.session_id, "failed")
            self._append_event(
                queue_item.session_id,
                "session_failed",
                {"queue_id": queue_item.queue_id, "step_id": queue_item.step_id, "reason": "execution_failed"},
            )
            raise

        refreshed_step = self._get_step(queue_item.step_id)
        self._complete_queue_item(queue_item.queue_id, state="done")
        self._append_event(
            queue_item.session_id,
            "queue_item_completed",
            {"queue_id": queue_item.queue_id, "step_id": queue_item.step_id},
        )

        if refreshed_step is not None and refreshed_step.state == "waiting_human":
            return None

        next_artifact = self._continue_session_queue(
            queue_item.session_id,
            running_step.step_id,
            lease_owner=queue_item.lease_owner,
            stop_before_step_id=stop_before_step_id,
        )
        if next_artifact is not None:
            return next_artifact
        return artifact
