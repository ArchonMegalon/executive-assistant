from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from app.domain.models import Commitment, now_utc_iso


def _to_iso(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value or "")


def _normalize_status(value: str) -> str:
    normalized = str(value or "").strip().lower()
    if normalized in {"open", "in_progress", "completed", "cancelled"}:
        return normalized
    return "open"


class PostgresCommitmentRepository:
    def __init__(self, database_url: str) -> None:
        self._database_url = str(database_url or "").strip()
        if not self._database_url:
            raise ValueError("database_url is required for PostgresCommitmentRepository")
        self._ensure_schema()

    def _connect(self):  # type: ignore[no-untyped-def]
        try:
            import psycopg
        except Exception as exc:  # pragma: no cover - import guard
            raise RuntimeError("psycopg is required for postgres commitment backend") from exc
        return psycopg.connect(self._database_url, autocommit=True)

    def _json_value(self, value: dict[str, Any]):  # type: ignore[no-untyped-def]
        from psycopg.types.json import Json

        return Json(value)

    def _ensure_schema(self) -> None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS commitments (
                        commitment_id TEXT PRIMARY KEY,
                        principal_id TEXT NOT NULL,
                        title TEXT NOT NULL,
                        details TEXT NOT NULL,
                        status TEXT NOT NULL,
                        priority TEXT NOT NULL,
                        due_at TIMESTAMPTZ NULL,
                        source_json JSONB NOT NULL,
                        created_at TIMESTAMPTZ NOT NULL,
                        updated_at TIMESTAMPTZ NOT NULL
                    )
                    """
                )
                cur.execute("ALTER TABLE commitments ADD COLUMN IF NOT EXISTS details TEXT NOT NULL DEFAULT ''")
                cur.execute("ALTER TABLE commitments ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'open'")
                cur.execute("ALTER TABLE commitments ADD COLUMN IF NOT EXISTS priority TEXT NOT NULL DEFAULT 'medium'")
                cur.execute("ALTER TABLE commitments ADD COLUMN IF NOT EXISTS due_at TIMESTAMPTZ NULL")
                cur.execute(
                    "ALTER TABLE commitments ADD COLUMN IF NOT EXISTS source_json JSONB NOT NULL DEFAULT '{}'::jsonb"
                )
                cur.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_commitments_principal_updated
                    ON commitments(principal_id, updated_at DESC)
                    """
                )
                cur.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_commitments_principal_status
                    ON commitments(principal_id, status, updated_at DESC)
                    """
                )

    def _from_row(self, row: tuple[Any, ...]) -> Commitment:
        (
            commitment_id,
            principal_id,
            title,
            details,
            status,
            priority,
            due_at,
            source_json,
            created_at,
            updated_at,
        ) = row
        return Commitment(
            commitment_id=str(commitment_id),
            principal_id=str(principal_id),
            title=str(title),
            details=str(details or ""),
            status=str(status or "open"),
            priority=str(priority or "medium"),
            due_at=_to_iso(due_at) if due_at else None,
            source_json=dict(source_json or {}),
            created_at=_to_iso(created_at),
            updated_at=_to_iso(updated_at),
        )

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
        cid = str(commitment_id or "").strip() or str(uuid.uuid4())
        row = Commitment(
            commitment_id=cid,
            principal_id=str(principal_id or "").strip(),
            title=str(title or "").strip(),
            details=str(details or "").strip(),
            status=_normalize_status(status),
            priority=str(priority or "medium").strip() or "medium",
            due_at=str(due_at or "").strip() or None,
            source_json=dict(source_json or {}),
            created_at=now_utc_iso(),
            updated_at=now_utc_iso(),
        )
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO commitments
                    (commitment_id, principal_id, title, details, status, priority, due_at, source_json, created_at, updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (commitment_id) DO UPDATE
                    SET principal_id = EXCLUDED.principal_id,
                        title = EXCLUDED.title,
                        details = EXCLUDED.details,
                        status = EXCLUDED.status,
                        priority = EXCLUDED.priority,
                        due_at = EXCLUDED.due_at,
                        source_json = EXCLUDED.source_json,
                        updated_at = EXCLUDED.updated_at
                    RETURNING commitment_id, principal_id, title, details, status, priority, due_at, source_json, created_at, updated_at
                    """,
                    (
                        row.commitment_id,
                        row.principal_id,
                        row.title,
                        row.details,
                        row.status,
                        row.priority,
                        row.due_at,
                        self._json_value(row.source_json),
                        row.created_at,
                        row.updated_at,
                    ),
                )
                out = cur.fetchone()
        if not out:
            return row
        return self._from_row(out)

    def get(self, commitment_id: str) -> Commitment | None:
        key = str(commitment_id or "")
        if not key:
            return None
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT commitment_id, principal_id, title, details, status, priority, due_at, source_json, created_at, updated_at
                    FROM commitments
                    WHERE commitment_id = %s
                    """,
                    (key,),
                )
                row = cur.fetchone()
        if not row:
            return None
        return self._from_row(row)

    def list_commitments(
        self,
        *,
        principal_id: str,
        limit: int = 100,
        status: str | None = None,
    ) -> list[Commitment]:
        principal = str(principal_id or "").strip()
        n = max(1, min(500, int(limit or 100)))
        status_filter = str(status or "").strip().lower()
        where = "WHERE principal_id = %s"
        params: list[object] = [principal]
        if status_filter:
            where += " AND status = %s"
            params.append(status_filter)
        query = (
            "SELECT commitment_id, principal_id, title, details, status, priority, due_at, source_json, created_at, updated_at "
            "FROM commitments "
            f"{where} "
            "ORDER BY updated_at DESC, commitment_id DESC LIMIT %s"
        )
        params.append(n)
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(query, tuple(params))
                rows = cur.fetchall()
        return [self._from_row(row) for row in rows]
