from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import json
from typing import Any, Iterable, Mapping

from app.domain.outreach.engagement_event import build_engagement_batch_receipt
from app.domain.outreach.recipient_basis import normalize_token, validate_recipient_basis
from app.services.ea_outreach_policy import validate_sendr_campaign_packet


def sha256_json(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _now(generated_at: str | None = None) -> str:
    return generated_at or datetime.now(UTC).isoformat().replace("+00:00", "Z")


def build_sendr_campaign_receipt(
    packet: Mapping[str, Any],
    *,
    recipients: Iterable[Mapping[str, object]] = (),
    dry_run: bool = True,
    generated_at: str | None = None,
) -> dict[str, Any]:
    recipient_rows = list(recipients)
    validation = validate_sendr_campaign_packet(packet, recipients=recipient_rows)
    blocked_recipient_count = sum(1 for row in recipient_rows if validate_recipient_basis(row))
    recipient_bases = sorted({normalize_token(row.get("recipient_basis")) for row in recipient_rows if row.get("recipient_basis")})
    status = "blocked" if validation["status"] != "pass" else "setup_review_required"
    if not dry_run and validation["status"] == "pass" and bool(packet.get("human_approved_limited_send")):
        status = "pilot_approved"
    return {
        "contract_name": "ea.sendr_campaign_receipt.v1",
        "status": status,
        "generated_at": _now(generated_at),
        "provider": "sendr",
        "license_tier": str(packet.get("license_tier") or "AppSumo Tier 4"),
        "packet_id": str(packet.get("packet_id") or ""),
        "campaign_type": str(packet.get("campaign_type") or ""),
        "source_packet_sha256": sha256_json(packet),
        "approved_claims_sha256": sha256_json(packet.get("allowed_claims") or []),
        "message_copy_sha256": sha256_json(packet.get("message_copy") or ""),
        "personalized_page_template_sha256": sha256_json(packet.get("personalized_page_copy") or ""),
        "video_script_sha256": sha256_json(packet.get("video_script") or ""),
        "recipient_policy": {
            "recipient_count": len(recipient_rows),
            "recipient_basis": recipient_bases,
            "blocked_recipient_count": blocked_recipient_count,
            "suppression_checked": bool(recipient_rows)
            and all(str(row.get("suppression_status") or "").strip() for row in recipient_rows),
        },
        "channels": dict(packet.get("channels") or {}),
        "sendr": {
            "campaign_id": "",
            "sequence_id": "",
            "page_template_id": "",
            "dynamic_video_id": "",
        },
        "validation": validation["validation"],
        "validation_status": validation["status"],
        "validation_issues": validation["issues"],
        "human_review": {
            "reviewer": "operator" if bool(packet.get("human_approved_limited_send")) else "",
            "reviewed_at": str(packet.get("human_reviewed_at") or ""),
            "approval_scope": str(packet.get("approval_scope") or "required_before_limited_send"),
        },
        "direct_send_allowed": False,
        "limited_send_allowed": status == "pilot_approved",
        "max_contacts": int(packet.get("max_contacts") or 50),
        "auto_reply_allowed": False,
        "dry_run": dry_run,
    }


def build_sendr_engagement_receipt(
    *,
    campaign_id: str,
    events: Iterable[Mapping[str, object]],
    event_batch_id: str | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    return build_engagement_batch_receipt(
        campaign_id=campaign_id,
        events=events,
        event_batch_id=event_batch_id,
        generated_at=generated_at,
    )
