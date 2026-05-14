from __future__ import annotations

from dataclasses import dataclass, asdict
import hashlib
import os
from typing import Any


@dataclass(frozen=True)
class ProductSignalReceipt:
    signal_id: str
    source: str
    source_route: str
    signal_type: str
    public_title: str
    public_summary: str
    status: str
    votes: int
    follows: int
    privacy_status: str
    source_receipts: tuple[str, ...]
    created_at_utc: str


@dataclass(frozen=True)
class ProductLiftProjectionReceipt:
    projection_receipt_id: str
    signal_id: str
    backend: str
    project_key: str
    action: str
    dry_run: bool
    payload_hash: str
    public_safe: bool
    created_at_utc: str


def build_product_signal_bridge_dry_run() -> dict[str, Any]:
    signal = ProductSignalReceipt(
        signal_id="signal_feedback_preview_001",
        source="chummer_public",
        source_route="/feedback",
        signal_type="feedback",
        public_title="Public feedback should stay separate from private support",
        public_summary="Votes show demand while first-party proof still decides what ships.",
        status="triaged",
        votes=7,
        follows=2,
        privacy_status="public_safe",
        source_receipts=("feedback_receipt_preview_001",),
        created_at_utc="2026-05-14T00:00:00Z",
    )
    payload = {
        "title": signal.public_title,
        "summary": signal.public_summary,
        "status": signal.status,
        "votes": signal.votes,
        "follows": signal.follows,
    }
    projection = ProductLiftProjectionReceipt(
        projection_receipt_id="projection_receipt_preview_001",
        signal_id=signal.signal_id,
        backend=str(os.environ.get("EA_PRODUCTLIFT_SIGNAL_BACKEND") or "productlift"),
        project_key=str(os.environ.get("EA_PRODUCTLIFT_PROJECT_DEFAULT") or "chummer6_public_preview"),
        action="mirror_signal",
        dry_run=True,
        payload_hash=hashlib.sha256(repr(sorted(payload.items())).encode("utf-8")).hexdigest(),
        public_safe=True,
        created_at_utc="2026-05-14T00:00:00Z",
    )
    return {
        "signal_receipt": asdict(signal),
        "projection_receipt": asdict(projection),
        "provider_name_publicly_exposed": False,
        "private_data_included": False,
    }
