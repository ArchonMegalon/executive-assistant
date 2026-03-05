from __future__ import annotations

import uuid
from typing import Dict, List, Protocol

from app.domain.models import Commitment, now_utc_iso


class CommitmentRepository(Protocol):
    def upsert_commitment(
        self,
        *,
        principal_id: str,
        title: str,
        details: str = "",
        status: str = "open",
        priority: str = "medium",
        due_at: str | None = None,
        source_json: dict[str, object] | None = None,
        commitment_id: str | None = None,
    ) -> Commitment:
        ...

    def get(self, commitment_id: str) -> Commitment | None:
        ...

    def list_commitments(
        self,
        *,
        principal_id: str,
        limit: int = 100,
        status: str | None = None,
    ) -> list[Commitment]:
        ...



def _normalize_status(value: str) -> str:
    normalized = str(value or "").strip().lower()
    if normalized in {"open", "in_progress", "completed", "cancelled"}:
        return normalized
    return "open"


class InMemoryCommitmentRepository:
    def __init__(self) -> None:
        self._rows: Dict[str, Commitment] = {}
        self._order: List[str] = []

    def upsert_commitment(
        self,
        *,
        principal_id: str,
        title: str,
        details: str = "",
        status: str = "open",
        priority: str = "medium",
        due_at: str | None = None,
        source_json: dict[str, object] | None = None,
        commitment_id: str | None = None,
    ) -> Commitment:
        now = now_utc_iso()
        key = str(commitment_id or "").strip()
        existing = self._rows.get(key) if key else None
        if existing and existing.principal_id != str(principal_id or "").strip():
            existing = None
        if existing:
            updated = Commitment(
                commitment_id=existing.commitment_id,
                principal_id=existing.principal_id,
                title=str(title or existing.title).strip() or existing.title,
                details=str(details or "").strip(),
                status=_normalize_status(status),
                priority=str(priority or existing.priority).strip() or existing.priority,
                due_at=str(due_at or "").strip() or None,
                source_json=dict(source_json or {}),
                created_at=existing.created_at,
                updated_at=now,
            )
            self._rows[existing.commitment_id] = updated
            return updated
        row = Commitment(
            commitment_id=key or str(uuid.uuid4()),
            principal_id=str(principal_id or "").strip(),
            title=str(title or "").strip(),
            details=str(details or "").strip(),
            status=_normalize_status(status),
            priority=str(priority or "medium").strip() or "medium",
            due_at=str(due_at or "").strip() or None,
            source_json=dict(source_json or {}),
            created_at=now,
            updated_at=now,
        )
        self._rows[row.commitment_id] = row
        self._order.append(row.commitment_id)
        return row

    def get(self, commitment_id: str) -> Commitment | None:
        return self._rows.get(str(commitment_id or ""))

    def list_commitments(
        self,
        *,
        principal_id: str,
        limit: int = 100,
        status: str | None = None,
    ) -> list[Commitment]:
        n = max(1, min(500, int(limit or 100)))
        principal = str(principal_id or "").strip()
        status_filter = str(status or "").strip().lower()
        rows = [self._rows[cid] for cid in reversed(self._order) if cid in self._rows]
        rows = [row for row in rows if row.principal_id == principal]
        if status_filter:
            rows = [row for row in rows if row.status == status_filter]
        return rows[:n]
