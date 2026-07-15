from __future__ import annotations

import json
import os

from fastapi import APIRouter, Depends, HTTPException, Request

from app.api.dependencies import get_container
from app.container import AppContainer
from app.domain.models import HumanTask, IntentSpecV3
from app.services.hedy_meeting_review_intake import HedyMeetingReviewIntakeService
from app.services.orchestrator import RewriteOrchestrator


router = APIRouter(tags=["hedy-meeting-review-intake"])

_DEFAULT_MAX_BODY_BYTES = 1_048_576
_DEFAULT_SIGNATURE_TOLERANCE_SECONDS = 300


class _HedyReviewQueueAdapter:
    """Bind the narrow Hedy review queue contract to the runtime orchestrator."""

    def __init__(self, orchestrator: RewriteOrchestrator) -> None:
        self._orchestrator = orchestrator

    def find_human_task_by_dedupe(
        self,
        dedupe_key: str,
        *,
        principal_id: str,
    ) -> HumanTask | None:
        for task in self._orchestrator.list_human_tasks(
            principal_id=principal_id,
            limit=1_000,
        ):
            if (
                str((task.input_json or {}).get("hedy_idempotency_key") or "")
                == dedupe_key
            ):
                return task
        return None

    def create_human_task(
        self,
        *,
        principal_id: str,
        task_type: str,
        priority: str,
        authority_required: str,
        input_json: dict[str, object],
        dedupe_key: str,
    ) -> HumanTask:
        session = self._orchestrator.start_session(
            IntentSpecV3(
                principal_id=principal_id,
                goal="Review signed Hedy meeting evidence before any write or send.",
                task_type="hedy_meeting_review",
                deliverable_type="memo",
                risk_class="medium",
                approval_class="draft",
                budget_class="standard",
            )
        )
        return self._orchestrator.create_human_task(
            session_id=session.session_id,
            principal_id=principal_id,
            task_type=task_type,
            role_required="operator",
            brief="Review Hedy meeting evidence candidates before any write or send.",
            authority_required=authority_required,
            why_human="Hedy meeting evidence is review-only until a principal or operator approves it.",
            input_json=input_json,
            priority=priority,
        )


def _env_enabled(name: str) -> bool:
    return str(os.environ.get(name) or "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _positive_int(name: str, *, default: int, maximum: int) -> int:
    try:
        value = int(str(os.environ.get(name) or default).strip())
    except ValueError:
        value = default
    return min(max(value, 1), maximum)


def _hedy_webhooks_enabled() -> bool:
    return _env_enabled("EA_HEDY_MEETING_EVIDENCE_ENABLED") and _env_enabled(
        "EA_HEDY_WEBHOOKS_ENABLED"
    )


def _content_length(request: Request) -> int | None:
    raw = str(request.headers.get("content-length") or "").strip()
    if not raw:
        return None
    try:
        value = int(raw)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail="hedy_content_length_invalid",
        ) from None
    if value < 0:
        raise HTTPException(status_code=400, detail="hedy_content_length_invalid")
    return value


@router.post("/v1/integrations/hedy/webhook")
async def ingest_hedy_meeting_review_webhook(
    request: Request,
    container: AppContainer = Depends(get_container),
) -> dict[str, object]:
    if not _hedy_webhooks_enabled():
        raise HTTPException(status_code=503, detail="hedy_webhook_disabled")

    max_body_bytes = _positive_int(
        "EA_HEDY_WEBHOOK_MAX_BODY_BYTES",
        default=_DEFAULT_MAX_BODY_BYTES,
        maximum=8 * _DEFAULT_MAX_BODY_BYTES,
    )
    declared_length = _content_length(request)
    if declared_length is not None and declared_length > max_body_bytes:
        raise HTTPException(status_code=413, detail="hedy_payload_too_large")

    body_buffer = bytearray()
    async for chunk in request.stream():
        if len(body_buffer) + len(chunk) > max_body_bytes:
            raise HTTPException(status_code=413, detail="hedy_payload_too_large")
        body_buffer.extend(chunk)
    body = bytes(body_buffer)
    if not body:
        raise HTTPException(status_code=400, detail="hedy_payload_required")
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise HTTPException(status_code=400, detail="hedy_payload_invalid") from None
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="hedy_payload_object_required")

    principal_id = str(
        payload.get("principal_id")
        or os.environ.get("EA_HEDY_DEFAULT_PRINCIPAL_ID")
        or ""
    ).strip()
    if not principal_id:
        raise HTTPException(status_code=422, detail="hedy_principal_required")
    workspace_id = str(payload.get("workspace_id") or "").strip()

    service = HedyMeetingReviewIntakeService(
        orchestrator=_HedyReviewQueueAdapter(container.orchestrator),
        webhook_secret=str(os.environ.get("HEDY_WEBHOOK_SECRET") or "").strip(),
        tolerance_seconds=_positive_int(
            "EA_HEDY_WEBHOOK_TOLERANCE_SECONDS",
            default=_DEFAULT_SIGNATURE_TOLERANCE_SECONDS,
            maximum=86_400,
        ),
    )
    try:
        result = service.ingest_webhook_to_review_queue(
            body=body,
            headers=dict(request.headers),
            principal_id=principal_id,
            workspace_id=workspace_id,
        )
    except PermissionError as exc:
        detail = str(exc or "webhook_signature_mismatch").strip()
        raise HTTPException(status_code=401, detail=detail) from None
    return result.as_dict()


__all__ = ["router"]
