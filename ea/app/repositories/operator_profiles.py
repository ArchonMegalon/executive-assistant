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

    def get(self, operator_id: str, *, principal_id: str | None = None) -> OperatorProfile | None:
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
        self._rows: Dict[tuple[str, str], OperatorProfile] = {}
        self._order: List[tuple[str, str]] = []

    def _key(self, principal_id: str, operator_id: str) -> tuple[str, str]:
        return (str(principal_id or "").strip(), str(operator_id or "").strip())

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
        normalized_principal = str(principal_id or "").strip()
        key = str(operator_id or "").strip()
        existing = self._rows.get(self._key(normalized_principal, key)) if key else None
        row = OperatorProfile(
            operator_id=existing.operator_id if existing else (key or str(uuid.uuid4())),
            principal_id=normalized_principal,
            display_name=str(display_name or existing.display_name if existing else display_name).strip(),
            roles=tuple(str(v).strip() for v in roles if str(v).strip()),
            skill_tags=tuple(str(v).strip().lower() for v in skill_tags if str(v).strip()),
            trust_tier=str(trust_tier or (existing.trust_tier if existing else "standard")).strip() or "standard",
            status=_normalize_status(status),
            notes=str(notes or "").strip(),
            created_at=existing.created_at if existing else now,
            updated_at=now,
        )
        storage_key = self._key(row.principal_id, row.operator_id)
        self._rows[storage_key] = row
        if storage_key not in self._order:
            self._order.append(storage_key)
        return row

    def get(self, operator_id: str, *, principal_id: str | None = None) -> OperatorProfile | None:
        normalized_operator_id = str(operator_id or "").strip()
        if not normalized_operator_id:
            return None
        normalized_principal = str(principal_id or "").strip()
        if normalized_principal:
            return self._rows.get(self._key(normalized_principal, normalized_operator_id))
        matches = [
            row
            for (row_principal_id, row_operator_id), row in self._rows.items()
            if row_operator_id == normalized_operator_id
        ]
        if len(matches) == 1:
            return matches[0]
        return None

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
