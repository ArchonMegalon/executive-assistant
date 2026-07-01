from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.api.dependencies import require_operator_context
from app.services.ea_outreach_receipts import build_sendr_engagement_receipt


router = APIRouter(prefix="/v1/internal/sendr", tags=["internal-sendr"], dependencies=[Depends(require_operator_context)])


class SendrEngagementBatchIn(BaseModel):
    campaign_id: str = Field(min_length=1, max_length=200)
    event_batch_id: str = Field(default="", max_length=200)
    events: list[dict[str, object]] = Field(default_factory=list)


@router.post("/webhook/dry-run")
def dry_run_sendr_webhook(body: SendrEngagementBatchIn) -> dict[str, object]:
    return build_sendr_engagement_receipt(
        campaign_id=body.campaign_id,
        event_batch_id=body.event_batch_id or None,
        events=body.events,
    )
