from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from app.domain.models import FollowUp, now_utc_iso


def _to_iso(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value or "")


def _normalize_status(value: str) -> str:
    raw = str(value or "").strip().lower()
    if raw in {"open", "completed", "cancelled"}:
        return raw
    return "open"


class PostgresFollowUpRepository:
    def __init__(self, database_url: str) -> None:
        self._database_url = str(database_url or "").strip()
        if not self._database_url:
            raise ValueError("database_url is required for PostgresFollowUpRepository")
        self._ensure_schema()

    def _connect(self):  # type: ignore[no-untyped-def]
        try:
            import psycopg
        except Exception as exc:  # pragma: no cover - import guard
            raise RuntimeError("psycopg is required for postgres follow-up backend") from exc
        return psycopg.connect(self._database_url, autocommit=True)

    def _json_value(self, value: dict[str, Any]):  # type: ignore[no-untyped-def]
        from psycopg.types.json import Json

        return Json(value)

    def _ensure_schema(self) -> None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS follow_ups (
                        follow_up_id TEXT PRIMARY KEY,
                        principal_id TEXT NOT NULL,
                        stakeholder_ref TEXT NOT NULL,
                        topic TEXT NOT NULL,
                        status TEXT NOT NULL,
                        due_at TIMESTAMPTZ NULL,
                        channel_hint TEXT NOT NULL,
                        notes TEXT NOT NULL,
                        source_json JSONB NOT NULL,
                        created_at TIMESTAMPTZ NOT NULL,
                        updated_at TIMESTAMPTZ NOT NULL
                    )
                    """
                )
                cur.execute("ALTER TABLE follow_ups ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'open'")
                cur.execute("ALTER TABLE follow_ups ADD COLUMN IF NOT EXISTS due_at TIMESTAMPTZ NULL")
                cur.execute("ALTER TABLE follow_ups ADD COLUMN IF NOT EXISTS channel_hint TEXT NOT NULL DEFAULT ''")
                cur.execute("ALTER TABLE follow_ups ADD COLUMN IF NOT EXISTS notes TEXT NOT NULL DEFAULT ''")
                cur.execute("ALTER TABLE follow_ups ADD COLUMN IF NOT EXISTS source_json JSONB NOT NULL DEFAULT '{}'::jsonb")
                cur.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_follow_ups_principal_status
                    ON follow_ups(principal_id, status, updated_at DESC)
                    """
                )
                cur.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_follow_ups_principal_due
                    ON follow_ups(principal_id, due_at ASC)
                    """
                )

    def _from_row(self, row: tuple[Any, ...]) -> FollowUp:
        (
            follow_up_id,
            principal_id,
            stakeholder_ref,
            topic,
            status,
            due_at,
            channel_hint,
            notes,
            source_json,
            created_at,
            updated_at,
        ) = row
        return FollowUp(
            follow_up_id=str(follow_up_id),
            principal_id=str(principal_id),
            stakeholder_ref=str(stakeholder_ref),
            topic=str(topic),
            status=str(status or "open"),
            due_at=_to_iso(due_at) if due_at else None,
            channel_hint=str(channel_hint or ""),
            notes=str(notes or ""),
            source_json=dict(source_json or {}),
            created_at=_to_iso(created_at),
            updated_at=_to_iso(updated_at),
        )

    def upsert_follow_up(
        self,
        *,
        principal_id: str,
        stakeholder_ref: str,
        topic: str,
        status: str = "open",
        due_at: str | None = None,
        channel_hint: str = "",
        notes: str = "",
        source_json: dict[str, object] | None = None,
        follow_up_id: str | None = None,
    ) -> FollowUp:
        now = now_utc_iso()
        row = FollowUp(
            follow_up_id=str(follow_up_id or "").strip() or str(uuid.uuid4()),
            principal_id=str(principal_id or "").strip(),
            stakeholder_ref=str(stakeholder_ref or "").strip(),
            topic=str(topic or "").strip(),
            status=_normalize_status(status),
            due_at=str(due_at or "").strip() or None,
            channel_hint=str(channel_hint or "").strip(),
            notes=str(notes or "").strip(),
            source_json=dict(source_json or {}),
            created_at=now,
            updated_at=now,
        )
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO follow_ups
                    (follow_up_id, principal_id, stakeholder_ref, topic, status, due_at,
                     channel_hint, notes, source_json, created_at, updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (follow_up_id) DO UPDATE
                    SET principal_id = EXCLUDED.principal_id,
                        stakeholder_ref = EXCLUDED.stakeholder_ref,
                        topic = EXCLUDED.topic,
                        status = EXCLUDED.status,
                        due_at = EXCLUDED.due_at,
                        channel_hint = EXCLUDED.channel_hint,
                        notes = EXCLUDED.notes,
                        source_json = EXCLUDED.source_json,
                        updated_at = EXCLUDED.updated_at
                    RETURNING follow_up_id, principal_id, stakeholder_ref, topic, status, due_at,
                              channel_hint, notes, source_json, created_at, updated_at
                    """,
                    (
                        row.follow_up_id,
                        row.principal_id,
                        row.stakeholder_ref,
                        row.topic,
                        row.status,
                        row.due_at,
                        row.channel_hint,
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

    def get(self, follow_up_id: str) -> FollowUp | None:
        key = str(follow_up_id or "")
        if not key:
            return None
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT follow_up_id, principal_id, stakeholder_ref, topic, status, due_at,
                           channel_hint, notes, source_json, created_at, updated_at
                    FROM follow_ups
                    WHERE follow_up_id = %s
                    """,
                    (key,),
                )
                row = cur.fetchone()
        if not row:
            return None
        return self._from_row(row)

    def list_follow_ups(
        self,
        *,
        principal_id: str,
        limit: int = 100,
        status: str | None = None,
    ) -> list[FollowUp]:
        principal = str(principal_id or "").strip()
        n = max(1, min(500, int(limit or 100)))
        status_filter = str(status or "").strip().lower()
        where = "WHERE principal_id = %s"
        params: list[object] = [principal]
        if status_filter:
            where += " AND status = %s"
            params.append(status_filter)
        query = (
            "SELECT follow_up_id, principal_id, stakeholder_ref, topic, status, due_at, "
            "channel_hint, notes, source_json, created_at, updated_at "
            "FROM follow_ups "
            f"{where} "
            "ORDER BY updated_at DESC, follow_up_id DESC LIMIT %s"
        )
        params.append(n)
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(query, tuple(params))
                rows = cur.fetchall()
        return [self._from_row(row) for row in rows]
