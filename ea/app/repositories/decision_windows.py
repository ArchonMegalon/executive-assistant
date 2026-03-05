from __future__ import annotations

import uuid
from typing import Dict, List, Protocol

from app.domain.models import DecisionWindow, now_utc_iso


class DecisionWindowRepository(Protocol):
    def upsert_decision_window(
        self,
        *,
        principal_id: str,
        title: str,
        context: str = "",
        opens_at: str | None = None,
        closes_at: str | None = None,
        urgency: str = "medium",
        authority_required: str = "manager",
        status: str = "open",
        notes: str = "",
        source_json: dict[str, object] | None = None,
        decision_window_id: str | None = None,
    ) -> DecisionWindow:
        ...

    def get(self, decision_window_id: str) -> DecisionWindow | None:
        ...

    def list_decision_windows(
        self,
        *,
        principal_id: str,
        limit: int = 100,
        status: str | None = None,
    ) -> list[DecisionWindow]:
        ...


def _normalize_status(value: str) -> str:
    raw = str(value or "").strip().lower()
    if raw in {"open", "decided", "expired", "cancelled"}:
        return raw
    return "open"


class InMemoryDecisionWindowRepository:
    def __init__(self) -> None:
        self._rows: Dict[str, DecisionWindow] = {}
        self._order: List[str] = []

    def upsert_decision_window(
        self,
        *,
        principal_id: str,
        title: str,
        context: str = "",
        opens_at: str | None = None,
        closes_at: str | None = None,
        urgency: str = "medium",
        authority_required: str = "manager",
        status: str = "open",
        notes: str = "",
        source_json: dict[str, object] | None = None,
        decision_window_id: str | None = None,
    ) -> DecisionWindow:
        now = now_utc_iso()
        key = str(decision_window_id or "").strip()
        existing = self._rows.get(key) if key else None
        if existing and existing.principal_id != str(principal_id or "").strip():
            existing = None
        if existing:
            updated = DecisionWindow(
                decision_window_id=existing.decision_window_id,
                principal_id=existing.principal_id,
                title=str(title or existing.title).strip() or existing.title,
                context=str(context or existing.context).strip(),
                opens_at=str(opens_at or "").strip() or None,
                closes_at=str(closes_at or "").strip() or None,
                urgency=str(urgency or existing.urgency).strip() or existing.urgency,
                authority_required=str(authority_required or existing.authority_required).strip()
                or existing.authority_required,
                status=_normalize_status(status),
                notes=str(notes or "").strip(),
                source_json=dict(source_json or {}),
                created_at=existing.created_at,
                updated_at=now,
            )
            self._rows[existing.decision_window_id] = updated
            return updated
        row = DecisionWindow(
            decision_window_id=key or str(uuid.uuid4()),
            principal_id=str(principal_id or "").strip(),
            title=str(title or "").strip(),
            context=str(context or "").strip(),
            opens_at=str(opens_at or "").strip() or None,
            closes_at=str(closes_at or "").strip() or None,
            urgency=str(urgency or "medium").strip() or "medium",
            authority_required=str(authority_required or "manager").strip() or "manager",
            status=_normalize_status(status),
            notes=str(notes or "").strip(),
            source_json=dict(source_json or {}),
            created_at=now,
            updated_at=now,
        )
        self._rows[row.decision_window_id] = row
        self._order.append(row.decision_window_id)
        return row

    def get(self, decision_window_id: str) -> DecisionWindow | None:
        return self._rows.get(str(decision_window_id or ""))

    def list_decision_windows(
        self,
        *,
        principal_id: str,
        limit: int = 100,
        status: str | None = None,
    ) -> list[DecisionWindow]:
        n = max(1, min(500, int(limit or 100)))
        principal = str(principal_id or "").strip()
        status_filter = str(status or "").strip().lower()
        rows = [self._rows[wid] for wid in reversed(self._order) if wid in self._rows]
        rows = [row for row in rows if row.principal_id == principal]
        if status_filter:
            rows = [row for row in rows if row.status == status_filter]
        return rows[:n]
