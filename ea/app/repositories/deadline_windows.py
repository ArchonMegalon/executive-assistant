from __future__ import annotations

import uuid
from typing import Dict, List, Protocol

from app.domain.models import DeadlineWindow, now_utc_iso


class DeadlineWindowRepository(Protocol):
    def upsert_deadline_window(
        self,
        *,
        principal_id: str,
        title: str,
        start_at: str | None = None,
        end_at: str | None = None,
        status: str = "open",
        priority: str = "medium",
        notes: str = "",
        source_json: dict[str, object] | None = None,
        window_id: str | None = None,
    ) -> DeadlineWindow:
        ...

    def get(self, window_id: str) -> DeadlineWindow | None:
        ...

    def list_deadline_windows(
        self,
        *,
        principal_id: str | None = None,
        limit: int = 100,
        status: str | None = None,
    ) -> list[DeadlineWindow]:
        ...


def _normalize_status(value: str) -> str:
    raw = str(value or "").strip().lower()
    if raw in {"open", "monitoring", "elapsed", "cancelled"}:
        return raw
    return "open"


class InMemoryDeadlineWindowRepository:
    def __init__(self) -> None:
        self._rows: Dict[str, DeadlineWindow] = {}
        self._order: List[str] = []

    def upsert_deadline_window(
        self,
        *,
        principal_id: str,
        title: str,
        start_at: str | None = None,
        end_at: str | None = None,
        status: str = "open",
        priority: str = "medium",
        notes: str = "",
        source_json: dict[str, object] | None = None,
        window_id: str | None = None,
    ) -> DeadlineWindow:
        now = now_utc_iso()
        key = str(window_id or "").strip()
        existing = self._rows.get(key) if key else None
        if existing and existing.principal_id != str(principal_id or "").strip():
            existing = None
        if existing:
            updated = DeadlineWindow(
                window_id=existing.window_id,
                principal_id=existing.principal_id,
                title=str(title or existing.title).strip() or existing.title,
                start_at=str(start_at or "").strip() or None,
                end_at=str(end_at or "").strip() or None,
                status=_normalize_status(status),
                priority=str(priority or existing.priority).strip() or existing.priority,
                notes=str(notes or "").strip(),
                source_json=dict(source_json or {}),
                created_at=existing.created_at,
                updated_at=now,
            )
            self._rows[existing.window_id] = updated
            return updated
        row = DeadlineWindow(
            window_id=key or str(uuid.uuid4()),
            principal_id=str(principal_id or "").strip(),
            title=str(title or "").strip(),
            start_at=str(start_at or "").strip() or None,
            end_at=str(end_at or "").strip() or None,
            status=_normalize_status(status),
            priority=str(priority or "medium").strip() or "medium",
            notes=str(notes or "").strip(),
            source_json=dict(source_json or {}),
            created_at=now,
            updated_at=now,
        )
        self._rows[row.window_id] = row
        self._order.append(row.window_id)
        return row

    def get(self, window_id: str) -> DeadlineWindow | None:
        return self._rows.get(str(window_id or ""))

    def list_deadline_windows(
        self,
        *,
        principal_id: str | None = None,
        limit: int = 100,
        status: str | None = None,
    ) -> list[DeadlineWindow]:
        n = max(1, min(500, int(limit or 100)))
        principal = str(principal_id or "").strip()
        status_filter = str(status or "").strip().lower()
        rows = [self._rows[wid] for wid in reversed(self._order) if wid in self._rows]
        if principal:
            rows = [row for row in rows if row.principal_id == principal]
        if status_filter:
            rows = [row for row in rows if row.status == status_filter]
        return rows[:n]
