from __future__ import annotations

from datetime import datetime, timezone
from typing import Callable

from app.domain.models import ExecutionQueueItem, ExecutionSessionSnapshot

RunQueueItemFn = Callable[[str, str | None], None]


class ExecutionQueueRuntimeFacade:
    def __init__(
        self,
        *,
        queue_service,
    ) -> None:
        self._queue_service = queue_service

    def active_queue_step_ids(self, session_id: str) -> set[str]:
        return self._queue_service.active_queue_step_ids(session_id)

    def queue_item_is_eligible_now(self, row: ExecutionQueueItem) -> bool:
        return self._queue_service.queue_item_is_eligible_now(row)

    def next_eligible_queue_item_for_session(self, session_id: str) -> ExecutionQueueItem | None:
        return self._queue_service.next_eligible_queue_item_for_session(session_id)

    def drain_session_inline(
        self,
        session_id: str,
        *,
        stop_before_step_id: str | None = None,
    ):
        return self._queue_service.drain_session_inline(
            session_id,
            stop_before_step_id=stop_before_step_id,
        )

    def ready_steps(
        self,
        session_id: str,
        *,
        stop_before_step_id: str | None = None,
    ):
        return self._queue_service.ready_steps(
            session_id,
            stop_before_step_id=stop_before_step_id,
        )

    def next_ready_step(
        self,
        session_id: str,
        *,
        stop_before_step_id: str | None = None,
    ):
        return self._queue_service.next_ready_step(
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
        return self._queue_service.queue_next_step_after(
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
        return self._queue_service._execute_leased_queue_item(
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
        return self._queue_service.run_queue_item(
            queue_id,
            lease_owner=lease_owner,
            stop_before_step_id=stop_before_step_id,
        )

    def run_next_queue_item(self, *, lease_owner: str = "worker"):
        return self._queue_service.run_next_queue_item(lease_owner=lease_owner)

    def delayed_retry_queue_item(
        self,
        snapshot: ExecutionSessionSnapshot,
    ) -> ExecutionQueueItem | None:
        if str(snapshot.session.status or "") != "queued":
            return None
        now = datetime.now(timezone.utc)
        delayed_items: list[tuple[datetime, ExecutionQueueItem]] = []
        for row in snapshot.queue_items:
            if str(row.state or "") != "queued":
                continue
            raw_next_attempt_at = str(row.next_attempt_at or "").strip()
            if not raw_next_attempt_at:
                continue
            try:
                parsed = datetime.fromisoformat(raw_next_attempt_at)
            except ValueError:
                continue
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            if parsed > now:
                delayed_items.append((parsed, row))
        if not delayed_items:
            return None
        delayed_items.sort(key=lambda item: (item[0], str(item[1].queue_id or "")))
        return delayed_items[0][1]
