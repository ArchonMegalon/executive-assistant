from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from app.domain.models import DecisionWindow, now_utc_iso


def _to_iso(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value or "")


def _normalize_status(value: str) -> str:
    raw = str(value or "").strip().lower()
    if raw in {"open", "decided", "expired", "cancelled"}:
        return raw
    return "open"


class PostgresDecisionWindowRepository:
    def __init__(self, database_url: str) -> None:
        self._database_url = str(database_url or "").strip()
        if not self._database_url:
            raise ValueError("database_url is required for PostgresDecisionWindowRepository")
        self._ensure_schema()

    def _connect(self):  # type: ignore[no-untyped-def]
        try:
            import psycopg
        except Exception as exc:  # pragma: no cover - import guard
            raise RuntimeError("psycopg is required for postgres decision-window backend") from exc
        return psycopg.connect(self._database_url, autocommit=True)

    def _json_value(self, value: dict[str, Any]):  # type: ignore[no-untyped-def]
        from psycopg.types.json import Json

        return Json(value)

    def _ensure_schema(self) -> None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS decision_windows (
                        decision_window_id TEXT PRIMARY KEY,
                        principal_id TEXT NOT NULL,
                        title TEXT NOT NULL,
                        context TEXT NOT NULL,
                        opens_at TIMESTAMPTZ NULL,
                        closes_at TIMESTAMPTZ NULL,
                        urgency TEXT NOT NULL,
                        authority_required TEXT NOT NULL,
                        status TEXT NOT NULL,
                        notes TEXT NOT NULL,
                        source_json JSONB NOT NULL,
                        created_at TIMESTAMPTZ NOT NULL,
                        updated_at TIMESTAMPTZ NOT NULL
                    )
                    """
                )
                cur.execute("ALTER TABLE decision_windows ADD COLUMN IF NOT EXISTS context TEXT NOT NULL DEFAULT ''")
                cur.execute("ALTER TABLE decision_windows ADD COLUMN IF NOT EXISTS opens_at TIMESTAMPTZ NULL")
                cur.execute("ALTER TABLE decision_windows ADD COLUMN IF NOT EXISTS closes_at TIMESTAMPTZ NULL")
                cur.execute("ALTER TABLE decision_windows ADD COLUMN IF NOT EXISTS urgency TEXT NOT NULL DEFAULT 'medium'")
                cur.execute(
                    "ALTER TABLE decision_windows ADD COLUMN IF NOT EXISTS authority_required TEXT NOT NULL DEFAULT 'manager'"
                )
                cur.execute("ALTER TABLE decision_windows ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'open'")
                cur.execute("ALTER TABLE decision_windows ADD COLUMN IF NOT EXISTS notes TEXT NOT NULL DEFAULT ''")
                cur.execute(
                    "ALTER TABLE decision_windows ADD COLUMN IF NOT EXISTS source_json JSONB NOT NULL DEFAULT '{}'::jsonb"
                )
                cur.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_decision_windows_principal_status
                    ON decision_windows(principal_id, status, updated_at DESC)
                    """
                )
                cur.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_decision_windows_principal_closes
                    ON decision_windows(principal_id, closes_at ASC)
                    """
                )

    def _from_row(self, row: tuple[Any, ...]) -> DecisionWindow:
        (
            decision_window_id,
            principal_id,
            title,
            context,
            opens_at,
            closes_at,
            urgency,
            authority_required,
            status,
            notes,
            source_json,
            created_at,
            updated_at,
        ) = row
        return DecisionWindow(
            decision_window_id=str(decision_window_id),
            principal_id=str(principal_id),
            title=str(title),
            context=str(context or ""),
            opens_at=_to_iso(opens_at) if opens_at else None,
            closes_at=_to_iso(closes_at) if closes_at else None,
            urgency=str(urgency or "medium"),
            authority_required=str(authority_required or "manager"),
            status=str(status or "open"),
            notes=str(notes or ""),
            source_json=dict(source_json or {}),
            created_at=_to_iso(created_at),
            updated_at=_to_iso(updated_at),
        )

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
        row = DecisionWindow(
            decision_window_id=str(decision_window_id or "").strip() or str(uuid.uuid4()),
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
            created_at=now_utc_iso(),
            updated_at=now_utc_iso(),
        )
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO decision_windows
                    (decision_window_id, principal_id, title, context, opens_at, closes_at, urgency, authority_required, status, notes, source_json, created_at, updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (decision_window_id) DO UPDATE
                    SET principal_id = EXCLUDED.principal_id,
                        title = EXCLUDED.title,
                        context = EXCLUDED.context,
                        opens_at = EXCLUDED.opens_at,
                        closes_at = EXCLUDED.closes_at,
                        urgency = EXCLUDED.urgency,
                        authority_required = EXCLUDED.authority_required,
                        status = EXCLUDED.status,
                        notes = EXCLUDED.notes,
                        source_json = EXCLUDED.source_json,
                        updated_at = EXCLUDED.updated_at
                    RETURNING decision_window_id, principal_id, title, context, opens_at, closes_at, urgency, authority_required, status, notes, source_json, created_at, updated_at
                    """,
                    (
                        row.decision_window_id,
                        row.principal_id,
                        row.title,
                        row.context,
                        row.opens_at,
                        row.closes_at,
                        row.urgency,
                        row.authority_required,
                        row.status,
                        row.notes,
                        self._json_value(row.source_json),
                        row.created_at,
                        row.updated_at,
                    ),
                )
                out = cur.fetchone()
        if not out:
            return row
        return self._from_row(out)

    def get(self, decision_window_id: str) -> DecisionWindow | None:
        key = str(decision_window_id or "")
        if not key:
            return None
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT decision_window_id, principal_id, title, context, opens_at, closes_at, urgency, authority_required, status, notes, source_json, created_at, updated_at
                    FROM decision_windows
                    WHERE decision_window_id = %s
                    """,
                    (key,),
                )
                row = cur.fetchone()
        if not row:
            return None
        return self._from_row(row)

    def list_decision_windows(
        self,
        *,
        principal_id: str | None = None,
        limit: int = 100,
        status: str | None = None,
    ) -> list[DecisionWindow]:
        principal = str(principal_id or "").strip()
        n = max(1, min(500, int(limit or 100)))
        status_filter = str(status or "").strip().lower()
        where_clauses: list[str] = []
        params: list[object] = []
        if principal:
            where_clauses.append("principal_id = %s")
            params.append(principal)
        if status_filter:
            where_clauses.append("status = %s")
            params.append(status_filter)
        where = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""
        query = (
            "SELECT decision_window_id, principal_id, title, context, opens_at, closes_at, urgency, authority_required, status, notes, source_json, created_at, updated_at "
            "FROM decision_windows "
            f"{where} "
            "ORDER BY updated_at DESC, decision_window_id DESC LIMIT %s"
        )
        params.append(n)
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(query, tuple(params))
                rows = cur.fetchall()
        return [self._from_row(row) for row in rows]
