from __future__ import annotations

import uuid
from typing import Dict, List, Protocol

from app.domain.models import PolicyDecision, PolicyDecisionRecord, now_utc_iso


class PolicyDecisionRepository(Protocol):
    def append(self, session_id: str, decision: PolicyDecision) -> PolicyDecisionRecord:
        ...

    def list_recent(self, limit: int = 50, session_id: str | None = None) -> list[PolicyDecisionRecord]:
        ...


class InMemoryPolicyDecisionRepository:
    def __init__(self) -> None:
        self._rows: Dict[str, PolicyDecisionRecord] = {}
        self._order: List[str] = []

    def append(self, session_id: str, decision: PolicyDecision) -> PolicyDecisionRecord:
        row = PolicyDecisionRecord(
            decision_id=str(uuid.uuid4()),
            session_id=str(session_id or ""),
            allow=bool(decision.allow),
            requires_approval=bool(decision.requires_approval),
            reason=str(decision.reason or ""),
            retention_policy=str(decision.retention_policy or ""),
            memory_write_allowed=bool(decision.memory_write_allowed),
            created_at=now_utc_iso(),
        )
        self._rows[row.decision_id] = row
        self._order.append(row.decision_id)
        return row

    def list_recent(self, limit: int = 50, session_id: str | None = None) -> list[PolicyDecisionRecord]:
        n = max(1, min(500, int(limit or 50)))
        sid = str(session_id or "").strip()
        ids = list(reversed(self._order))
        if sid:
            ids = [i for i in ids if self._rows.get(i) and self._rows[i].session_id == sid]
        return [self._rows[i] for i in ids[:n] if i in self._rows]
