from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from app.domain.models import FollowUpRule, now_utc_iso


def _to_iso(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value or "")


def _normalize_status(value: str) -> str:
    raw = str(value or "").strip().lower()
    if raw in {"active", "paused", "archived"}:
        return raw
    return "active"


class PostgresFollowUpRuleRepository:
    def __init__(self, database_url: str) -> None:
        self._database_url = str(database_url or "").strip()
        if not self._database_url:
            raise ValueError("database_url is required for PostgresFollowUpRuleRepository")
        self._ensure_schema()

    def _connect(self):  # type: ignore[no-untyped-def]
        try:
            import psycopg
        except Exception as exc:  # pragma: no cover - import guard
            raise RuntimeError("psycopg is required for postgres follow-up-rule backend") from exc
        return psycopg.connect(self._database_url, autocommit=True)

    def _json_value(self, value: Any):  # type: ignore[no-untyped-def]
        from psycopg.types.json import Json

        return Json(value)

    def _ensure_schema(self) -> None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS follow_up_rules (
                        rule_id TEXT PRIMARY KEY,
                        principal_id TEXT NOT NULL,
                        name TEXT NOT NULL,
                        trigger_kind TEXT NOT NULL,
                        channel_scope_json JSONB NOT NULL,
                        delay_minutes INTEGER NOT NULL,
                        max_attempts INTEGER NOT NULL,
                        escalation_policy TEXT NOT NULL,
                        conditions_json JSONB NOT NULL,
                        action_json JSONB NOT NULL,
                        status TEXT NOT NULL,
                        notes TEXT NOT NULL,
                        created_at TIMESTAMPTZ NOT NULL,
                        updated_at TIMESTAMPTZ NOT NULL
                    )
                    """
                )
                cur.execute(
                    "ALTER TABLE follow_up_rules ADD COLUMN IF NOT EXISTS channel_scope_json JSONB NOT NULL DEFAULT '[]'::jsonb"
                )
                cur.execute(
                    "ALTER TABLE follow_up_rules ADD COLUMN IF NOT EXISTS delay_minutes INTEGER NOT NULL DEFAULT 60"
                )
                cur.execute(
                    "ALTER TABLE follow_up_rules ADD COLUMN IF NOT EXISTS max_attempts INTEGER NOT NULL DEFAULT 3"
                )
                cur.execute(
                    "ALTER TABLE follow_up_rules ADD COLUMN IF NOT EXISTS escalation_policy TEXT NOT NULL DEFAULT 'notify_exec'"
                )
                cur.execute(
                    "ALTER TABLE follow_up_rules ADD COLUMN IF NOT EXISTS conditions_json JSONB NOT NULL DEFAULT '{}'::jsonb"
                )
                cur.execute(
                    "ALTER TABLE follow_up_rules ADD COLUMN IF NOT EXISTS action_json JSONB NOT NULL DEFAULT '{}'::jsonb"
                )
                cur.execute("ALTER TABLE follow_up_rules ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'active'")
                cur.execute("ALTER TABLE follow_up_rules ADD COLUMN IF NOT EXISTS notes TEXT NOT NULL DEFAULT ''")
                cur.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_follow_up_rules_principal_status
                    ON follow_up_rules(principal_id, status, updated_at DESC)
                    """
                )
                cur.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_follow_up_rules_principal_trigger
                    ON follow_up_rules(principal_id, trigger_kind)
                    """
                )

    def _from_row(self, row: tuple[Any, ...]) -> FollowUpRule:
        (
            rule_id,
            principal_id,
            name,
            trigger_kind,
            channel_scope_json,
            delay_minutes,
            max_attempts,
            escalation_policy,
            conditions_json,
            action_json,
            status,
            notes,
            created_at,
            updated_at,
        ) = row
        return FollowUpRule(
            rule_id=str(rule_id),
            principal_id=str(principal_id),
            name=str(name),
            trigger_kind=str(trigger_kind),
            channel_scope=tuple(str(v).strip() for v in (channel_scope_json or []) if str(v).strip()),
            delay_minutes=max(0, int(delay_minutes or 0)),
            max_attempts=max(1, int(max_attempts or 1)),
            escalation_policy=str(escalation_policy or "notify_exec"),
            conditions_json=dict(conditions_json or {}),
            action_json=dict(action_json or {}),
            status=str(status or "active"),
            notes=str(notes or ""),
            created_at=_to_iso(created_at),
            updated_at=_to_iso(updated_at),
        )

    def upsert_rule(
        self,
        *,
        principal_id: str,
        name: str,
        trigger_kind: str,
        channel_scope: tuple[str, ...] = (),
        delay_minutes: int = 60,
        max_attempts: int = 3,
        escalation_policy: str = "notify_exec",
        conditions_json: dict[str, object] | None = None,
        action_json: dict[str, object] | None = None,
        status: str = "active",
        notes: str = "",
        rule_id: str | None = None,
    ) -> FollowUpRule:
        row = FollowUpRule(
            rule_id=str(rule_id or "").strip() or str(uuid.uuid4()),
            principal_id=str(principal_id or "").strip(),
            name=str(name or "").strip(),
            trigger_kind=str(trigger_kind or "").strip(),
            channel_scope=tuple(str(v).strip() for v in (channel_scope or ()) if str(v).strip()),
            delay_minutes=max(0, int(delay_minutes or 0)),
            max_attempts=max(1, int(max_attempts or 1)),
            escalation_policy=str(escalation_policy or "notify_exec").strip() or "notify_exec",
            conditions_json=dict(conditions_json or {}),
            action_json=dict(action_json or {}),
            status=_normalize_status(status),
            notes=str(notes or "").strip(),
            created_at=now_utc_iso(),
            updated_at=now_utc_iso(),
        )
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO follow_up_rules
                    (rule_id, principal_id, name, trigger_kind, channel_scope_json, delay_minutes, max_attempts, escalation_policy, conditions_json, action_json, status, notes, created_at, updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (rule_id) DO UPDATE
                    SET principal_id = EXCLUDED.principal_id,
                        name = EXCLUDED.name,
                        trigger_kind = EXCLUDED.trigger_kind,
                        channel_scope_json = EXCLUDED.channel_scope_json,
                        delay_minutes = EXCLUDED.delay_minutes,
                        max_attempts = EXCLUDED.max_attempts,
                        escalation_policy = EXCLUDED.escalation_policy,
                        conditions_json = EXCLUDED.conditions_json,
                        action_json = EXCLUDED.action_json,
                        status = EXCLUDED.status,
                        notes = EXCLUDED.notes,
                        updated_at = EXCLUDED.updated_at
                    RETURNING rule_id, principal_id, name, trigger_kind, channel_scope_json, delay_minutes, max_attempts, escalation_policy, conditions_json, action_json, status, notes, created_at, updated_at
                    """,
                    (
                        row.rule_id,
                        row.principal_id,
                        row.name,
                        row.trigger_kind,
                        self._json_value(list(row.channel_scope)),
                        row.delay_minutes,
                        row.max_attempts,
                        row.escalation_policy,
                        self._json_value(row.conditions_json),
                        self._json_value(row.action_json),
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

    def get(self, rule_id: str) -> FollowUpRule | None:
        key = str(rule_id or "")
        if not key:
            return None
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT rule_id, principal_id, name, trigger_kind, channel_scope_json, delay_minutes, max_attempts, escalation_policy, conditions_json, action_json, status, notes, created_at, updated_at
                    FROM follow_up_rules
                    WHERE rule_id = %s
                    """,
                    (key,),
                )
                row = cur.fetchone()
        if not row:
            return None
        return self._from_row(row)

    def list_rules(
        self,
        *,
        principal_id: str,
        limit: int = 100,
        status: str | None = None,
    ) -> list[FollowUpRule]:
        principal = str(principal_id or "").strip()
        n = max(1, min(500, int(limit or 100)))
        status_filter = str(status or "").strip().lower()
        where = "WHERE principal_id = %s"
        params: list[object] = [principal]
        if status_filter:
            where += " AND status = %s"
            params.append(status_filter)
        query = (
            "SELECT rule_id, principal_id, name, trigger_kind, channel_scope_json, delay_minutes, max_attempts, escalation_policy, conditions_json, action_json, status, notes, created_at, updated_at "
            "FROM follow_up_rules "
            f"{where} "
            "ORDER BY updated_at DESC, rule_id DESC LIMIT %s"
        )
        params.append(n)
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(query, tuple(params))
                rows = cur.fetchall()
        return [self._from_row(row) for row in rows]
