from __future__ import annotations

import uuid
from dataclasses import replace
from datetime import datetime, timezone
from typing import Dict, List, Protocol

from app.domain.models import DeliveryOutboxItem, now_utc_iso


def _due(next_attempt_at: str | None) -> bool:
    raw = str(next_attempt_at or "").strip()
    if not raw:
        return True
    try:
        value = datetime.fromisoformat(raw)
    except ValueError:
        return True
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value <= datetime.now(timezone.utc)


class DeliveryOutboxRepository(Protocol):
    def enqueue(
        self,
        channel: str,
        recipient: str,
        content: str,
        metadata: dict[str, object] | None = None,
        *,
        principal_id: str = "",
        idempotency_key: str = "",
    ) -> DeliveryOutboxItem:
        ...

    def mark_sent(
        self,
        delivery_id: str,
        *,
        principal_id: str = "",
        receipt_json: dict[str, object] | None = None,
    ) -> DeliveryOutboxItem | None:
        ...

    def mark_failed(
        self,
        delivery_id: str,
        *,
        principal_id: str = "",
        error: str,
        next_attempt_at: str | None = None,
        dead_letter: bool = False,
    ) -> DeliveryOutboxItem | None:
        ...

    def list_pending(self, limit: int = 50, *, principal_id: str | None = None) -> list[DeliveryOutboxItem]:
        ...


class InMemoryDeliveryOutboxRepository:
    def __init__(self) -> None:
        self._rows: Dict[str, DeliveryOutboxItem] = {}
        self._order: List[str] = []
        self._idempotency_to_id: Dict[tuple[str, str], str] = {}

    def enqueue(
        self,
        channel: str,
        recipient: str,
        content: str,
        metadata: dict[str, object] | None = None,
        *,
        principal_id: str = "",
        idempotency_key: str = "",
    ) -> DeliveryOutboxItem:
        principal = str(principal_id or "").strip()
        idem = str(idempotency_key or "").strip()
        if idem:
            found_id = self._idempotency_to_id.get((principal, idem))
            if found_id and found_id in self._rows:
                return self._rows[found_id]
        row = DeliveryOutboxItem(
            delivery_id=str(uuid.uuid4()),
            principal_id=principal,
            channel=str(channel or "unknown").strip(),
            recipient=str(recipient or "").strip(),
            content=str(content or ""),
            status="queued",
            metadata=dict(metadata or {}),
            created_at=now_utc_iso(),
            sent_at=None,
            idempotency_key=idem,
            attempt_count=0,
            next_attempt_at=None,
            last_error="",
            receipt_json={},
            dead_lettered_at=None,
        )
        self._rows[row.delivery_id] = row
        self._order.append(row.delivery_id)
        if idem:
            self._idempotency_to_id[(principal, idem)] = row.delivery_id
        return row

    def mark_sent(
        self,
        delivery_id: str,
        *,
        principal_id: str = "",
        receipt_json: dict[str, object] | None = None,
    ) -> DeliveryOutboxItem | None:
        found = self._rows.get(str(delivery_id or ""))
        if not found:
            return None
        if found.principal_id != str(principal_id or "").strip():
            return None
        updated = replace(
            found,
            status="sent",
            sent_at=now_utc_iso(),
            receipt_json=dict(receipt_json or found.receipt_json),
            last_error="",
            next_attempt_at=None,
            dead_lettered_at=None,
        )
        self._rows[updated.delivery_id] = updated
        return updated

    def mark_failed(
        self,
        delivery_id: str,
        *,
        principal_id: str = "",
        error: str,
        next_attempt_at: str | None = None,
        dead_letter: bool = False,
    ) -> DeliveryOutboxItem | None:
        found = self._rows.get(str(delivery_id or ""))
        if not found:
            return None
        if found.principal_id != str(principal_id or "").strip():
            return None
        status = "dead_lettered" if dead_letter else "retry"
        updated = replace(
            found,
            status=status,
            attempt_count=max(0, int(found.attempt_count)) + 1,
            last_error=str(error or ""),
            next_attempt_at=None if dead_letter else str(next_attempt_at or ""),
            dead_lettered_at=now_utc_iso() if dead_letter else None,
        )
        self._rows[updated.delivery_id] = updated
        return updated

    def list_pending(self, limit: int = 50, *, principal_id: str | None = None) -> list[DeliveryOutboxItem]:
        n = max(1, min(500, int(limit or 50)))
        normalized_principal = str(principal_id or "").strip()
        pending_ids = [
            i
            for i in self._order
            if self._rows.get(i)
            and (not normalized_principal or self._rows[i].principal_id == normalized_principal)
            and self._rows[i].status in {"queued", "retry"}
            and _due(self._rows[i].next_attempt_at)
        ]
        ids = list(reversed(pending_ids[-n:]))
        return [self._rows[i] for i in ids if i in self._rows]
