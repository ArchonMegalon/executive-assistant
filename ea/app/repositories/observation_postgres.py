from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from app.domain.models import ObservationEvent, now_utc_iso


def _to_iso(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value or "")


class PostgresObservationEventRepository:
    def __init__(self, database_url: str) -> None:
        self._database_url = str(database_url or "").strip()
        if not self._database_url:
            raise ValueError("database_url is required for PostgresObservationEventRepository")
        self._ensure_schema()

    def _connect(self):  # type: ignore[no-untyped-def]
        try:
            import psycopg
        except Exception as exc:  # pragma: no cover - import guard
            raise RuntimeError("psycopg is required for postgres backend") from exc
        return psycopg.connect(self._database_url, autocommit=True)

    def _json_value(self, value: dict[str, Any]):  # type: ignore[no-untyped-def]
        from psycopg.types.json import Json

        return Json(value)

    def _ensure_schema(self) -> None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS observation_events (
                        observation_id TEXT PRIMARY KEY,
                        principal_id TEXT NOT NULL,
                        channel TEXT NOT NULL,
                        event_type TEXT NOT NULL,
                        payload_json JSONB NOT NULL,
                        created_at TIMESTAMPTZ NOT NULL,
                        source_id TEXT NOT NULL DEFAULT '',
                        external_id TEXT NOT NULL DEFAULT '',
                        dedupe_key TEXT NOT NULL DEFAULT '',
                        auth_context_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                        raw_payload_uri TEXT NOT NULL DEFAULT ''
                    )
                    """
                )
                cur.execute("ALTER TABLE observation_events ADD COLUMN IF NOT EXISTS source_id TEXT NOT NULL DEFAULT ''")
                cur.execute("ALTER TABLE observation_events ADD COLUMN IF NOT EXISTS external_id TEXT NOT NULL DEFAULT ''")
                cur.execute("ALTER TABLE observation_events ADD COLUMN IF NOT EXISTS dedupe_key TEXT NOT NULL DEFAULT ''")
                cur.execute(
                    "ALTER TABLE observation_events ADD COLUMN IF NOT EXISTS auth_context_json JSONB NOT NULL DEFAULT '{}'::jsonb"
                )
                cur.execute("ALTER TABLE observation_events ADD COLUMN IF NOT EXISTS raw_payload_uri TEXT NOT NULL DEFAULT ''")
                cur.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_observation_events_created
                    ON observation_events(created_at DESC)
                    """
                )
                cur.execute(
                    """
                    CREATE UNIQUE INDEX IF NOT EXISTS idx_observation_events_dedupe_key_unique
                    ON observation_events(dedupe_key)
                    WHERE dedupe_key <> ''
                    """
                )
                cur.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_observation_events_source_external
                    ON observation_events(source_id, external_id, created_at DESC)
                    """
                )

    def append(
        self,
        principal_id: str,
        channel: str,
        event_type: str,
        payload: dict[str, object] | None = None,
        *,
        source_id: str = "",
        external_id: str = "",
        dedupe_key: str = "",
        auth_context_json: dict[str, object] | None = None,
        raw_payload_uri: str = "",
    ) -> ObservationEvent:
        dedupe = str(dedupe_key or "").strip()
        if dedupe:
            with self._connect() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT observation_id, principal_id, channel, event_type, payload_json, created_at,
                               source_id, external_id, dedupe_key, auth_context_json, raw_payload_uri
                        FROM observation_events
                        WHERE dedupe_key = %s
                        LIMIT 1
                        """,
                        (dedupe,),
                    )
                    found = cur.fetchone()
            if found:
                (
                    observation_id,
                    found_principal,
                    found_channel,
                    found_event_type,
                    payload_json,
                    created_at,
                    found_source,
                    found_external,
                    found_dedupe,
                    found_auth_context,
                    found_raw_uri,
                ) = found
                return ObservationEvent(
                    observation_id=str(observation_id),
                    principal_id=str(found_principal),
                    channel=str(found_channel),
                    event_type=str(found_event_type),
                    payload=dict(payload_json or {}),
                    created_at=_to_iso(created_at),
                    source_id=str(found_source or ""),
                    external_id=str(found_external or ""),
                    dedupe_key=str(found_dedupe or ""),
                    auth_context_json=dict(found_auth_context or {}),
                    raw_payload_uri=str(found_raw_uri or ""),
                )
        row = ObservationEvent(
            observation_id=str(uuid.uuid4()),
            principal_id=str(principal_id or "").strip(),
            channel=str(channel or "unknown").strip(),
            event_type=str(event_type or "unknown").strip(),
            payload=dict(payload or {}),
            created_at=now_utc_iso(),
            source_id=str(source_id or "").strip(),
            external_id=str(external_id or "").strip(),
            dedupe_key=dedupe,
            auth_context_json=dict(auth_context_json or {}),
            raw_payload_uri=str(raw_payload_uri or "").strip(),
        )
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO observation_events
                    (observation_id, principal_id, channel, event_type, payload_json, created_at,
                     source_id, external_id, dedupe_key, auth_context_json, raw_payload_uri)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        row.observation_id,
                        row.principal_id,
                        row.channel,
                        row.event_type,
                        self._json_value(row.payload),
                        row.created_at,
                        row.source_id,
                        row.external_id,
                        row.dedupe_key,
                        self._json_value(row.auth_context_json),
                        row.raw_payload_uri,
                    ),
                )
        return row

    def list_recent(self, limit: int = 50) -> list[ObservationEvent]:
        n = max(1, min(500, int(limit or 50)))
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT observation_id, principal_id, channel, event_type, payload_json, created_at,
                           source_id, external_id, dedupe_key, auth_context_json, raw_payload_uri
                    FROM observation_events
                    ORDER BY created_at DESC, observation_id DESC
                    LIMIT %s
                    """,
                    (n,),
                )
                rows = cur.fetchall()
        return [
            ObservationEvent(
                observation_id=str(observation_id),
                principal_id=str(principal_id),
                channel=str(channel),
                event_type=str(event_type),
                payload=dict(payload_json or {}),
                created_at=_to_iso(created_at),
                source_id=str(source_id or ""),
                external_id=str(external_id or ""),
                dedupe_key=str(dedupe_key or ""),
                auth_context_json=dict(auth_context_json or {}),
                raw_payload_uri=str(raw_payload_uri or ""),
            )
            for (
                observation_id,
                principal_id,
                channel,
                event_type,
                payload_json,
                created_at,
                source_id,
                external_id,
                dedupe_key,
                auth_context_json,
                raw_payload_uri,
            ) in rows
        ]

    def get_by_dedupe(self, dedupe_key: str) -> ObservationEvent | None:
        key = str(dedupe_key or "").strip()
        if not key:
            return None
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT observation_id, principal_id, channel, event_type, payload_json, created_at,
                           source_id, external_id, dedupe_key, auth_context_json, raw_payload_uri
                    FROM observation_events
                    WHERE dedupe_key = %s
                    LIMIT 1
                    """,
                    (key,),
                )
                row = cur.fetchone()
        if not row:
            return None
        (
            observation_id,
            principal_id,
            channel,
            event_type,
            payload_json,
            created_at,
            source_id,
            external_id,
            found_dedupe_key,
            auth_context_json,
            raw_payload_uri,
        ) = row
        return ObservationEvent(
            observation_id=str(observation_id),
            principal_id=str(principal_id),
            channel=str(channel),
            event_type=str(event_type),
            payload=dict(payload_json or {}),
            created_at=_to_iso(created_at),
            source_id=str(source_id or ""),
            external_id=str(external_id or ""),
            dedupe_key=str(found_dedupe_key or ""),
            auth_context_json=dict(auth_context_json or {}),
            raw_payload_uri=str(raw_payload_uri or ""),
        )

    def count_recent_for_principal(self, principal_id: str, *, since: str) -> int:
        principal = str(principal_id or "").strip()
        cutoff = str(since or "").strip()
        if not principal or not cutoff:
            return 0
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT COUNT(*)
                    FROM observation_events
                    WHERE principal_id = %s
                      AND created_at >= %s
                    """,
                    (principal, cutoff),
                )
                row = cur.fetchone()
        return int(row[0] or 0) if row else 0
