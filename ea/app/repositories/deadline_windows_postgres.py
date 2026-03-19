from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from app.domain.models import DeadlineWindow, now_utc_iso


def _to_iso(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value or "")


def _normalize_status(value: str) -> str:
    raw = str(value or "").strip().lower()
    if raw in {"open", "monitoring", "elapsed", "cancelled"}:
        return raw
    return "open"


class PostgresDeadlineWindowRepository:
    def __init__(self, database_url: str) -> None:
        self._database_url = str(database_url or "").strip()
        if not self._database_url:
            raise ValueError("database_url is required for PostgresDeadlineWindowRepository")
        self._ensure_schema()

    def _connect(self):  # type: ignore[no-untyped-def]
        try:
            import psycopg
        except Exception as exc:  # pragma: no cover - import guard
            raise RuntimeError("psycopg is required for postgres deadline-window backend") from exc
        return psycopg.connect(self._database_url, autocommit=True)

    def _json_value(self, value: dict[str, Any]):  # type: ignore[no-untyped-def]
        from psycopg.types.json import Json

        return Json(value)

    def _ensure_schema(self) -> None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS deadline_windows (
                        window_id TEXT PRIMARY KEY,
                        principal_id TEXT NOT NULL,
                        title TEXT NOT NULL,
                        start_at TIMESTAMPTZ NULL,
                        end_at TIMESTAMPTZ NULL,
                        status TEXT NOT NULL,
                        priority TEXT NOT NULL,
                        notes TEXT NOT NULL,
                        source_json JSONB NOT NULL,
                        created_at TIMESTAMPTZ NOT NULL,
                        updated_at TIMESTAMPTZ NOT NULL
                    )
                    """
                )
                cur.execute("ALTER TABLE deadline_windows ADD COLUMN IF NOT EXISTS start_at TIMESTAMPTZ NULL")
                cur.execute("ALTER TABLE deadline_windows ADD COLUMN IF NOT EXISTS end_at TIMESTAMPTZ NULL")
                cur.execute("ALTER TABLE deadline_windows ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'open'")
                cur.execute(
                    "ALTER TABLE deadline_windows ADD COLUMN IF NOT EXISTS priority TEXT NOT NULL DEFAULT 'medium'"
                )
                cur.execute("ALTER TABLE deadline_windows ADD COLUMN IF NOT EXISTS notes TEXT NOT NULL DEFAULT ''")
                cur.execute(
                    "ALTER TABLE deadline_windows ADD COLUMN IF NOT EXISTS source_json JSONB NOT NULL DEFAULT '{}'::jsonb"
                )
                cur.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_deadline_windows_principal_status
                    ON deadline_windows(principal_id, status, updated_at DESC)
                    """
                )
                cur.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_deadline_windows_principal_end
                    ON deadline_windows(principal_id, end_at ASC)
                    """
                )

    def _from_row(self, row: tuple[Any, ...]) -> DeadlineWindow:
        (
            window_id,
            principal_id,
            title,
            start_at,
            end_at,
            status,
            priority,
            notes,
            source_json,
            created_at,
            updated_at,
        ) = row
        return DeadlineWindow(
            window_id=str(window_id),
            principal_id=str(principal_id),
            title=str(title),
            start_at=_to_iso(start_at) if start_at else None,
            end_at=_to_iso(end_at) if end_at else None,
            status=str(status or "open"),
            priority=str(priority or "medium"),
            notes=str(notes or ""),
            source_json=dict(source_json or {}),
            created_at=_to_iso(created_at),
            updated_at=_to_iso(updated_at),
        )

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
        row = DeadlineWindow(
            window_id=str(window_id or "").strip() or str(uuid.uuid4()),
            principal_id=str(principal_id or "").strip(),
            title=str(title or "").strip(),
            start_at=str(start_at or "").strip() or None,
            end_at=str(end_at or "").strip() or None,
            status=_normalize_status(status),
            priority=str(priority or "medium").strip() or "medium",
            notes=str(notes or "").strip(),
            source_json=dict(source_json or {}),
            created_at=now_utc_iso(),
            updated_at=now_utc_iso(),
        )
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO deadline_windows
                    (window_id, principal_id, title, start_at, end_at, status, priority, notes, source_json, created_at, updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (window_id) DO UPDATE
                    SET principal_id = EXCLUDED.principal_id,
                        title = EXCLUDED.title,
                        start_at = EXCLUDED.start_at,
                        end_at = EXCLUDED.end_at,
                        status = EXCLUDED.status,
                        priority = EXCLUDED.priority,
                        notes = EXCLUDED.notes,
                        source_json = EXCLUDED.source_json,
                        updated_at = EXCLUDED.updated_at
                    RETURNING window_id, principal_id, title, start_at, end_at, status, priority, notes, source_json, created_at, updated_at
                    """,
                    (
                        row.window_id,
                        row.principal_id,
                        row.title,
                        row.start_at,
                        row.end_at,
                        row.status,
                        row.priority,
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

    def get(self, window_id: str) -> DeadlineWindow | None:
        key = str(window_id or "")
        if not key:
            return None
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT window_id, principal_id, title, start_at, end_at, status, priority, notes, source_json, created_at, updated_at
                    FROM deadline_windows
                    WHERE window_id = %s
                    """,
                    (key,),
                )
                row = cur.fetchone()
        if not row:
            return None
        return self._from_row(row)

    def list_deadline_windows(
        self,
        *,
        principal_id: str | None = None,
        limit: int = 100,
        status: str | None = None,
    ) -> list[DeadlineWindow]:
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
            "SELECT window_id, principal_id, title, start_at, end_at, status, priority, notes, source_json, created_at, updated_at "
            "FROM deadline_windows "
            f"{where} "
            "ORDER BY updated_at DESC, window_id DESC LIMIT %s"
        )
        params.append(n)
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(query, tuple(params))
                rows = cur.fetchall()
        return [self._from_row(row) for row in rows]
