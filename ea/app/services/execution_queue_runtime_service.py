from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Callable

from app.domain.models import ExecutionQueueItem, ExecutionStep

EnqueueStepFn = Callable[..., ExecutionQueueItem]
RetryQueueItemFn = Callable[[str, str | None, str], ExecutionQueueItem]
UpdateStepFn = Callable[[str, ...], ExecutionStep | None]
SetSessionStatusFn = Callable[[str, str], object]
AppendEventFn = Callable[[str, str, dict[str, object]], object]
IdempotencyKeyFn = Callable[[str, str], str]


class ExecutionQueueRuntimeService:
    @staticmethod
    def default_step_id_to_retry_key(session_id: str, step_id: str) -> str:
        return f"rewrite:{str(session_id or '').strip()}:{str(step_id or '').strip()}"

    def __init__(
        self,
        *,
        enqueue_step: EnqueueStepFn,
        retry_queue_item: RetryQueueItemFn,
        update_step: UpdateStepFn,
        set_session_status: SetSessionStatusFn,
        append_event: AppendEventFn,
        step_id_to_retry_key: IdempotencyKeyFn,
    ) -> None:
        self._enqueue_step = enqueue_step
        self._retry_queue_item = retry_queue_item
        self._update_step = update_step
        self._set_session_status = set_session_status
        self._append_event = append_event
        self._step_id_to_retry_key = step_id_to_retry_key

    def _step_failure_strategy(self, rewrite_step: ExecutionStep) -> str:
        return str((rewrite_step.input_json or {}).get("failure_strategy") or "fail").strip().lower() or "fail"

    def _step_max_attempts(self, rewrite_step: ExecutionStep) -> int:
        try:
            value = int((rewrite_step.input_json or {}).get("max_attempts") or 1)
        except (TypeError, ValueError):
            return 1
        return max(1, value)

    def _step_retry_backoff_seconds(self, rewrite_step: ExecutionStep) -> int:
        try:
            value = int((rewrite_step.input_json or {}).get("retry_backoff_seconds") or 0)
        except (TypeError, ValueError):
            return 0
        return max(0, value)

    def schedule_step_retry(self, queue_item: ExecutionQueueItem, rewrite_step: ExecutionStep, exc: Exception) -> bool:
        if self._step_failure_strategy(rewrite_step) != "retry":
            return False
        max_attempts = self._step_max_attempts(rewrite_step)
        if queue_item.attempt_count >= max_attempts:
            return False
        next_attempt_at = (
            datetime.now(timezone.utc) + timedelta(seconds=self._step_retry_backoff_seconds(rewrite_step))
        ).isoformat()
        self._retry_queue_item(
            queue_item.queue_id,
            last_error=str(exc),
            next_attempt_at=next_attempt_at,
        )
        self._update_step(
            rewrite_step.step_id,
            state="queued",
            error_json={
                "reason": "retry_scheduled",
                "detail": str(exc),
                "next_attempt_at": next_attempt_at,
                "attempt_count": queue_item.attempt_count,
                "max_attempts": max_attempts,
            },
            attempt_count=queue_item.attempt_count,
        )
        self._set_session_status(queue_item.session_id, "queued")
        self._append_event(
            queue_item.session_id,
            "step_retry_scheduled",
            {
                "queue_id": queue_item.queue_id,
                "step_id": queue_item.step_id,
                "attempt_count": queue_item.attempt_count,
                "max_attempts": max_attempts,
                "next_attempt_at": next_attempt_at,
                "reason": str(exc),
            },
        )
        return True

    def enqueue_rewrite_step(self, session_id: str, step_id: str) -> ExecutionQueueItem:
        queue_item = self._enqueue_step(
            session_id,
            step_id,
            idempotency_key=self._step_id_to_retry_key(session_id, step_id),
        )
        self._append_event(
            session_id,
            "step_enqueued",
            {
                "queue_id": queue_item.queue_id,
                "step_id": step_id,
                "state": queue_item.state,
            },
        )
        return queue_item
