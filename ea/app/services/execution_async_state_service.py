from __future__ import annotations

from typing import Any, Callable

from app.domain.models import ApprovalRequest, ExecutionQueueItem, PolicyDecision


class ExecutionAsyncStateService:
    def __init__(
        self,
        *,
        list_pending_approvals: Callable[[int], list[ApprovalRequest]],
        list_recent_policy_decisions: Callable[[int, str | None], list[PolicyDecision]],
        delayed_retry_queue_item: Callable[[Any], ExecutionQueueItem | None],
        raise_human_task_required: Callable[[Any], None],
        raise_approval_required: Callable[[Any, str], None],
        raise_policy_denied: Callable[[str], None],
        raise_async_execution_queued: Callable[[Any, str], None],
    ) -> None:
        self._list_pending_approvals = list_pending_approvals
        self._list_recent_policy_decisions = list_recent_policy_decisions
        self._delayed_retry_queue_item = delayed_retry_queue_item
        self._raise_human_task_required = raise_human_task_required
        self._raise_approval_required = raise_approval_required
        self._raise_policy_denied = raise_policy_denied
        self._raise_async_execution_queued = raise_async_execution_queued

    def raise_for_snapshot_state(self, snapshot: Any) -> None:
        session = getattr(snapshot, "session", None)
        if session is None:
            return
        status = str(getattr(session, "status", "") or "")
        session_id = str(getattr(session, "session_id", "") or "")
        if status == "awaiting_human":
            self._raise_human_task_required(snapshot)
            return
        if status == "awaiting_approval":
            approval_request = next(
                (row for row in self._list_pending_approvals(100) if row.session_id == session_id),
                None,
            )
            self._raise_approval_required(snapshot, approval_request.approval_id if approval_request is not None else "")
            return
        if status == "blocked":
            decision = next(iter(self._list_recent_policy_decisions(1, session_id)), None)
            reason = str(decision.reason if decision is not None else "") or "policy_denied"
            self._raise_policy_denied(reason)
            return
        delayed_retry = self._delayed_retry_queue_item(snapshot)
        if delayed_retry is not None:
            self._raise_async_execution_queued(snapshot, delayed_retry.next_attempt_at)
