from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from app.domain.models import OperatorProfile, now_utc_iso


def _to_iso(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value or "")


def _normalize_status(value: str) -> str:
    raw = str(value or "").strip().lower()
    if raw in {"active", "inactive", "archived"}:
        return raw
    return "active"


class PostgresOperatorProfileRepository:
    def __init__(self, database_url: str) -> None:
        self._database_url = str(database_url or "").strip()
        if not self._database_url:
            raise ValueError("database_url is required for PostgresOperatorProfileRepository")
        self._ensure_schema()

    def _connect(self):  # type: ignore[no-untyped-def]
        try:
            import psycopg
        except Exception as exc:  # pragma: no cover
            raise RuntimeError("psycopg is required for postgres operator-profile backend") from exc
        return psycopg.connect(self._database_url, autocommit=True)

    def _json_value(self, value: list[str]):  # type: ignore[no-untyped-def]
        from psycopg.types.json import Json

        return Json(value)

    def _ensure_schema(self) -> None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS operator_profiles (
                        principal_id TEXT NOT NULL,
                        operator_id TEXT NOT NULL,
                        display_name TEXT NOT NULL,
                        roles_json JSONB NOT NULL DEFAULT '[]'::jsonb,
                        skill_tags_json JSONB NOT NULL DEFAULT '[]'::jsonb,
                        trust_tier TEXT NOT NULL DEFAULT 'standard',
                        status TEXT NOT NULL DEFAULT 'active',
                        notes TEXT NOT NULL DEFAULT '',
                        created_at TIMESTAMPTZ NOT NULL,
                        updated_at TIMESTAMPTZ NOT NULL
                    )
                    """
                )
                cur.execute("ALTER TABLE operator_profiles DROP CONSTRAINT IF EXISTS operator_profiles_pkey")
                cur.execute(
                    """
                    CREATE UNIQUE INDEX IF NOT EXISTS idx_operator_profiles_principal_operator
                    ON operator_profiles(principal_id, operator_id)
                    """
                )
                cur.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_operator_profiles_principal_status
                    ON operator_profiles(principal_id, status, updated_at DESC)
                    """
                )

    def _from_row(self, row: tuple[Any, ...]) -> OperatorProfile:
        (
            operator_id,
            principal_id,
            display_name,
            roles_json,
            skill_tags_json,
            trust_tier,
            status,
            notes,
            created_at,
            updated_at,
        ) = row
        return OperatorProfile(
            operator_id=str(operator_id),
            principal_id=str(principal_id),
            display_name=str(display_name),
            roles=tuple(str(v).strip() for v in (roles_json or []) if str(v).strip()),
            skill_tags=tuple(str(v).strip().lower() for v in (skill_tags_json or []) if str(v).strip()),
            trust_tier=str(trust_tier or "standard"),
            status=str(status or "active"),
            notes=str(notes or ""),
            created_at=_to_iso(created_at),
            updated_at=_to_iso(updated_at),
        )

    def upsert_profile(
        self,
        *,
        principal_id: str,
        operator_id: str | None = None,
        display_name: str,
        roles: tuple[str, ...] = (),
        skill_tags: tuple[str, ...] = (),
        trust_tier: str = "standard",
        status: str = "active",
        notes: str = "",
    ) -> OperatorProfile:
        normalized_principal = str(principal_id or "").strip()
        normalized_operator_id = str(operator_id or "").strip()
        row = OperatorProfile(
            operator_id=normalized_operator_id or str(uuid.uuid4()),
            principal_id=normalized_principal,
            display_name=str(display_name or "").strip(),
            roles=tuple(str(v).strip() for v in roles if str(v).strip()),
            skill_tags=tuple(str(v).strip().lower() for v in skill_tags if str(v).strip()),
            trust_tier=str(trust_tier or "standard").strip() or "standard",
            status=_normalize_status(status),
            notes=str(notes or "").strip(),
            created_at=now_utc_iso(),
            updated_at=now_utc_iso(),
        )
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO operator_profiles
                    (operator_id, principal_id, display_name, roles_json, skill_tags_json, trust_tier, status, notes, created_at, updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (principal_id, operator_id) DO UPDATE
                    SET display_name = EXCLUDED.display_name,
                        roles_json = EXCLUDED.roles_json,
                        skill_tags_json = EXCLUDED.skill_tags_json,
                        trust_tier = EXCLUDED.trust_tier,
                        status = EXCLUDED.status,
                        notes = EXCLUDED.notes,
                        updated_at = EXCLUDED.updated_at
                    RETURNING operator_id, principal_id, display_name, roles_json, skill_tags_json, trust_tier, status, notes, created_at, updated_at
                    """,
                    (
                        row.operator_id,
                        row.principal_id,
                        row.display_name,
                        self._json_value(list(row.roles)),
                        self._json_value(list(row.skill_tags)),
                        row.trust_tier,
                        row.status,
                        row.notes,
                        row.created_at,
                        row.updated_at,
                    ),
                )
                out = cur.fetchone()
        return self._from_row(out) if out else row

    def get(self, operator_id: str, *, principal_id: str | None = None) -> OperatorProfile | None:
        key = str(operator_id or "").strip()
        if not key:
            return None
        with self._connect() as conn:
            with conn.cursor() as cur:
                if str(principal_id or "").strip():
                    cur.execute(
                        """
                        SELECT operator_id, principal_id, display_name, roles_json, skill_tags_json, trust_tier, status, notes, created_at, updated_at
                        FROM operator_profiles
                        WHERE operator_id = %s AND principal_id = %s
                        """,
                        (key, str(principal_id or "").strip()),
                    )
                    row = cur.fetchone()
                    return self._from_row(row) if row else None
                cur.execute(
                    """
                    SELECT operator_id, principal_id, display_name, roles_json, skill_tags_json, trust_tier, status, notes, created_at, updated_at
                    FROM operator_profiles
                    WHERE operator_id = %s
                    ORDER BY principal_id ASC
                    LIMIT 2
                    """,
                    (key,),
                )
                rows = cur.fetchall()
        if len(rows) == 1:
            return self._from_row(rows[0])
        return None

    def list_for_principal(
        self,
        *,
        principal_id: str,
        status: str | None = None,
        limit: int = 100,
    ) -> list[OperatorProfile]:
        principal = str(principal_id or "").strip()
        status_filter = str(status or "").strip().lower()
        n = max(1, min(500, int(limit or 100)))
        clauses = ["principal_id = %s"]
        params: list[object] = [principal]
        if status_filter:
            clauses.append("status = %s")
            params.append(status_filter)
        params.append(n)
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT operator_id, principal_id, display_name, roles_json, skill_tags_json, trust_tier, status, notes, created_at, updated_at
                    FROM operator_profiles
                    WHERE {' AND '.join(clauses)}
                    ORDER BY updated_at DESC, operator_id DESC
                    LIMIT %s
                    """,
                    tuple(params),
                )
                rows = cur.fetchall()
        return [self._from_row(row) for row in rows]
