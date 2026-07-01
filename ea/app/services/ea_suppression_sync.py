from __future__ import annotations

from app.domain.outreach.recipient_basis import SUPPRESSION_BLOCKING_STATUSES, normalize_token


def suppression_status_blocks_send(status: object) -> bool:
    return normalize_token(status) in SUPPRESSION_BLOCKING_STATUSES
