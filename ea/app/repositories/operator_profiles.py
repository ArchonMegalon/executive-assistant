from __future__ import annotations

import uuid
from typing import Dict, List, Protocol

from app.domain.models import OperatorProfile, now_utc_iso


class OperatorProfileRepository(Protocol):
    def upsert_profile(
        self,
        *,
        principal_id: str,
        operator_id: str | None = None,
        display_name: str,
        roles: tuple[str, ...] = (),
        skill_tags: tuple[str, ...] = (),
        trust_tier: str = "standard",
        status: str = "active",
        notes: str = "",
    ) -> OperatorProfile:
        ...

    def get(self, operator_id: str) -> OperatorProfile | None:
        ...

    def list_for_principal(
        self,
        *,
        principal_id: str,
        status: str | None = None,
        limit: int = 100,
    ) -> list[OperatorProfile]:
        ...


def _normalize_status(value: str) -> str:
    raw = str(value or "").strip().lower()
    if raw in {"active", "inactive", "archived"}:
        return raw
    return "active"


class InMemoryOperatorProfileRepository:
    def __init__(self) -> None:
        self._rows: Dict[str, OperatorProfile] = {}
        self._order: List[str] = []

    def upsert_profile(
        self,
        *,
        principal_id: str,
        operator_id: str | None = None,
        display_name: str,
        roles: tuple[str, ...] = (),
        skill_tags: tuple[str, ...] = (),
        trust_tier: str = "standard",
        status: str = "active",
        notes: str = "",
    ) -> OperatorProfile:
        now = now_utc_iso()
        key = str(operator_id or "").strip()
        existing = self._rows.get(key) if key else None
        if existing and existing.principal_id != str(principal_id or "").strip():
            existing = None
        row = OperatorProfile(
            operator_id=existing.operator_id if existing else (key or str(uuid.uuid4())),
            principal_id=str(principal_id or "").strip(),
            display_name=str(display_name or existing.display_name if existing else display_name).strip(),
            roles=tuple(str(v).strip() for v in roles if str(v).strip()),
            skill_tags=tuple(str(v).strip().lower() for v in skill_tags if str(v).strip()),
            trust_tier=str(trust_tier or (existing.trust_tier if existing else "standard")).strip() or "standard",
            status=_normalize_status(status),
            notes=str(notes or "").strip(),
            created_at=existing.created_at if existing else now,
            updated_at=now,
        )
        self._rows[row.operator_id] = row
        if row.operator_id not in self._order:
            self._order.append(row.operator_id)
        return row

    def get(self, operator_id: str) -> OperatorProfile | None:
        return self._rows.get(str(operator_id or "").strip())

    def list_for_principal(
        self,
        *,
        principal_id: str,
        status: str | None = None,
        limit: int = 100,
    ) -> list[OperatorProfile]:
        principal = str(principal_id or "").strip()
        status_filter = str(status or "").strip().lower()
        n = max(1, min(500, int(limit or 100)))
        rows = [self._rows[row_id] for row_id in reversed(self._order) if row_id in self._rows]
        rows = [row for row in rows if row.principal_id == principal]
        if status_filter:
            rows = [row for row in rows if row.status == status_filter]
        return rows[:n]
