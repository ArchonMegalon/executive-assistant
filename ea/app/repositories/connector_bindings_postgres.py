from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from app.domain.models import ConnectorBinding, now_utc_iso


def _to_iso(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value or "")


class PostgresConnectorBindingRepository:
    def __init__(self, database_url: str) -> None:
        self._database_url = str(database_url or "").strip()
        if not self._database_url:
            raise ValueError("database_url is required for PostgresConnectorBindingRepository")
        self._ensure_schema()

    def _connect(self):  # type: ignore[no-untyped-def]
        try:
            import psycopg
        except Exception as exc:  # pragma: no cover - import guard
            raise RuntimeError("psycopg is required for postgres connector backend") from exc
        return psycopg.connect(self._database_url, autocommit=True)

    def _json_value(self, value: Any):  # type: ignore[no-untyped-def]
        from psycopg.types.json import Json

        return Json(value)

    def _ensure_schema(self) -> None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS connector_bindings (
                        binding_id TEXT PRIMARY KEY,
                        principal_id TEXT NOT NULL,
                        connector_name TEXT NOT NULL,
                        external_account_ref TEXT NOT NULL,
                        scope_json JSONB NOT NULL,
                        auth_metadata_json JSONB NOT NULL,
                        status TEXT NOT NULL,
                        created_at TIMESTAMPTZ NOT NULL,
                        updated_at TIMESTAMPTZ NOT NULL
                    )
                    """
                )
                cur.execute(
                    """
                    CREATE UNIQUE INDEX IF NOT EXISTS idx_connector_bindings_natural_key
                    ON connector_bindings(principal_id, connector_name, external_account_ref)
                    """
                )
                cur.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_connector_bindings_principal_updated
                    ON connector_bindings(principal_id, updated_at DESC)
                    """
                )

    def _from_row(self, row: tuple[Any, ...]) -> ConnectorBinding:
        (
            binding_id,
            principal_id,
            connector_name,
            external_account_ref,
            scope_json,
            auth_metadata_json,
            status,
            created_at,
            updated_at,
        ) = row
        return ConnectorBinding(
            binding_id=str(binding_id),
            principal_id=str(principal_id),
            connector_name=str(connector_name),
            external_account_ref=str(external_account_ref),
            scope_json=dict(scope_json or {}),
            auth_metadata_json=dict(auth_metadata_json or {}),
            status=str(status),
            created_at=_to_iso(created_at),
            updated_at=_to_iso(updated_at),
        )

    def upsert(
        self,
        principal_id: str,
        connector_name: str,
        external_account_ref: str,
        *,
        scope_json: dict[str, object] | None = None,
        auth_metadata_json: dict[str, object] | None = None,
        status: str = "enabled",
    ) -> ConnectorBinding:
        principal = str(principal_id or "").strip()
        connector = str(connector_name or "").strip()
        account_ref = str(external_account_ref or "").strip()
        if not principal or not connector or not account_ref:
            raise ValueError("principal_id, connector_name, and external_account_ref are required")
        now = now_utc_iso()
        row = ConnectorBinding(
            binding_id=str(uuid.uuid4()),
            principal_id=principal,
            connector_name=connector,
            external_account_ref=account_ref,
            scope_json=dict(scope_json or {}),
            auth_metadata_json=dict(auth_metadata_json or {}),
            status=str(status or "enabled"),
            created_at=now,
            updated_at=now,
        )
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO connector_bindings
                    (binding_id, principal_id, connector_name, external_account_ref, scope_json, auth_metadata_json, status, created_at, updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (principal_id, connector_name, external_account_ref) DO UPDATE
                    SET scope_json = EXCLUDED.scope_json,
                        auth_metadata_json = EXCLUDED.auth_metadata_json,
                        status = EXCLUDED.status,
                        updated_at = EXCLUDED.updated_at
                    RETURNING binding_id, principal_id, connector_name, external_account_ref, scope_json, auth_metadata_json, status, created_at, updated_at
                    """,
                    (
                        row.binding_id,
                        row.principal_id,
                        row.connector_name,
                        row.external_account_ref,
                        self._json_value(row.scope_json),
                        self._json_value(row.auth_metadata_json),
                        row.status,
                        row.created_at,
                        row.updated_at,
                    ),
                )
                out = cur.fetchone()
        if not out:
            return row
        return self._from_row(out)

    def list_for_principal(self, principal_id: str, limit: int = 100) -> list[ConnectorBinding]:
        principal = str(principal_id or "").strip()
        if not principal:
            return []
        n = max(1, min(500, int(limit or 100)))
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT binding_id, principal_id, connector_name, external_account_ref, scope_json, auth_metadata_json, status, created_at, updated_at
                    FROM connector_bindings
                    WHERE principal_id = %s
                    ORDER BY updated_at DESC, binding_id DESC
                    LIMIT %s
                    """,
                    (principal, n),
                )
                rows = cur.fetchall()
        return [self._from_row(row) for row in rows]

    def list_for_connector(self, connector_name: str, limit: int = 100) -> list[ConnectorBinding]:
        normalized = str(connector_name or "").strip()
        if not normalized:
            return []
        n = max(1, min(500, int(limit or 100)))
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT binding_id, principal_id, connector_name, external_account_ref, scope_json, auth_metadata_json, status, created_at, updated_at
                    FROM connector_bindings
                    WHERE lower(connector_name) = lower(%s)
                    ORDER BY updated_at DESC, binding_id DESC
                    LIMIT %s
                    """,
                    (normalized, n),
                )
                rows = cur.fetchall()
        return [self._from_row(row) for row in rows]

    def get(self, binding_id: str) -> ConnectorBinding | None:
        bid = str(binding_id or "").strip()
        if not bid:
            return None
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT binding_id, principal_id, connector_name, external_account_ref, scope_json, auth_metadata_json, status, created_at, updated_at
                    FROM connector_bindings
                    WHERE binding_id = %s
                    """,
                    (bid,),
                )
                row = cur.fetchone()
        if not row:
            return None
        return self._from_row(row)

    def set_status(self, binding_id: str, status: str) -> ConnectorBinding | None:
        bid = str(binding_id or "").strip()
        if not bid:
            return None
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE connector_bindings
                    SET status = %s, updated_at = %s
                    WHERE binding_id = %s
                    RETURNING binding_id, principal_id, connector_name, external_account_ref, scope_json, auth_metadata_json, status, created_at, updated_at
                    """,
                    (str(status or "enabled"), now_utc_iso(), bid),
                )
                row = cur.fetchone()
        if not row:
            return None
        return self._from_row(row)
