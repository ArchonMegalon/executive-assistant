from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from app.domain.outreach.sendr_campaign import build_sendr_campaign_packet
from app.services.ea_outreach_policy import validate_sendr_campaign_packet


def build_and_validate_sendr_campaign_packet(
    *,
    campaign_type: str,
    packet_id: str,
    target_audience: str | None = None,
    expires_at: str | None = None,
    root: Path | None = None,
) -> dict[str, Any]:
    packet = build_sendr_campaign_packet(
        campaign_type=campaign_type,
        packet_id=packet_id,
        target_audience=target_audience,
        expires_at=expires_at,
        root=root,
    )
    packet["validation"] = validate_sendr_campaign_packet(packet)
    return packet


def assert_sendr_packet_reviewable(packet: Mapping[str, object]) -> None:
    validation = validate_sendr_campaign_packet(packet)
    if validation["status"] != "pass":
        codes = ",".join(str(issue.get("code")) for issue in validation["issues"])
        raise ValueError(f"sendr_campaign_packet_blocked:{codes}")
