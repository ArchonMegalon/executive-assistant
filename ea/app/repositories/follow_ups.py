from __future__ import annotations

import uuid
from typing import Dict, List, Protocol

from app.domain.models import FollowUp, now_utc_iso


class FollowUpRepository(Protocol):
    def upsert_follow_up(
        self,
        *,
        principal_id: str,
        stakeholder_ref: str,
        topic: str,
        status: str = "open",
        due_at: str | None = None,
        channel_hint: str = "",
        notes: str = "",
        source_json: dict[str, object] | None = None,
        follow_up_id: str | None = None,
    ) -> FollowUp:
        ...

    def get(self, follow_up_id: str) -> FollowUp | None:
        ...

    def list_follow_ups(
        self,
        *,
        principal_id: str,
        limit: int = 100,
        status: str | None = None,
    ) -> list[FollowUp]:
        ...



def _normalize_status(value: str) -> str:
    raw = str(value or "").strip().lower()
    if raw in {"open", "completed", "cancelled", "waiting_on_external", "scheduled"}:
        return raw
    return "open"


class InMemoryFollowUpRepository:
    def __init__(self) -> None:
        self._rows: Dict[str, FollowUp] = {}
        self._order: List[str] = []

    def upsert_follow_up(
        self,
        *,
        principal_id: str,
        stakeholder_ref: str,
        topic: str,
        status: str = "open",
        due_at: str | None = None,
        channel_hint: str = "",
        notes: str = "",
        source_json: dict[str, object] | None = None,
        follow_up_id: str | None = None,
    ) -> FollowUp:
        now = now_utc_iso()
        key = str(follow_up_id or "").strip()
        existing = self._rows.get(key) if key else None
        if existing and existing.principal_id != str(principal_id or "").strip():
            existing = None
        if existing:
            updated = FollowUp(
                follow_up_id=existing.follow_up_id,
                principal_id=existing.principal_id,
                stakeholder_ref=str(stakeholder_ref or existing.stakeholder_ref).strip() or existing.stakeholder_ref,
                topic=str(topic or existing.topic).strip() or existing.topic,
                status=_normalize_status(status),
                due_at=str(due_at or "").strip() or None,
                channel_hint=str(channel_hint or existing.channel_hint).strip(),
                notes=str(notes or "").strip(),
                source_json=dict(source_json or {}),
                created_at=existing.created_at,
                updated_at=now,
            )
            self._rows[existing.follow_up_id] = updated
            return updated
        row = FollowUp(
            follow_up_id=key or str(uuid.uuid4()),
            principal_id=str(principal_id or "").strip(),
            stakeholder_ref=str(stakeholder_ref or "").strip(),
            topic=str(topic or "").strip(),
            status=_normalize_status(status),
            due_at=str(due_at or "").strip() or None,
            channel_hint=str(channel_hint or "").strip(),
            notes=str(notes or "").strip(),
            source_json=dict(source_json or {}),
            created_at=now,
            updated_at=now,
        )
        self._rows[row.follow_up_id] = row
        self._order.append(row.follow_up_id)
        return row

    def get(self, follow_up_id: str) -> FollowUp | None:
        return self._rows.get(str(follow_up_id or ""))

    def list_follow_ups(
        self,
        *,
        principal_id: str,
        limit: int = 100,
        status: str | None = None,
    ) -> list[FollowUp]:
        n = max(1, min(500, int(limit or 100)))
        principal = str(principal_id or "").strip()
        status_filter = str(status or "").strip().lower()
        rows = [self._rows[fid] for fid in reversed(self._order) if fid in self._rows]
        rows = [row for row in rows if row.principal_id == principal]
        if status_filter:
            rows = [row for row in rows if row.status == status_filter]
        return rows[:n]
