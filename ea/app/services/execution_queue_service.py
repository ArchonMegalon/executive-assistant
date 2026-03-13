from __future__ import annotations

from datetime import datetime, timezone
from typing import Callable

from app.domain.models import Artifact, ExecutionQueueItem, ExecutionSession, ExecutionStep

ExecuteStepFn = Callable[[str, ExecutionStep], Artifact | None]
GetStepFn = Callable[[str], ExecutionStep | None]
GetSessionFn = Callable[[str], ExecutionSession | None]
AppendEventFn = Callable[[str, str, dict[str, object] | None], object]
UpdateStepFn = Callable[[str, ...], ExecutionStep | None]
StepsForSessionFn = Callable[[str], list[ExecutionStep]]
LeaseQueueFn = Callable[[str, ...], ExecutionQueueItem | None]
NextQueueFn = Callable[[str], ExecutionQueueItem | None]
CompleteQueueItemFn = Callable[[str, ...], ExecutionQueueItem | None]
FailQueueItemFn = Callable[[str, ...], ExecutionQueueItem | None]
RetryDeciderFn = Callable[[ExecutionQueueItem, ExecutionStep, Exception], bool]
SetSessionStatusFn = Callable[[str, str], ExecutionSession | None]
QueueForSessionFn = Callable[[str], list[ExecutionQueueItem]]
EnqueueStepFn = Callable[[str, str], ExecutionQueueItem]
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
        steps_for: StepsForSessionFn,
        update_step: UpdateStepFn,
        append_event: AppendEventFn,
        complete_queue_item: CompleteQueueItemFn,
        fail_queue_item: FailQueueItemFn,
        complete_session: SetSessionStatusFn,
        set_session_status: SetSessionStatusFn,
        enqueue_step: EnqueueStepFn,
        execute_step: ExecuteStepFn,
        continue_session_queue: ContinuePipelineFn,
        schedule_retry: RetryDeciderFn,
    ) -> None:
        self._lease_queue_item = lease_queue_item
        self._lease_next_queue_item = lease_next_queue_item
        self._queue_for_session = queue_for_session
        self._get_session = get_session
        self._get_step = get_step
        self._steps_for = steps_for
        self._update_step = update_step
        self._append_event = append_event
        self._complete_queue_item = complete_queue_item
        self._fail_queue_item = fail_queue_item
        self._complete_session = complete_session
        self._set_session_status = set_session_status
        self._enqueue_step = enqueue_step
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

    def queue_item_is_eligible_now(self, row: ExecutionQueueItem) -> bool:
        return self._queue_item_is_eligible_now(row)

    def next_eligible_queue_item_for_session(self, session_id: str) -> ExecutionQueueItem | None:
        return self._next_eligible_queue_item_for_session(session_id)

    def _step_dependency_keys(self, row: ExecutionStep) -> tuple[str, ...]:
        raw = (row.input_json or {}).get("depends_on") or ()
        if isinstance(raw, (list, tuple)):
            values = tuple(str(value or "").strip() for value in raw if str(value or "").strip())
            if values:
                return values
        if row.parent_step_id:
            return (f"step-id:{row.parent_step_id}",)
        return ()

    def _dependency_lookup(self, steps: list[ExecutionStep]) -> dict[str, ExecutionStep]:
        lookup: dict[str, ExecutionStep] = {}
        for row in steps:
            step_key = str((row.input_json or {}).get("plan_step_key") or "").strip()
            if step_key:
                lookup[step_key] = row
            lookup[f"step-id:{row.step_id}"] = row
        return lookup

    def active_queue_step_ids(self, session_id: str) -> set[str]:
        return {
            row.step_id
            for row in self._queue_for_session(session_id)
            if str(row.state or "") in {"queued", "leased"}
        }

    def ready_steps(
        self,
        session_id: str,
        *,
        stop_before_step_id: str | None = None,
    ) -> list[ExecutionStep]:
        steps = self._steps_for(session_id)
        if not steps:
            return []
        dependency_lookup = self._dependency_lookup(steps)
        active_queue_step_ids = self.active_queue_step_ids(session_id)
        blocked_step_id = str(stop_before_step_id or "").strip()
        ready_steps: list[ExecutionStep] = []
        for row in steps:
            if row.state != "queued":
                continue
            if blocked_step_id and row.step_id == blocked_step_id:
                continue
            if row.step_id in active_queue_step_ids:
                continue
            dependency_keys = self._step_dependency_keys(row)
            if not dependency_keys:
                ready_steps.append(row)
                continue
            if all(
                (dependency_lookup.get(key) is not None and dependency_lookup[key].state == "completed")
                for key in dependency_keys
            ):
                ready_steps.append(row)
        return ready_steps

    def next_ready_step(
        self,
        session_id: str,
        *,
        stop_before_step_id: str | None = None,
    ) -> ExecutionStep | None:
        ready_steps = self.ready_steps(session_id, stop_before_step_id=stop_before_step_id)
        if not ready_steps:
            return None
        return ready_steps[0]

    def queue_next_step_after(
        self,
        session_id: str,
        step_id: str,
        *,
        lease_owner: str,
        stop_before_step_id: str | None = None,
    ) -> Artifact | None:
        steps = self._steps_for(session_id)
        if not any(row.step_id == step_id for row in steps):
            raise RuntimeError(f"step missing from session order: {step_id}")
        triggering_step = next((row for row in steps if row.step_id == step_id), None)
        session = self._get_session(session_id)
        if session is not None and str(session.status or "") in {"awaiting_approval", "awaiting_human", "blocked"}:
            return None

        artifact: Artifact | None = None
        # Prefer draining already queued work before enqueueing new ready steps.
        should_drain_existing = str(lease_owner or "").strip() == "inline" or (
            triggering_step is not None and str(triggering_step.state or "") not in {"completed", "failed", "blocked", "waiting_human"}
        )
        if should_drain_existing:
            while True:
                existing = self._next_eligible_queue_item_for_session(session_id)
                if existing is None:
                    break
                if stop_before_step_id and existing.step_id == stop_before_step_id:
                    return artifact
                result = self.run_queue_item(
                    existing.queue_id,
                    lease_owner=lease_owner,
                    stop_before_step_id=stop_before_step_id,
                )
                if result is not None:
                    artifact = result
                session = self._get_session(session_id)
                if session is not None and str(session.status or "") in {"awaiting_approval", "awaiting_human", "blocked"}:
                    return artifact

        ready_steps = self.ready_steps(session_id, stop_before_step_id=stop_before_step_id)
        if not ready_steps:
            if steps and all(row.state == "completed" for row in steps):
                session = self._get_session(session_id)
                if session is None or str(session.status or "") != "completed":
                    self._complete_session(session_id, status="completed")
                    self._append_event(session_id, "session_completed", {"status": "completed"})
            return artifact

        queue_items = [self._enqueue_step(session_id, row.step_id) for row in ready_steps]
        if str(lease_owner or "").strip() != "inline":
            return artifact
        for queue_item in queue_items:
            result = self.run_queue_item(
                queue_item.queue_id,
                lease_owner=lease_owner,
                stop_before_step_id=stop_before_step_id,
            )
            if result is not None:
                artifact = result
            session = self._get_session(session_id)
            if session is not None and str(session.status or "") in {"awaiting_approval", "awaiting_human", "blocked"}:
                break
        return artifact

    def drain_session_inline(
        self,
        session_id: str,
        *,
        stop_before_step_id: str | None = None,
    ) -> Artifact | None:
        artifact: Artifact | None = None
        while True:
            queue_item = self.next_eligible_queue_item_for_session(session_id)
            if queue_item is None:
                return artifact
            if stop_before_step_id and queue_item.step_id == stop_before_step_id:
                return artifact
            result = self.run_queue_item(
                queue_item.queue_id,
                lease_owner="inline",
                stop_before_step_id=stop_before_step_id,
            )
            if result is not None:
                artifact = result

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
        blocked_step_id = str(stop_before_step_id or "").strip()
        if blocked_step_id and queue_item.step_id == blocked_step_id:
            self._complete_queue_item(queue_item.queue_id, state="queued")
            self._set_session_status(queue_item.session_id, "queued")
            self._append_event(
                queue_item.session_id,
                "queue_item_deferred",
                {
                    "queue_id": queue_item.queue_id,
                    "step_id": queue_item.step_id,
                    "reason": "stop_before_step_id",
                },
            )
            return None

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
