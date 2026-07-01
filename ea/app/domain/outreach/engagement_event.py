from __future__ import annotations

from datetime import UTC, datetime
import hashlib
from typing import Any, Iterable, Mapping


CONTRACT_NAME = "ea.sendr_engagement_batch.v1"
ALLOWED_EVENT_TYPES = frozenset(
    {
        "reply_received",
        "page_view",
        "video_view",
        "meeting_booked",
        "unsubscribe",
        "bounce",
        "negative_reply",
    }
)


def _hash(value: object) -> str:
    return hashlib.sha256(str(value or "").encode("utf-8")).hexdigest()


def _preview(value: object, limit: int = 160) -> str:
    text = " ".join(str(value or "").split())
    return text[:limit]


def normalize_engagement_event(event: Mapping[str, object]) -> dict[str, Any]:
    event_type = str(event.get("event_type") or "").strip()
    if event_type not in ALLOWED_EVENT_TYPES:
        raise ValueError(f"unsupported_sendr_engagement_event:{event_type}")
    recipient_hash = str(event.get("recipient_hash") or "").strip() or _hash(event.get("recipient") or event.get("email"))
    row: dict[str, Any] = {
        "event_type": event_type,
        "recipient_hash": recipient_hash,
        "occurred_at": str(event.get("occurred_at") or datetime.now(UTC).isoformat().replace("+00:00", "Z")),
        "raw_body_stored": False,
    }
    if event_type == "reply_received":
        row["preview"] = _preview(event.get("preview") or event.get("body"))
        row["human_review_required"] = True
    if event_type == "page_view":
        row["page_id"] = str(event.get("page_id") or "")
    if event_type == "video_view":
        row["duration_seconds"] = int(event.get("duration_seconds") or 0)
    if event_type in {"unsubscribe", "bounce", "negative_reply"}:
        row["human_review_required"] = True
    return row


def build_engagement_batch_receipt(
    *,
    campaign_id: str,
    events: Iterable[Mapping[str, object]],
    event_batch_id: str | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    normalized_events = [normalize_engagement_event(event) for event in events]
    reply_count = sum(1 for event in normalized_events if event["event_type"] == "reply_received")
    meeting_count = sum(1 for event in normalized_events if event["event_type"] == "meeting_booked")
    suppression_count = sum(
        1 for event in normalized_events if event["event_type"] in {"unsubscribe", "bounce", "negative_reply"}
    )
    batch_id = event_batch_id or _hash(
        f"{campaign_id}:{generated_at or datetime.now(UTC).isoformat()}:{len(normalized_events)}"
    )[:24]
    return {
        "contract_name": CONTRACT_NAME,
        "status": "review_required" if reply_count or meeting_count or suppression_count else "pass",
        "generated_at": generated_at or datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "campaign_id": str(campaign_id or "").strip(),
        "event_batch_id": batch_id,
        "events": normalized_events,
        "ea_actions": {
            "draft_reply_candidates": reply_count,
            "decision_candidates": meeting_count,
            "commitment_candidates": meeting_count,
            "people_memory_candidates": 0,
            "suppression_updates": suppression_count,
        },
    }
