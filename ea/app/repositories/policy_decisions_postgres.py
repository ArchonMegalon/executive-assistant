from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from app.domain.models import PolicyDecision, PolicyDecisionRecord, now_utc_iso


def _to_iso(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value or "")


class PostgresPolicyDecisionRepository:
    def __init__(self, database_url: str) -> None:
        self._database_url = str(database_url or "").strip()
        if not self._database_url:
            raise ValueError("database_url is required for PostgresPolicyDecisionRepository")
        self._ensure_schema()

    def _connect(self):  # type: ignore[no-untyped-def]
        try:
            import psycopg
        except Exception as exc:  # pragma: no cover - import guard
            raise RuntimeError("psycopg is required for postgres backend") from exc
        return psycopg.connect(self._database_url, autocommit=True)

    def _ensure_schema(self) -> None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS policy_decisions (
                        decision_id TEXT PRIMARY KEY,
                        session_id TEXT NOT NULL,
                        allow BOOLEAN NOT NULL,
                        requires_approval BOOLEAN NOT NULL,
                        reason TEXT NOT NULL,
                        retention_policy TEXT NOT NULL,
                        memory_write_allowed BOOLEAN NOT NULL,
                        created_at TIMESTAMPTZ NOT NULL
                    )
                    """
                )
                cur.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_policy_decisions_created
                    ON policy_decisions(created_at DESC)
                    """
                )
                cur.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_policy_decisions_session_created
                    ON policy_decisions(session_id, created_at DESC)
                    """
                )

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
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO policy_decisions
                    (decision_id, session_id, allow, requires_approval, reason, retention_policy, memory_write_allowed, created_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        row.decision_id,
                        row.session_id,
                        row.allow,
                        row.requires_approval,
                        row.reason,
                        row.retention_policy,
                        row.memory_write_allowed,
                        row.created_at,
                    ),
                )
        return row

    def list_recent(self, limit: int = 50, session_id: str | None = None) -> list[PolicyDecisionRecord]:
        n = max(1, min(500, int(limit or 50)))
        sid = str(session_id or "").strip()
        with self._connect() as conn:
            with conn.cursor() as cur:
                if sid:
                    cur.execute(
                        """
                        SELECT decision_id, session_id, allow, requires_approval, reason, retention_policy, memory_write_allowed, created_at
                        FROM policy_decisions
                        WHERE session_id = %s
                        ORDER BY created_at DESC, decision_id DESC
                        LIMIT %s
                        """,
                        (sid, n),
                    )
                else:
                    cur.execute(
                        """
                        SELECT decision_id, session_id, allow, requires_approval, reason, retention_policy, memory_write_allowed, created_at
                        FROM policy_decisions
                        ORDER BY created_at DESC, decision_id DESC
                        LIMIT %s
                        """,
                        (n,),
                    )
                rows = cur.fetchall()
        return [
            PolicyDecisionRecord(
                decision_id=str(decision_id),
                session_id=str(found_sid),
                allow=bool(allow),
                requires_approval=bool(requires_approval),
                reason=str(reason),
                retention_policy=str(retention_policy),
                memory_write_allowed=bool(memory_write_allowed),
                created_at=_to_iso(created_at),
            )
            for decision_id, found_sid, allow, requires_approval, reason, retention_policy, memory_write_allowed, created_at in rows
        ]
