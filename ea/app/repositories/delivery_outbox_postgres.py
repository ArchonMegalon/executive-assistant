from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from app.domain.models import DeliveryOutboxItem, now_utc_iso


def _to_iso(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value or "")


def _as_delivery(row: tuple[Any, ...]) -> DeliveryOutboxItem:
    (
        delivery_id,
        principal_id,
        channel,
        recipient,
        content,
        status,
        metadata_json,
        created_at,
        sent_at,
        idempotency_key,
        attempt_count,
        next_attempt_at,
        last_error,
        receipt_json,
        dead_lettered_at,
    ) = row
    return DeliveryOutboxItem(
        delivery_id=str(delivery_id),
        principal_id=str(principal_id or ""),
        channel=str(channel),
        recipient=str(recipient),
        content=str(content),
        status=str(status),
        metadata=dict(metadata_json or {}),
        created_at=_to_iso(created_at),
        sent_at=_to_iso(sent_at) if sent_at else None,
        idempotency_key=str(idempotency_key or ""),
        attempt_count=int(attempt_count or 0),
        next_attempt_at=_to_iso(next_attempt_at) if next_attempt_at else None,
        last_error=str(last_error or ""),
        receipt_json=dict(receipt_json or {}),
        dead_lettered_at=_to_iso(dead_lettered_at) if dead_lettered_at else None,
    )


class PostgresDeliveryOutboxRepository:
    def __init__(self, database_url: str) -> None:
        self._database_url = str(database_url or "").strip()
        if not self._database_url:
            raise ValueError("database_url is required for PostgresDeliveryOutboxRepository")
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
                    CREATE TABLE IF NOT EXISTS delivery_outbox (
                        delivery_id TEXT PRIMARY KEY,
                        principal_id TEXT NOT NULL DEFAULT '',
                        channel TEXT NOT NULL,
                        recipient TEXT NOT NULL,
                        content TEXT NOT NULL,
                        status TEXT NOT NULL,
                        metadata_json JSONB NOT NULL,
                        created_at TIMESTAMPTZ NOT NULL,
                        sent_at TIMESTAMPTZ NULL,
                        idempotency_key TEXT NOT NULL DEFAULT '',
                        attempt_count INT NOT NULL DEFAULT 0,
                        next_attempt_at TIMESTAMPTZ NULL,
                        last_error TEXT NOT NULL DEFAULT '',
                        receipt_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                        dead_lettered_at TIMESTAMPTZ NULL
                    )
                    """
                )
                cur.execute("ALTER TABLE delivery_outbox ADD COLUMN IF NOT EXISTS principal_id TEXT NOT NULL DEFAULT ''")
                cur.execute(
                    """
                    UPDATE delivery_outbox
                    SET principal_id = COALESCE(NULLIF(metadata_json->>'principal_id', ''), principal_id, '')
                    WHERE COALESCE(principal_id, '') = ''
                    """
                )
                cur.execute("ALTER TABLE delivery_outbox ADD COLUMN IF NOT EXISTS idempotency_key TEXT NOT NULL DEFAULT ''")
                cur.execute("ALTER TABLE delivery_outbox ADD COLUMN IF NOT EXISTS attempt_count INT NOT NULL DEFAULT 0")
                cur.execute("ALTER TABLE delivery_outbox ADD COLUMN IF NOT EXISTS next_attempt_at TIMESTAMPTZ NULL")
                cur.execute("ALTER TABLE delivery_outbox ADD COLUMN IF NOT EXISTS last_error TEXT NOT NULL DEFAULT ''")
                cur.execute(
                    "ALTER TABLE delivery_outbox ADD COLUMN IF NOT EXISTS receipt_json JSONB NOT NULL DEFAULT '{}'::jsonb"
                )
                cur.execute("ALTER TABLE delivery_outbox ADD COLUMN IF NOT EXISTS dead_lettered_at TIMESTAMPTZ NULL")
                cur.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_delivery_outbox_status_created
                    ON delivery_outbox(status, created_at DESC)
                    """
                )
                cur.execute("DROP INDEX IF EXISTS idx_delivery_outbox_idempotency_key_unique")
                cur.execute(
                    """
                    CREATE UNIQUE INDEX IF NOT EXISTS idx_delivery_outbox_principal_idempotency_unique
                    ON delivery_outbox(principal_id, idempotency_key)
                    WHERE idempotency_key <> ''
                    """
                )
                cur.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_delivery_outbox_retry_schedule
                    ON delivery_outbox(status, next_attempt_at, created_at DESC)
                    """
                )
                cur.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_delivery_outbox_principal_status_created
                    ON delivery_outbox(principal_id, status, created_at DESC)
                    """
                )

    def enqueue(
        self,
        channel: str,
        recipient: str,
        content: str,
        metadata: dict[str, object] | None = None,
        *,
        principal_id: str = "",
        idempotency_key: str = "",
    ) -> DeliveryOutboxItem:
        principal = str(principal_id or "").strip()
        idem = str(idempotency_key or "").strip()
        if idem:
            with self._connect() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT delivery_id, principal_id, channel, recipient, content, status, metadata_json, created_at, sent_at,
                               idempotency_key, attempt_count, next_attempt_at, last_error, receipt_json, dead_lettered_at
                        FROM delivery_outbox
                        WHERE principal_id = %s AND idempotency_key = %s
                        LIMIT 1
                        """,
                        (principal, idem),
                    )
                    found = cur.fetchone()
            if found:
                return _as_delivery(found)
        row = DeliveryOutboxItem(
            delivery_id=str(uuid.uuid4()),
            principal_id=principal,
            channel=str(channel or "unknown").strip(),
            recipient=str(recipient or "").strip(),
            content=str(content or ""),
            status="queued",
            metadata=dict(metadata or {}),
            created_at=now_utc_iso(),
            sent_at=None,
            idempotency_key=idem,
            attempt_count=0,
            next_attempt_at=None,
            last_error="",
            receipt_json={},
            dead_lettered_at=None,
        )
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO delivery_outbox
                    (delivery_id, principal_id, channel, recipient, content, status, metadata_json, created_at, sent_at,
                     idempotency_key, attempt_count, next_attempt_at, last_error, receipt_json, dead_lettered_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        row.delivery_id,
                        row.principal_id,
                        row.channel,
                        row.recipient,
                        row.content,
                        row.status,
                        self._json_value(row.metadata),
                        row.created_at,
                        row.sent_at,
                        row.idempotency_key,
                        row.attempt_count,
                        row.next_attempt_at,
                        row.last_error,
                        self._json_value(row.receipt_json),
                        row.dead_lettered_at,
                    ),
                )
        return row

    def mark_sent(
        self,
        delivery_id: str,
        *,
        principal_id: str = "",
        receipt_json: dict[str, object] | None = None,
    ) -> DeliveryOutboxItem | None:
        did = str(delivery_id or "")
        if not did:
            return None
        principal = str(principal_id or "").strip()
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE delivery_outbox
                    SET status = 'sent',
                        sent_at = %s,
                        receipt_json = %s,
                        last_error = '',
                        next_attempt_at = NULL,
                        dead_lettered_at = NULL
                    WHERE delivery_id = %s AND principal_id = %s
                    RETURNING delivery_id, principal_id, channel, recipient, content, status, metadata_json, created_at, sent_at,
                              idempotency_key, attempt_count, next_attempt_at, last_error, receipt_json, dead_lettered_at
                    """,
                    (now_utc_iso(), self._json_value(dict(receipt_json or {})), did, principal),
                )
                row = cur.fetchone()
        if not row:
            return None
        return _as_delivery(row)

    def mark_failed(
        self,
        delivery_id: str,
        *,
        principal_id: str = "",
        error: str,
        next_attempt_at: str | None = None,
        dead_letter: bool = False,
    ) -> DeliveryOutboxItem | None:
        did = str(delivery_id or "")
        if not did:
            return None
        principal = str(principal_id or "").strip()
        status = "dead_lettered" if dead_letter else "retry"
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE delivery_outbox
                    SET status = %s,
                        attempt_count = attempt_count + 1,
                        next_attempt_at = %s,
                        last_error = %s,
                        dead_lettered_at = %s
                    WHERE delivery_id = %s AND principal_id = %s
                    RETURNING delivery_id, principal_id, channel, recipient, content, status, metadata_json, created_at, sent_at,
                              idempotency_key, attempt_count, next_attempt_at, last_error, receipt_json, dead_lettered_at
                    """,
                    (
                        status,
                        None if dead_letter else next_attempt_at,
                        str(error or ""),
                        now_utc_iso() if dead_letter else None,
                        did,
                        principal,
                    ),
                )
                row = cur.fetchone()
        if not row:
            return None
        return _as_delivery(row)


    def list_pending(self, limit: int = 50, *, principal_id: str | None = None) -> list[DeliveryOutboxItem]:
        n = max(1, min(500, int(limit or 50)))
        normalized_principal = str(principal_id or "").strip()
        query = """
            SELECT delivery_id, principal_id, channel, recipient, content, status, metadata_json, created_at, sent_at,
                   idempotency_key, attempt_count, next_attempt_at, last_error, receipt_json, dead_lettered_at
            FROM delivery_outbox
            WHERE status IN ('queued', 'retry')
              AND (next_attempt_at IS NULL OR next_attempt_at <= NOW())
        """
        params: list[Any] = []
        if normalized_principal:
            query += " AND principal_id = %s"
            params.append(normalized_principal)
        query += " ORDER BY created_at DESC, delivery_id DESC LIMIT %s"
        params.append(n)
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(query, tuple(params))
                rows = cur.fetchall()
        return [_as_delivery(row) for row in rows]
