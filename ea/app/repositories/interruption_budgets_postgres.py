from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from app.domain.models import InterruptionBudget, now_utc_iso


def _to_iso(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value or "")


def _normalize_status(value: str) -> str:
    raw = str(value or "").strip().lower()
    if raw in {"active", "paused", "archived"}:
        return raw
    return "active"


class PostgresInterruptionBudgetRepository:
    def __init__(self, database_url: str) -> None:
        self._database_url = str(database_url or "").strip()
        if not self._database_url:
            raise ValueError("database_url is required for PostgresInterruptionBudgetRepository")
        self._ensure_schema()

    def _connect(self):  # type: ignore[no-untyped-def]
        try:
            import psycopg
        except Exception as exc:  # pragma: no cover - import guard
            raise RuntimeError("psycopg is required for postgres interruption-budget backend") from exc
        return psycopg.connect(self._database_url, autocommit=True)

    def _json_value(self, value: Any):  # type: ignore[no-untyped-def]
        from psycopg.types.json import Json

        return Json(value)

    def _ensure_schema(self) -> None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS interruption_budgets (
                        budget_id TEXT PRIMARY KEY,
                        principal_id TEXT NOT NULL,
                        scope TEXT NOT NULL,
                        window_kind TEXT NOT NULL,
                        budget_minutes INTEGER NOT NULL,
                        used_minutes INTEGER NOT NULL,
                        reset_at TIMESTAMPTZ NULL,
                        quiet_hours_json JSONB NOT NULL,
                        status TEXT NOT NULL,
                        notes TEXT NOT NULL,
                        created_at TIMESTAMPTZ NOT NULL,
                        updated_at TIMESTAMPTZ NOT NULL
                    )
                    """
                )
                cur.execute(
                    "ALTER TABLE interruption_budgets ADD COLUMN IF NOT EXISTS window_kind TEXT NOT NULL DEFAULT 'daily'"
                )
                cur.execute(
                    "ALTER TABLE interruption_budgets ADD COLUMN IF NOT EXISTS budget_minutes INTEGER NOT NULL DEFAULT 120"
                )
                cur.execute(
                    "ALTER TABLE interruption_budgets ADD COLUMN IF NOT EXISTS used_minutes INTEGER NOT NULL DEFAULT 0"
                )
                cur.execute("ALTER TABLE interruption_budgets ADD COLUMN IF NOT EXISTS reset_at TIMESTAMPTZ NULL")
                cur.execute(
                    "ALTER TABLE interruption_budgets ADD COLUMN IF NOT EXISTS quiet_hours_json JSONB NOT NULL DEFAULT '{}'::jsonb"
                )
                cur.execute("ALTER TABLE interruption_budgets ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'active'")
                cur.execute("ALTER TABLE interruption_budgets ADD COLUMN IF NOT EXISTS notes TEXT NOT NULL DEFAULT ''")
                cur.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_interrupt_budgets_principal_status
                    ON interruption_budgets(principal_id, status, updated_at DESC)
                    """
                )
                cur.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_interrupt_budgets_principal_scope
                    ON interruption_budgets(principal_id, scope)
                    """
                )

    def _from_row(self, row: tuple[Any, ...]) -> InterruptionBudget:
        (
            budget_id,
            principal_id,
            scope,
            window_kind,
            budget_minutes,
            used_minutes,
            reset_at,
            quiet_hours_json,
            status,
            notes,
            created_at,
            updated_at,
        ) = row
        return InterruptionBudget(
            budget_id=str(budget_id),
            principal_id=str(principal_id),
            scope=str(scope),
            window_kind=str(window_kind or "daily"),
            budget_minutes=max(0, int(budget_minutes or 0)),
            used_minutes=max(0, int(used_minutes or 0)),
            reset_at=_to_iso(reset_at) if reset_at else None,
            quiet_hours_json=dict(quiet_hours_json or {}),
            status=str(status or "active"),
            notes=str(notes or ""),
            created_at=_to_iso(created_at),
            updated_at=_to_iso(updated_at),
        )

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
        row = InterruptionBudget(
            budget_id=str(budget_id or "").strip() or str(uuid.uuid4()),
            principal_id=str(principal_id or "").strip(),
            scope=str(scope or "").strip(),
            window_kind=str(window_kind or "daily").strip() or "daily",
            budget_minutes=max(0, int(budget_minutes or 0)),
            used_minutes=max(0, int(used_minutes or 0)),
            reset_at=str(reset_at or "").strip() or None,
            quiet_hours_json=dict(quiet_hours_json or {}),
            status=_normalize_status(status),
            notes=str(notes or "").strip(),
            created_at=now_utc_iso(),
            updated_at=now_utc_iso(),
        )
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO interruption_budgets
                    (budget_id, principal_id, scope, window_kind, budget_minutes, used_minutes, reset_at, quiet_hours_json, status, notes, created_at, updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (budget_id) DO UPDATE
                    SET principal_id = EXCLUDED.principal_id,
                        scope = EXCLUDED.scope,
                        window_kind = EXCLUDED.window_kind,
                        budget_minutes = EXCLUDED.budget_minutes,
                        used_minutes = EXCLUDED.used_minutes,
                        reset_at = EXCLUDED.reset_at,
                        quiet_hours_json = EXCLUDED.quiet_hours_json,
                        status = EXCLUDED.status,
                        notes = EXCLUDED.notes,
                        updated_at = EXCLUDED.updated_at
                    RETURNING budget_id, principal_id, scope, window_kind, budget_minutes, used_minutes, reset_at, quiet_hours_json, status, notes, created_at, updated_at
                    """,
                    (
                        row.budget_id,
                        row.principal_id,
                        row.scope,
                        row.window_kind,
                        row.budget_minutes,
                        row.used_minutes,
                        row.reset_at,
                        self._json_value(row.quiet_hours_json),
                        row.status,
                        row.notes,
                        row.created_at,
                        row.updated_at,
                    ),
                )
                out = cur.fetchone()
        if not out:
            return row
        return self._from_row(out)

    def get(self, budget_id: str) -> InterruptionBudget | None:
        key = str(budget_id or "")
        if not key:
            return None
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT budget_id, principal_id, scope, window_kind, budget_minutes, used_minutes, reset_at, quiet_hours_json, status, notes, created_at, updated_at
                    FROM interruption_budgets
                    WHERE budget_id = %s
                    """,
                    (key,),
                )
                row = cur.fetchone()
        if not row:
            return None
        return self._from_row(row)

    def list_budgets(
        self,
        *,
        principal_id: str | None = None,
        limit: int = 100,
        status: str | None = None,
    ) -> list[InterruptionBudget]:
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
            "SELECT budget_id, principal_id, scope, window_kind, budget_minutes, used_minutes, reset_at, quiet_hours_json, status, notes, created_at, updated_at "
            "FROM interruption_budgets "
            f"{where} "
            "ORDER BY updated_at DESC, budget_id DESC LIMIT %s"
        )
        params.append(n)
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(query, tuple(params))
                rows = cur.fetchall()
        return [self._from_row(row) for row in rows]
