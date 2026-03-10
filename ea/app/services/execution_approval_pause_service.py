from __future__ import annotations

from typing import Callable

from app.domain.models import ApprovalRequest, ExecutionStep


class ExecutionApprovalPauseService:
    def __init__(
        self,
        *,
        create_request: Callable[..., ApprovalRequest],
        update_step: Callable[[str, ...], ExecutionStep | None],
        set_session_status: Callable[[str, str], object],
        append_event: Callable[[str, str, dict[str, object]], object],
    ) -> None:
        self._create_request = create_request
        self._update_step = update_step
        self._set_session_status = set_session_status
        self._append_event = append_event

    def pause_for_approval(
        self,
        *,
        session_id: str,
        target_step: ExecutionStep,
        reason: str,
        requested_action_json: dict[str, object],
    ) -> ApprovalRequest:
        approval_request = self._create_request(
            session_id,
            target_step.step_id,
            reason=reason,
            requested_action_json=requested_action_json,
        )
        self._update_step(
            target_step.step_id,
            state="waiting_approval",
            output_json=target_step.output_json,
            error_json={"reason": reason, "approval_id": approval_request.approval_id},
        )
        self._set_session_status(session_id, "awaiting_approval")
        self._append_event(
            session_id,
            "session_paused_for_approval",
            {"reason": reason, "approval_id": approval_request.approval_id},
        )
        return approval_request
