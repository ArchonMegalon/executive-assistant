from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from app.domain.models import CommunicationPolicy, now_utc_iso


def _to_iso(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value or "")


def _normalize_status(value: str) -> str:
    raw = str(value or "").strip().lower()
    if raw in {"active", "paused", "archived"}:
        return raw
    return "active"


class PostgresCommunicationPolicyRepository:
    def __init__(self, database_url: str) -> None:
        self._database_url = str(database_url or "").strip()
        if not self._database_url:
            raise ValueError("database_url is required for PostgresCommunicationPolicyRepository")
        self._ensure_schema()

    def _connect(self):  # type: ignore[no-untyped-def]
        try:
            import psycopg
        except Exception as exc:  # pragma: no cover - import guard
            raise RuntimeError("psycopg is required for postgres communication-policy backend") from exc
        return psycopg.connect(self._database_url, autocommit=True)

    def _json_value(self, value: dict[str, Any]):  # type: ignore[no-untyped-def]
        from psycopg.types.json import Json

        return Json(value)

    def _ensure_schema(self) -> None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS communication_policies (
                        policy_id TEXT PRIMARY KEY,
                        principal_id TEXT NOT NULL,
                        scope TEXT NOT NULL,
                        preferred_channel TEXT NOT NULL,
                        tone TEXT NOT NULL,
                        max_length INTEGER NOT NULL,
                        quiet_hours_json JSONB NOT NULL,
                        escalation_json JSONB NOT NULL,
                        status TEXT NOT NULL,
                        notes TEXT NOT NULL,
                        created_at TIMESTAMPTZ NOT NULL,
                        updated_at TIMESTAMPTZ NOT NULL
                    )
                    """
                )
                cur.execute(
                    "ALTER TABLE communication_policies ADD COLUMN IF NOT EXISTS preferred_channel TEXT NOT NULL DEFAULT ''"
                )
                cur.execute("ALTER TABLE communication_policies ADD COLUMN IF NOT EXISTS tone TEXT NOT NULL DEFAULT 'neutral'")
                cur.execute(
                    "ALTER TABLE communication_policies ADD COLUMN IF NOT EXISTS max_length INTEGER NOT NULL DEFAULT 1200"
                )
                cur.execute(
                    "ALTER TABLE communication_policies ADD COLUMN IF NOT EXISTS quiet_hours_json JSONB NOT NULL DEFAULT '{}'::jsonb"
                )
                cur.execute(
                    "ALTER TABLE communication_policies ADD COLUMN IF NOT EXISTS escalation_json JSONB NOT NULL DEFAULT '{}'::jsonb"
                )
                cur.execute(
                    "ALTER TABLE communication_policies ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'active'"
                )
                cur.execute("ALTER TABLE communication_policies ADD COLUMN IF NOT EXISTS notes TEXT NOT NULL DEFAULT ''")
                cur.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_comm_policies_principal_status
                    ON communication_policies(principal_id, status, updated_at DESC)
                    """
                )
                cur.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_comm_policies_principal_scope
                    ON communication_policies(principal_id, scope)
                    """
                )

    def _from_row(self, row: tuple[Any, ...]) -> CommunicationPolicy:
        (
            policy_id,
            principal_id,
            scope,
            preferred_channel,
            tone,
            max_length,
            quiet_hours_json,
            escalation_json,
            status,
            notes,
            created_at,
            updated_at,
        ) = row
        return CommunicationPolicy(
            policy_id=str(policy_id),
            principal_id=str(principal_id),
            scope=str(scope),
            preferred_channel=str(preferred_channel or ""),
            tone=str(tone or "neutral"),
            max_length=max(1, int(max_length or 1200)),
            quiet_hours_json=dict(quiet_hours_json or {}),
            escalation_json=dict(escalation_json or {}),
            status=str(status or "active"),
            notes=str(notes or ""),
            created_at=_to_iso(created_at),
            updated_at=_to_iso(updated_at),
        )

    def upsert_policy(
        self,
        *,
        principal_id: str,
        scope: str,
        preferred_channel: str = "",
        tone: str = "neutral",
        max_length: int = 1200,
        quiet_hours_json: dict[str, object] | None = None,
        escalation_json: dict[str, object] | None = None,
        status: str = "active",
        notes: str = "",
        policy_id: str | None = None,
    ) -> CommunicationPolicy:
        row = CommunicationPolicy(
            policy_id=str(policy_id or "").strip() or str(uuid.uuid4()),
            principal_id=str(principal_id or "").strip(),
            scope=str(scope or "").strip(),
            preferred_channel=str(preferred_channel or "").strip(),
            tone=str(tone or "neutral").strip() or "neutral",
            max_length=max(1, int(max_length or 1200)),
            quiet_hours_json=dict(quiet_hours_json or {}),
            escalation_json=dict(escalation_json or {}),
            status=_normalize_status(status),
            notes=str(notes or "").strip(),
            created_at=now_utc_iso(),
            updated_at=now_utc_iso(),
        )
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO communication_policies
                    (policy_id, principal_id, scope, preferred_channel, tone, max_length, quiet_hours_json, escalation_json, status, notes, created_at, updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (policy_id) DO UPDATE
                    SET principal_id = EXCLUDED.principal_id,
                        scope = EXCLUDED.scope,
                        preferred_channel = EXCLUDED.preferred_channel,
                        tone = EXCLUDED.tone,
                        max_length = EXCLUDED.max_length,
                        quiet_hours_json = EXCLUDED.quiet_hours_json,
                        escalation_json = EXCLUDED.escalation_json,
                        status = EXCLUDED.status,
                        notes = EXCLUDED.notes,
                        updated_at = EXCLUDED.updated_at
                    WHERE communication_policies.principal_id = EXCLUDED.principal_id
                    RETURNING policy_id, principal_id, scope, preferred_channel, tone, max_length, quiet_hours_json, escalation_json, status, notes, created_at, updated_at
                    """,
                    (
                        row.policy_id,
                        row.principal_id,
                        row.scope,
                        row.preferred_channel,
                        row.tone,
                        row.max_length,
                        self._json_value(row.quiet_hours_json),
                        self._json_value(row.escalation_json),
                        row.status,
                        row.notes,
                        row.created_at,
                        row.updated_at,
                    ),
                )
                out = cur.fetchone()
        if not out:
            raise PermissionError("principal_scope_mismatch")
        return self._from_row(out)

    def get(self, policy_id: str) -> CommunicationPolicy | None:
        key = str(policy_id or "")
        if not key:
            return None
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT policy_id, principal_id, scope, preferred_channel, tone, max_length, quiet_hours_json, escalation_json, status, notes, created_at, updated_at
                    FROM communication_policies
                    WHERE policy_id = %s
                    """,
                    (key,),
                )
                row = cur.fetchone()
        if not row:
            return None
        return self._from_row(row)

    def list_policies(
        self,
        *,
        principal_id: str,
        limit: int = 100,
        status: str | None = None,
    ) -> list[CommunicationPolicy]:
        principal = str(principal_id or "").strip()
        n = max(1, min(500, int(limit or 100)))
        status_filter = str(status or "").strip().lower()
        where = "WHERE principal_id = %s"
        params: list[object] = [principal]
        if status_filter:
            where += " AND status = %s"
            params.append(status_filter)
        query = (
            "SELECT policy_id, principal_id, scope, preferred_channel, tone, max_length, quiet_hours_json, escalation_json, status, notes, created_at, updated_at "
            "FROM communication_policies "
            f"{where} "
            "ORDER BY updated_at DESC, policy_id DESC LIMIT %s"
        )
        params.append(n)
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(query, tuple(params))
                rows = cur.fetchall()
        return [self._from_row(row) for row in rows]
