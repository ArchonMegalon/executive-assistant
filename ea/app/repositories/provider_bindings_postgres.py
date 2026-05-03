from __future__ import annotations

from datetime import datetime
from typing import Any

from app.domain.models import ProviderBindingRecord, now_utc_iso


def _to_iso(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value or "")


class PostgresProviderBindingRepository:
    def __init__(self, database_url: str) -> None:
        self._database_url = str(database_url or "").strip()
        if not self._database_url:
            raise ValueError("database_url is required for PostgresProviderBindingRepository")
        self._ensure_schema()

    def _connect(self):  # type: ignore[no-untyped-def]
        try:
            import psycopg
        except Exception as exc:  # pragma: no cover - import guard
            raise RuntimeError("psycopg is required for postgres provider-binding backend") from exc
        return psycopg.connect(self._database_url, autocommit=True)

    def _json_value(self, value: Any):  # type: ignore[no-untyped-def]
        from psycopg.types.json import Json

        return Json(value)

    def _ensure_schema(self) -> None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS provider_bindings (
                        binding_id TEXT PRIMARY KEY,
                        principal_id TEXT NOT NULL,
                        provider_key TEXT NOT NULL,
                        status TEXT NOT NULL,
                        priority INTEGER NOT NULL,
                        probe_state TEXT NOT NULL,
                        probe_details_json JSONB NOT NULL,
                        scope_json JSONB NOT NULL,
                        auth_metadata_json JSONB NOT NULL,
                        created_at TIMESTAMPTZ NOT NULL,
                        updated_at TIMESTAMPTZ NOT NULL
                    )
                    """
                )
                cur.execute(
                    """
                    DROP INDEX IF EXISTS idx_provider_bindings_principal_provider
                    """
                )
                cur.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_provider_bindings_principal_provider
                    ON provider_bindings(principal_id, provider_key, updated_at DESC)
                    """
                )
                cur.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_provider_bindings_principal_updated
                    ON provider_bindings(principal_id, updated_at DESC)
                    """
                )

    def _binding_id(self, *, principal_id: str, provider_key: str) -> str:
        return f"{principal_id}:{provider_key}"

    def _from_row(self, row: tuple[Any, ...]) -> ProviderBindingRecord:
        (
            binding_id,
            principal_id,
            provider_key,
            status,
            priority,
            probe_state,
            probe_details_json,
            scope_json,
            auth_metadata_json,
            created_at,
            updated_at,
        ) = row
        return ProviderBindingRecord(
            binding_id=str(binding_id),
            principal_id=str(principal_id),
            provider_key=str(provider_key),
            status=str(status),
            priority=int(priority),
            probe_state=str(probe_state),
            probe_details_json=dict(probe_details_json or {}),
            scope_json=dict(scope_json or {}),
            auth_metadata_json=dict(auth_metadata_json or {}),
            created_at=_to_iso(created_at),
            updated_at=_to_iso(updated_at),
        )

    def get(self, binding_id: str) -> ProviderBindingRecord | None:
        normalized_binding_id = str(binding_id or "").strip()
        if not normalized_binding_id:
            return None
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT binding_id, principal_id, provider_key, status, priority, probe_state,
                           probe_details_json, scope_json, auth_metadata_json, created_at, updated_at
                    FROM provider_bindings
                    WHERE binding_id = %s
                    """,
                    (normalized_binding_id,),
                )
                row = cur.fetchone()
        if row is None:
            return None
        return self._from_row(row)

    def get_for_provider(self, principal_id: str, provider_key: str) -> ProviderBindingRecord | None:
        normalized_principal = str(principal_id or "").strip()
        normalized_provider = str(provider_key or "").strip().lower()
        if not normalized_principal or not normalized_provider:
            return None
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT binding_id, principal_id, provider_key, status, priority, probe_state,
                           probe_details_json, scope_json, auth_metadata_json, created_at, updated_at
                    FROM provider_bindings
                    WHERE principal_id = %s AND provider_key = %s
                    """,
                    (normalized_principal, normalized_provider),
                )
                row = cur.fetchone()
        if row is None:
            return None
        return self._from_row(row)

    def list_for_principal(self, principal_id: str, limit: int = 100) -> list[ProviderBindingRecord]:
        normalized_principal = str(principal_id or "").strip()
        if not normalized_principal:
            return []
        bounded_limit = max(1, min(500, int(limit or 100)))
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT binding_id, principal_id, provider_key, status, priority, probe_state,
                           probe_details_json, scope_json, auth_metadata_json, created_at, updated_at
                    FROM provider_bindings
                    WHERE principal_id = %s
                    ORDER BY updated_at DESC, binding_id DESC
                    LIMIT %s
                    """,
                    (normalized_principal, bounded_limit),
                )
                rows = cur.fetchall()
        return [self._from_row(row) for row in rows]

    def upsert(
        self,
        *,
        binding_id: str | None = None,
        principal_id: str,
        provider_key: str,
        status: str,
        priority: int = 100,
        probe_state: str = "unknown",
        probe_details_json: dict[str, object] | None = None,
        scope_json: dict[str, object] | None = None,
        auth_metadata_json: dict[str, object] | None = None,
    ) -> ProviderBindingRecord:
        normalized_principal = str(principal_id or "").strip()
        normalized_provider = str(provider_key or "").strip().lower()
        if not normalized_principal:
            raise ValueError("principal_id_required")
        if not normalized_provider:
            raise ValueError("provider_key_required")
        timestamp = now_utc_iso()
        normalized_binding_id = str(binding_id or "").strip() or self._binding_id(
            principal_id=normalized_principal,
            provider_key=normalized_provider,
        )
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO provider_bindings (
                        binding_id,
                        principal_id,
                        provider_key,
                        status,
                        priority,
                        probe_state,
                        probe_details_json,
                        scope_json,
                        auth_metadata_json,
                        created_at,
                        updated_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (binding_id) DO UPDATE SET
                        status = EXCLUDED.status,
                        priority = EXCLUDED.priority,
                        probe_state = EXCLUDED.probe_state,
                        probe_details_json = EXCLUDED.probe_details_json,
                        scope_json = EXCLUDED.scope_json,
                        auth_metadata_json = EXCLUDED.auth_metadata_json,
                        updated_at = EXCLUDED.updated_at
                    RETURNING binding_id, principal_id, provider_key, status, priority, probe_state,
                              probe_details_json, scope_json, auth_metadata_json, created_at, updated_at
                    """,
                    (
                        normalized_binding_id,
                        normalized_principal,
                        normalized_provider,
                        str(status or "enabled").strip().lower() or "enabled",
                        int(priority or 100),
                        str(probe_state or "unknown").strip() or "unknown",
                        self._json_value(dict(probe_details_json or {})),
                        self._json_value(dict(scope_json or {})),
                        self._json_value(dict(auth_metadata_json or {})),
                        timestamp,
                        timestamp,
                    ),
                )
                row = cur.fetchone()
        if row is None:
            raise RuntimeError("provider_binding_upsert_failed")
        return self._from_row(row)

    def set_status(self, binding_id: str, status: str) -> ProviderBindingRecord | None:
        normalized_binding_id = str(binding_id or "").strip()
        if not normalized_binding_id:
            return None
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE provider_bindings
                    SET status = %s,
                        updated_at = %s
                    WHERE binding_id = %s
                    RETURNING binding_id, principal_id, provider_key, status, priority, probe_state,
                              probe_details_json, scope_json, auth_metadata_json, created_at, updated_at
                    """,
                    (
                        str(status or "enabled").strip().lower() or "enabled",
                        now_utc_iso(),
                        normalized_binding_id,
                    ),
                )
                row = cur.fetchone()
        if row is None:
            return None
        return self._from_row(row)

    def set_probe(
        self,
        binding_id: str,
        probe_state: str,
        probe_details_json: dict[str, object] | None = None,
    ) -> ProviderBindingRecord | None:
        normalized_binding_id = str(binding_id or "").strip()
        if not normalized_binding_id:
            return None
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE provider_bindings
                    SET probe_state = %s,
                        probe_details_json = %s,
                        updated_at = %s
                    WHERE binding_id = %s
                    RETURNING binding_id, principal_id, provider_key, status, priority, probe_state,
                              probe_details_json, scope_json, auth_metadata_json, created_at, updated_at
                    """,
                    (
                        str(probe_state or "unknown").strip() or "unknown",
                        self._json_value(dict(probe_details_json or {})),
                        now_utc_iso(),
                        normalized_binding_id,
                    ),
                )
                row = cur.fetchone()
        if row is None:
            return None
        return self._from_row(row)

    def delete(self, binding_id: str) -> ProviderBindingRecord | None:
        normalized_binding_id = str(binding_id or "").strip()
        if not normalized_binding_id:
            return None
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    DELETE FROM provider_bindings
                    WHERE binding_id = %s
                    RETURNING binding_id, principal_id, provider_key, status, priority, probe_state,
                              probe_details_json, scope_json, auth_metadata_json, created_at, updated_at
                    """,
                    (normalized_binding_id,),
                )
                row = cur.fetchone()
        if row is None:
            return None
        return self._from_row(row)
