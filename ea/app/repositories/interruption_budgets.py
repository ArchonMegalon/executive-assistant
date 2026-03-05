from __future__ import annotations

import uuid
from typing import Dict, List, Protocol

from app.domain.models import InterruptionBudget, now_utc_iso


class InterruptionBudgetRepository(Protocol):
    def upsert_budget(
        self,
        *,
        principal_id: str,
        scope: str,
        window_kind: str = "daily",
        budget_minutes: int = 120,
        used_minutes: int = 0,
        reset_at: str | None = None,
        quiet_hours_json: dict[str, object] | None = None,
        status: str = "active",
        notes: str = "",
        budget_id: str | None = None,
    ) -> InterruptionBudget:
        ...

    def get(self, budget_id: str) -> InterruptionBudget | None:
        ...

    def list_budgets(
        self,
        *,
        principal_id: str,
        limit: int = 100,
        status: str | None = None,
    ) -> list[InterruptionBudget]:
        ...


def _normalize_status(value: str) -> str:
    raw = str(value or "").strip().lower()
    if raw in {"active", "paused", "archived"}:
        return raw
    return "active"


class InMemoryInterruptionBudgetRepository:
    def __init__(self) -> None:
        self._rows: Dict[str, InterruptionBudget] = {}
        self._order: List[str] = []

    def upsert_budget(
        self,
        *,
        principal_id: str,
        scope: str,
        window_kind: str = "daily",
        budget_minutes: int = 120,
        used_minutes: int = 0,
        reset_at: str | None = None,
        quiet_hours_json: dict[str, object] | None = None,
        status: str = "active",
        notes: str = "",
        budget_id: str | None = None,
    ) -> InterruptionBudget:
        now = now_utc_iso()
        key = str(budget_id or "").strip()
        existing = self._rows.get(key) if key else None
        if existing and existing.principal_id != str(principal_id or "").strip():
            existing = None
        if existing:
            updated = InterruptionBudget(
                budget_id=existing.budget_id,
                principal_id=existing.principal_id,
                scope=str(scope or existing.scope).strip() or existing.scope,
                window_kind=str(window_kind or existing.window_kind).strip() or existing.window_kind,
                budget_minutes=max(0, int(budget_minutes if budget_minutes is not None else existing.budget_minutes)),
                used_minutes=max(0, int(used_minutes if used_minutes is not None else existing.used_minutes)),
                reset_at=str(reset_at or "").strip() or None,
                quiet_hours_json=dict(quiet_hours_json or {}),
                status=_normalize_status(status),
                notes=str(notes or "").strip(),
                created_at=existing.created_at,
                updated_at=now,
            )
            self._rows[existing.budget_id] = updated
            return updated
        row = InterruptionBudget(
            budget_id=key or str(uuid.uuid4()),
            principal_id=str(principal_id or "").strip(),
            scope=str(scope or "").strip(),
            window_kind=str(window_kind or "daily").strip() or "daily",
            budget_minutes=max(0, int(budget_minutes or 0)),
            used_minutes=max(0, int(used_minutes or 0)),
            reset_at=str(reset_at or "").strip() or None,
            quiet_hours_json=dict(quiet_hours_json or {}),
            status=_normalize_status(status),
            notes=str(notes or "").strip(),
            created_at=now,
            updated_at=now,
        )
        self._rows[row.budget_id] = row
        self._order.append(row.budget_id)
        return row

    def get(self, budget_id: str) -> InterruptionBudget | None:
        return self._rows.get(str(budget_id or ""))

    def list_budgets(
        self,
        *,
        principal_id: str,
        limit: int = 100,
        status: str | None = None,
    ) -> list[InterruptionBudget]:
        n = max(1, min(500, int(limit or 100)))
        principal = str(principal_id or "").strip()
        status_filter = str(status or "").strip().lower()
        rows = [self._rows[bid] for bid in reversed(self._order) if bid in self._rows]
        rows = [row for row in rows if row.principal_id == principal]
        if status_filter:
            rows = [row for row in rows if row.status == status_filter]
        return rows[:n]
