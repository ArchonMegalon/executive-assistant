from __future__ import annotations

from typing import Any, Callable

from app.domain.models import ApprovalDecision, ApprovalRequest, ExecutionQueueItem


class ExecutionApprovalResumeService:
    def __init__(
        self,
        *,
        decide_approval: Callable[
            [str, str, str, str],
            tuple[ApprovalRequest, ApprovalDecision] | None,
        ],
        append_event: Callable[[str, str, dict[str, object]], object],
        update_step: Callable[[str, ...], object],
        set_session_status: Callable[[str, str], object],
        execute_next_ready_step: Callable[[str], object],
        fetch_session: Callable[[str], Any | None],
        delayed_retry_queue_item: Callable[[Any], ExecutionQueueItem | None],
    ) -> None:
        self._decide_approval = decide_approval
        self._append_event = append_event
        self._update_step = update_step
        self._set_session_status = set_session_status
        self._execute_next_ready_step = execute_next_ready_step
        self._fetch_session = fetch_session
        self._delayed_retry_queue_item = delayed_retry_queue_item

    @staticmethod
    def _has_pending_queue_work(snapshot: Any) -> bool:
        queue_items = list(getattr(snapshot, "queue_items", []) or [])
        for row in queue_items:
            state = str(getattr(row, "state", "") or "").strip().lower()
            if state in {"queued", "leased", "running", "retry_scheduled"}:
                return True
        return False

    def decide_approval(
        self,
        approval_id: str,
        *,
        decision: str,
        decided_by: str,
        reason: str,
    ) -> tuple[ApprovalRequest, ApprovalDecision] | None:
        found = self._decide_approval(
            approval_id,
            decision=decision,
            decided_by=decided_by,
            reason=reason,
        )
        if not found:
            return None
        request, decision_row = found
        self._append_event(
            request.session_id,
            "approval_decided",
            {
                "approval_id": request.approval_id,
                "step_id": request.step_id,
                "decision": decision_row.decision,
                "decided_by": decision_row.decided_by,
                "reason": decision_row.reason,
            },
        )
        if decision_row.decision == "approved":
            updated_step = self._update_step(
                request.step_id,
                state="queued",
                output_json={"approval_id": request.approval_id, "decision": "approved"},
                error_json={},
            )
            self._set_session_status(request.session_id, "running")
            self._append_event(
                request.session_id,
                "session_resumed_from_approval",
                {"approval_id": request.approval_id, "step_id": request.step_id},
            )
            if updated_step is not None:
                self._execute_next_ready_step(request.session_id)
                snapshot = self._fetch_session(request.session_id)
                if snapshot is None:
                    return request, decision_row
                if snapshot.session.status in {"awaiting_human", "awaiting_approval", "completed"}:
                    return request, decision_row
                if self._delayed_retry_queue_item(snapshot) is not None:
                    return request, decision_row
                if self._has_pending_queue_work(snapshot):
                    return request, decision_row
                raise RuntimeError(f"approved queue item did not execute: {request.session_id}")
        else:
            self._update_step(
                request.step_id,
                state="blocked",
                error_json={"approval_id": request.approval_id, "decision": decision_row.decision},
            )
            self._set_session_status(request.session_id, "blocked")
            self._append_event(
                request.session_id,
                "session_blocked",
                {"reason": f"approval_{decision_row.decision}", "approval_id": request.approval_id},
            )
        return request, decision_row
