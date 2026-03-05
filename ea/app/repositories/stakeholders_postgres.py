from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from app.domain.models import Stakeholder, now_utc_iso


def _to_iso(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value or "")


def _normalize_status(value: str) -> str:
    raw = str(value or "").strip().lower()
    if raw in {"active", "archived", "inactive"}:
        return raw
    return "active"


class PostgresStakeholderRepository:
    def __init__(self, database_url: str) -> None:
        self._database_url = str(database_url or "").strip()
        if not self._database_url:
            raise ValueError("database_url is required for PostgresStakeholderRepository")
        self._ensure_schema()

    def _connect(self):  # type: ignore[no-untyped-def]
        try:
            import psycopg
        except Exception as exc:  # pragma: no cover - import guard
            raise RuntimeError("psycopg is required for postgres stakeholder backend") from exc
        return psycopg.connect(self._database_url, autocommit=True)

    def _json_value(self, value: dict[str, Any]):  # type: ignore[no-untyped-def]
        from psycopg.types.json import Json

        return Json(value)

    def _ensure_schema(self) -> None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS stakeholders (
                        stakeholder_id TEXT PRIMARY KEY,
                        principal_id TEXT NOT NULL,
                        display_name TEXT NOT NULL,
                        channel_ref TEXT NOT NULL,
                        authority_level TEXT NOT NULL,
                        importance TEXT NOT NULL,
                        response_cadence TEXT NOT NULL,
                        tone_pref TEXT NOT NULL,
                        sensitivity TEXT NOT NULL,
                        escalation_policy TEXT NOT NULL,
                        open_loops_json JSONB NOT NULL,
                        friction_points_json JSONB NOT NULL,
                        last_interaction_at TIMESTAMPTZ NULL,
                        status TEXT NOT NULL,
                        notes TEXT NOT NULL,
                        created_at TIMESTAMPTZ NOT NULL,
                        updated_at TIMESTAMPTZ NOT NULL
                    )
                    """
                )
                cur.execute("ALTER TABLE stakeholders ADD COLUMN IF NOT EXISTS channel_ref TEXT NOT NULL DEFAULT ''")
                cur.execute(
                    "ALTER TABLE stakeholders ADD COLUMN IF NOT EXISTS authority_level TEXT NOT NULL DEFAULT 'manager'"
                )
                cur.execute("ALTER TABLE stakeholders ADD COLUMN IF NOT EXISTS importance TEXT NOT NULL DEFAULT 'medium'")
                cur.execute(
                    "ALTER TABLE stakeholders ADD COLUMN IF NOT EXISTS response_cadence TEXT NOT NULL DEFAULT 'normal'"
                )
                cur.execute("ALTER TABLE stakeholders ADD COLUMN IF NOT EXISTS tone_pref TEXT NOT NULL DEFAULT 'neutral'")
                cur.execute(
                    "ALTER TABLE stakeholders ADD COLUMN IF NOT EXISTS sensitivity TEXT NOT NULL DEFAULT 'internal'"
                )
                cur.execute(
                    "ALTER TABLE stakeholders ADD COLUMN IF NOT EXISTS escalation_policy TEXT NOT NULL DEFAULT 'none'"
                )
                cur.execute(
                    "ALTER TABLE stakeholders ADD COLUMN IF NOT EXISTS open_loops_json JSONB NOT NULL DEFAULT '{}'::jsonb"
                )
                cur.execute(
                    "ALTER TABLE stakeholders ADD COLUMN IF NOT EXISTS friction_points_json JSONB NOT NULL DEFAULT '{}'::jsonb"
                )
                cur.execute("ALTER TABLE stakeholders ADD COLUMN IF NOT EXISTS last_interaction_at TIMESTAMPTZ NULL")
                cur.execute("ALTER TABLE stakeholders ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'active'")
                cur.execute("ALTER TABLE stakeholders ADD COLUMN IF NOT EXISTS notes TEXT NOT NULL DEFAULT ''")
                cur.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_stakeholders_principal_status
                    ON stakeholders(principal_id, status, updated_at DESC)
                    """
                )
                cur.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_stakeholders_principal_name
                    ON stakeholders(principal_id, display_name)
                    """
                )

    def _from_row(self, row: tuple[Any, ...]) -> Stakeholder:
        (
            stakeholder_id,
            principal_id,
            display_name,
            channel_ref,
            authority_level,
            importance,
            response_cadence,
            tone_pref,
            sensitivity,
            escalation_policy,
            open_loops_json,
            friction_points_json,
            last_interaction_at,
            status,
            notes,
            created_at,
            updated_at,
        ) = row
        return Stakeholder(
            stakeholder_id=str(stakeholder_id),
            principal_id=str(principal_id),
            display_name=str(display_name),
            channel_ref=str(channel_ref or ""),
            authority_level=str(authority_level or "manager"),
            importance=str(importance or "medium"),
            response_cadence=str(response_cadence or "normal"),
            tone_pref=str(tone_pref or "neutral"),
            sensitivity=str(sensitivity or "internal"),
            escalation_policy=str(escalation_policy or "none"),
            open_loops_json=dict(open_loops_json or {}),
            friction_points_json=dict(friction_points_json or {}),
            last_interaction_at=_to_iso(last_interaction_at) if last_interaction_at else None,
            status=str(status or "active"),
            notes=str(notes or ""),
            created_at=_to_iso(created_at),
            updated_at=_to_iso(updated_at),
        )

    def upsert_stakeholder(
        self,
        *,
        principal_id: str,
        display_name: str,
        channel_ref: str = "",
        authority_level: str = "manager",
        importance: str = "medium",
        response_cadence: str = "normal",
        tone_pref: str = "neutral",
        sensitivity: str = "internal",
        escalation_policy: str = "none",
        open_loops_json: dict[str, object] | None = None,
        friction_points_json: dict[str, object] | None = None,
        last_interaction_at: str | None = None,
        status: str = "active",
        notes: str = "",
        stakeholder_id: str | None = None,
    ) -> Stakeholder:
        row = Stakeholder(
            stakeholder_id=str(stakeholder_id or "").strip() or str(uuid.uuid4()),
            principal_id=str(principal_id or "").strip(),
            display_name=str(display_name or "").strip(),
            channel_ref=str(channel_ref or "").strip(),
            authority_level=str(authority_level or "manager").strip() or "manager",
            importance=str(importance or "medium").strip() or "medium",
            response_cadence=str(response_cadence or "normal").strip() or "normal",
            tone_pref=str(tone_pref or "neutral").strip() or "neutral",
            sensitivity=str(sensitivity or "internal").strip() or "internal",
            escalation_policy=str(escalation_policy or "none").strip() or "none",
            open_loops_json=dict(open_loops_json or {}),
            friction_points_json=dict(friction_points_json or {}),
            last_interaction_at=str(last_interaction_at or "").strip() or None,
            status=_normalize_status(status),
            notes=str(notes or "").strip(),
            created_at=now_utc_iso(),
            updated_at=now_utc_iso(),
        )
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO stakeholders
                    (stakeholder_id, principal_id, display_name, channel_ref, authority_level, importance, response_cadence, tone_pref,
                     sensitivity, escalation_policy, open_loops_json, friction_points_json, last_interaction_at, status, notes, created_at, updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (stakeholder_id) DO UPDATE
                    SET principal_id = EXCLUDED.principal_id,
                        display_name = EXCLUDED.display_name,
                        channel_ref = EXCLUDED.channel_ref,
                        authority_level = EXCLUDED.authority_level,
                        importance = EXCLUDED.importance,
                        response_cadence = EXCLUDED.response_cadence,
                        tone_pref = EXCLUDED.tone_pref,
                        sensitivity = EXCLUDED.sensitivity,
                        escalation_policy = EXCLUDED.escalation_policy,
                        open_loops_json = EXCLUDED.open_loops_json,
                        friction_points_json = EXCLUDED.friction_points_json,
                        last_interaction_at = EXCLUDED.last_interaction_at,
                        status = EXCLUDED.status,
                        notes = EXCLUDED.notes,
                        updated_at = EXCLUDED.updated_at
                    RETURNING stakeholder_id, principal_id, display_name, channel_ref, authority_level, importance, response_cadence, tone_pref,
                              sensitivity, escalation_policy, open_loops_json, friction_points_json, last_interaction_at, status, notes, created_at, updated_at
                    """,
                    (
                        row.stakeholder_id,
                        row.principal_id,
                        row.display_name,
                        row.channel_ref,
                        row.authority_level,
                        row.importance,
                        row.response_cadence,
                        row.tone_pref,
                        row.sensitivity,
                        row.escalation_policy,
                        self._json_value(row.open_loops_json),
                        self._json_value(row.friction_points_json),
                        row.last_interaction_at,
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

    def get(self, stakeholder_id: str) -> Stakeholder | None:
        key = str(stakeholder_id or "")
        if not key:
            return None
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT stakeholder_id, principal_id, display_name, channel_ref, authority_level, importance, response_cadence, tone_pref,
                           sensitivity, escalation_policy, open_loops_json, friction_points_json, last_interaction_at, status, notes, created_at, updated_at
                    FROM stakeholders
                    WHERE stakeholder_id = %s
                    """,
                    (key,),
                )
                row = cur.fetchone()
        if not row:
            return None
        return self._from_row(row)

    def list_stakeholders(
        self,
        *,
        principal_id: str,
        limit: int = 100,
        status: str | None = None,
    ) -> list[Stakeholder]:
        principal = str(principal_id or "").strip()
        n = max(1, min(500, int(limit or 100)))
        status_filter = str(status or "").strip().lower()
        where = "WHERE principal_id = %s"
        params: list[object] = [principal]
        if status_filter:
            where += " AND status = %s"
            params.append(status_filter)
        query = (
            "SELECT stakeholder_id, principal_id, display_name, channel_ref, authority_level, importance, response_cadence, tone_pref, "
            "sensitivity, escalation_policy, open_loops_json, friction_points_json, last_interaction_at, status, notes, created_at, updated_at "
            "FROM stakeholders "
            f"{where} "
            "ORDER BY updated_at DESC, stakeholder_id DESC LIMIT %s"
        )
        params.append(n)
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(query, tuple(params))
                rows = cur.fetchall()
        return [self._from_row(row) for row in rows]
