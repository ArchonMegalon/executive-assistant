from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.api.dependencies import require_operator_context
from app.domain.outreach.sendr_campaign import build_sendr_campaign_packet
from app.services.ea_outreach_policy import validate_sendr_campaign_packet
from app.services.ea_outreach_receipts import build_sendr_campaign_receipt
from app.services.ltd_provider_governance import build_ltd_provider_governance_receipt


router = APIRouter(prefix="/v1/admin/outreach", tags=["admin-outreach"], dependencies=[Depends(require_operator_context)])


class SendrPacketBuildIn(BaseModel):
    campaign_type: str = Field(default="FOUNDER_DEMO_OUTREACH", max_length=100)
    packet_id: str = Field(min_length=1, max_length=200)
    target_audience: str = Field(default="", max_length=1000)
    expires_at: str = Field(default="", max_length=100)


class SendrPacketValidateIn(BaseModel):
    packet: dict[str, object] = Field(default_factory=dict)
    recipients: list[dict[str, object]] = Field(default_factory=list)


class SendrCampaignReceiptIn(BaseModel):
    packet: dict[str, object] = Field(default_factory=dict)
    recipients: list[dict[str, object]] = Field(default_factory=list)
    dry_run: bool = True


@router.post("/sendr/campaign-packets")
def build_admin_sendr_campaign_packet(body: SendrPacketBuildIn) -> dict[str, object]:
    return build_sendr_campaign_packet(
        campaign_type=body.campaign_type,
        packet_id=body.packet_id,
        target_audience=body.target_audience or None,
        expires_at=body.expires_at or None,
    )


@router.post("/sendr/campaign-packets/validate")
def validate_admin_sendr_campaign_packet(body: SendrPacketValidateIn) -> dict[str, object]:
    return validate_sendr_campaign_packet(body.packet, recipients=body.recipients)


@router.post("/sendr/campaign-receipts")
def build_admin_sendr_campaign_receipt(body: SendrCampaignReceiptIn) -> dict[str, object]:
    return build_sendr_campaign_receipt(body.packet, recipients=body.recipients, dry_run=body.dry_run)


@router.get("/sendr/provider-lane")
def get_admin_sendr_provider_lane() -> dict[str, object]:
    receipt = build_ltd_provider_governance_receipt()
    for lane in receipt.get("lanes", []):
        if str(lane.get("lane_key") or "") == "sendr_ea_growth_outreach":
            return dict(lane)
    return {
        "lane_key": "sendr_ea_growth_outreach",
        "status": "missing",
    }
