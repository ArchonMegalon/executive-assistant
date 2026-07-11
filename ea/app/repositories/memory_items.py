from __future__ import annotations

import uuid
from dataclasses import replace
from typing import Dict, List, Protocol

from app.domain.models import MemoryItem, now_utc_iso


class MemoryItemRepository(Protocol):
    @property
    def snapshot_storage_durable(self) -> bool:
        ...

    def create_item(
        self,
        *,
        principal_id: str,
        category: str,
        summary: str,
        fact_json: dict[str, object] | None = None,
        provenance_json: dict[str, object] | None = None,
        confidence: float = 0.5,
        sensitivity: str = "internal",
        sharing_policy: str = "private",
        reviewer: str = "",
        last_verified_at: str | None = None,
    ) -> MemoryItem:
        ...

    def get(self, item_id: str) -> MemoryItem | None:
        ...

    def list_items(
        self,
        *,
        limit: int = 100,
        principal_id: str | None = None,
    ) -> list[MemoryItem]:
        ...

    def export_principal_snapshot(
        self,
        *,
        principal_id: str,
        max_items: int,
    ) -> list[MemoryItem]:
        ...


class MemoryItemSnapshotLimitExceeded(RuntimeError):
    """Raised when an exact snapshot would exceed its caller-defined bound."""

    def __init__(self, *, principal_id: str, max_items: int) -> None:
        self.principal_id = principal_id
        self.max_items = max_items
        super().__init__("memory_item_snapshot_limit_exceeded")


def validate_memory_item_snapshot_request(
    *,
    principal_id: str,
    max_items: int,
) -> tuple[str, int]:
    principal = str(principal_id or "").strip()
    if not principal:
        raise ValueError("principal_id is required for memory-item snapshot export")
    if isinstance(max_items, bool):
        raise ValueError("max_items must be a positive integer")
    try:
        item_limit = int(max_items)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("max_items must be a positive integer") from exc
    if item_limit < 1:
        raise ValueError("max_items must be a positive integer")
    return principal, item_limit


def _clamp_confidence(value: float) -> float:
    try:
        numeric = float(value)
    except Exception:
        numeric = 0.5
    if numeric < 0.0:
        return 0.0
    if numeric > 1.0:
        return 1.0
    return numeric


class InMemoryMemoryItemRepository:
    def __init__(self) -> None:
        self._rows: Dict[str, MemoryItem] = {}
        self._order: List[str] = []

    @property
    def snapshot_storage_durable(self) -> bool:
        return False

    def create_item(
        self,
        *,
        principal_id: str,
        category: str,
        summary: str,
        fact_json: dict[str, object] | None = None,
        provenance_json: dict[str, object] | None = None,
        confidence: float = 0.5,
        sensitivity: str = "internal",
        sharing_policy: str = "private",
        reviewer: str = "",
        last_verified_at: str | None = None,
    ) -> MemoryItem:
        ts = now_utc_iso()
        row = MemoryItem(
            item_id=str(uuid.uuid4()),
            principal_id=str(principal_id or "").strip(),
            category=str(category or "fact").strip() or "fact",
            summary=str(summary or "").strip(),
            fact_json=dict(fact_json or {}),
            provenance_json=dict(provenance_json or {}),
            confidence=_clamp_confidence(confidence),
            sensitivity=str(sensitivity or "internal").strip() or "internal",
            sharing_policy=str(sharing_policy or "private").strip() or "private",
            last_verified_at=str(last_verified_at or ts),
            reviewer=str(reviewer or "").strip(),
            created_at=ts,
            updated_at=ts,
        )
        self._rows[row.item_id] = row
        self._order.append(row.item_id)
        return row

    def get(self, item_id: str) -> MemoryItem | None:
        return self._rows.get(str(item_id or ""))

    def list_items(
        self,
        *,
        limit: int = 100,
        principal_id: str | None = None,
    ) -> list[MemoryItem]:
        n = max(1, min(500, int(limit or 100)))
        principal_filter = str(principal_id or "").strip()
        rows = [self._rows[item_id] for item_id in reversed(self._order) if item_id in self._rows]
        if principal_filter:
            rows = [row for row in rows if row.principal_id == principal_filter]
        return rows[:n]

    def export_principal_snapshot(
        self,
        *,
        principal_id: str,
        max_items: int,
    ) -> list[MemoryItem]:
        principal, item_limit = validate_memory_item_snapshot_request(
            principal_id=principal_id,
            max_items=max_items,
        )
        rows = sorted(
            (row for row in self._rows.values() if row.principal_id == principal),
            key=lambda row: (row.created_at, row.item_id),
        )[: item_limit + 1]
        if len(rows) > item_limit:
            raise MemoryItemSnapshotLimitExceeded(
                principal_id=principal,
                max_items=item_limit,
            )
        return rows

    def touch_last_verified(self, item_id: str, when_iso: str | None = None) -> MemoryItem | None:
        key = str(item_id or "")
        row = self._rows.get(key)
        if not row:
            return None
        ts = str(when_iso or now_utc_iso())
        updated = replace(row, last_verified_at=ts, updated_at=ts)
        self._rows[key] = updated
        return updated
