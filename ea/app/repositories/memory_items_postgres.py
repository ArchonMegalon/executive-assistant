from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from app.domain.models import MemoryItem, now_utc_iso
from app.repositories.memory_items import (
    MemoryItemSnapshotLimitExceeded,
    validate_memory_item_snapshot_request,
)


def _to_iso(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value or "")


def _clamp_confidence(value: float) -> float:
    try:
        numeric = float(value)
    except Exception:
        numeric = 0.5
    if numeric < 0.0:
        return 0.0
    if numeric > 1.0:
        return 1.0
    return numeric


class PostgresMemoryItemRepository:
    def __init__(self, database_url: str) -> None:
        self._database_url = str(database_url or "").strip()
        if not self._database_url:
            raise ValueError("database_url is required for PostgresMemoryItemRepository")
        self._ensure_schema()

    @property
    def snapshot_storage_durable(self) -> bool:
        return True

    def _connect(self):  # type: ignore[no-untyped-def]
        try:
            import psycopg
        except Exception as exc:  # pragma: no cover - import guard
            raise RuntimeError("psycopg is required for postgres memory-item backend") from exc
        return psycopg.connect(self._database_url, autocommit=True)

    def _json_value(self, value: dict[str, Any]):  # type: ignore[no-untyped-def]
        from psycopg.types.json import Json

        return Json(value)

    def _ensure_schema(self) -> None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS memory_items (
                        item_id TEXT PRIMARY KEY,
                        principal_id TEXT NOT NULL,
                        category TEXT NOT NULL,
                        summary TEXT NOT NULL,
                        fact_json JSONB NOT NULL,
                        provenance_json JSONB NOT NULL,
                        confidence DOUBLE PRECISION NOT NULL,
                        sensitivity TEXT NOT NULL,
                        sharing_policy TEXT NOT NULL,
                        last_verified_at TIMESTAMPTZ NULL,
                        reviewer TEXT NOT NULL DEFAULT '',
                        created_at TIMESTAMPTZ NOT NULL,
                        updated_at TIMESTAMPTZ NOT NULL
                    )
                    """
                )
                cur.execute(
                    "ALTER TABLE memory_items ADD COLUMN IF NOT EXISTS provenance_json JSONB NOT NULL DEFAULT '{}'::jsonb"
                )
                cur.execute(
                    "ALTER TABLE memory_items ADD COLUMN IF NOT EXISTS confidence DOUBLE PRECISION NOT NULL DEFAULT 0.5"
                )
                cur.execute(
                    "ALTER TABLE memory_items ADD COLUMN IF NOT EXISTS sensitivity TEXT NOT NULL DEFAULT 'internal'"
                )
                cur.execute(
                    "ALTER TABLE memory_items ADD COLUMN IF NOT EXISTS sharing_policy TEXT NOT NULL DEFAULT 'private'"
                )
                cur.execute("ALTER TABLE memory_items ADD COLUMN IF NOT EXISTS last_verified_at TIMESTAMPTZ NULL")
                cur.execute("ALTER TABLE memory_items ADD COLUMN IF NOT EXISTS reviewer TEXT NOT NULL DEFAULT ''")
                cur.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_memory_items_principal_updated
                    ON memory_items(principal_id, updated_at DESC)
                    """
                )
                cur.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_memory_items_principal_created
                    ON memory_items(principal_id, created_at, item_id)
                    """
                )
                cur.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_memory_items_category_updated
                    ON memory_items(category, updated_at DESC)
                    """
                )

    def _from_row(self, row: tuple[Any, ...]) -> MemoryItem:
        (
            item_id,
            principal_id,
            category,
            summary,
            fact_json,
            provenance_json,
            confidence,
            sensitivity,
            sharing_policy,
            last_verified_at,
            reviewer,
            created_at,
            updated_at,
        ) = row
        return MemoryItem(
            item_id=str(item_id),
            principal_id=str(principal_id),
            category=str(category),
            summary=str(summary),
            fact_json=dict(fact_json or {}),
            provenance_json=dict(provenance_json or {}),
            confidence=float(confidence or 0.0),
            sensitivity=str(sensitivity or "internal"),
            sharing_policy=str(sharing_policy or "private"),
            last_verified_at=_to_iso(last_verified_at) if last_verified_at else None,
            reviewer=str(reviewer or ""),
            created_at=_to_iso(created_at),
            updated_at=_to_iso(updated_at),
        )

    def create_item(
        self,
        *,
        principal_id: str,
        category: str,
        summary: str,
        fact_json: dict[str, object] | None = None,
        provenance_json: dict[str, object] | None = None,
        confidence: float = 0.5,
        sensitivity: str = "internal",
        sharing_policy: str = "private",
        reviewer: str = "",
        last_verified_at: str | None = None,
    ) -> MemoryItem:
        ts = now_utc_iso()
        row = MemoryItem(
            item_id=str(uuid.uuid4()),
            principal_id=str(principal_id or "").strip(),
            category=str(category or "fact").strip() or "fact",
            summary=str(summary or "").strip(),
            fact_json=dict(fact_json or {}),
            provenance_json=dict(provenance_json or {}),
            confidence=_clamp_confidence(confidence),
            sensitivity=str(sensitivity or "internal").strip() or "internal",
            sharing_policy=str(sharing_policy or "private").strip() or "private",
            last_verified_at=str(last_verified_at or ts),
            reviewer=str(reviewer or "").strip(),
            created_at=ts,
            updated_at=ts,
        )
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO memory_items
                    (item_id, principal_id, category, summary, fact_json, provenance_json,
                     confidence, sensitivity, sharing_policy, last_verified_at, reviewer,
                     created_at, updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING item_id, principal_id, category, summary, fact_json, provenance_json,
                              confidence, sensitivity, sharing_policy, last_verified_at, reviewer,
                              created_at, updated_at
                    """,
                    (
                        row.item_id,
                        row.principal_id,
                        row.category,
                        row.summary,
                        self._json_value(row.fact_json),
                        self._json_value(row.provenance_json),
                        row.confidence,
                        row.sensitivity,
                        row.sharing_policy,
                        row.last_verified_at,
                        row.reviewer,
                        row.created_at,
                        row.updated_at,
                    ),
                )
                out = cur.fetchone()
        if not out:
            return row
        return self._from_row(out)

    def get(self, item_id: str) -> MemoryItem | None:
        key = str(item_id or "")
        if not key:
            return None
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT item_id, principal_id, category, summary, fact_json, provenance_json,
                           confidence, sensitivity, sharing_policy, last_verified_at, reviewer,
                           created_at, updated_at
                    FROM memory_items
                    WHERE item_id = %s
                    """,
                    (key,),
                )
                row = cur.fetchone()
        if not row:
            return None
        return self._from_row(row)

    def list_items(
        self,
        *,
        limit: int = 100,
        principal_id: str | None = None,
    ) -> list[MemoryItem]:
        n = max(1, min(500, int(limit or 100)))
        principal_filter = str(principal_id or "").strip()
        params: list[object] = []
        where_sql = ""
        if principal_filter:
            where_sql = "WHERE principal_id = %s"
            params.append(principal_filter)
        query = (
            "SELECT item_id, principal_id, category, summary, fact_json, provenance_json, "
            "confidence, sensitivity, sharing_policy, last_verified_at, reviewer, "
            "created_at, updated_at "
            "FROM memory_items "
            f"{where_sql} "
            "ORDER BY updated_at DESC, item_id DESC LIMIT %s"
        )
        params.append(n)
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(query, tuple(params))
                rows = cur.fetchall()
        return [self._from_row(row) for row in rows]

    def export_principal_snapshot(
        self,
        *,
        principal_id: str,
        max_items: int,
    ) -> list[MemoryItem]:
        principal, item_limit = validate_memory_item_snapshot_request(
            principal_id=principal_id,
            max_items=max_items,
        )
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT item_id, principal_id, category, summary, fact_json, provenance_json,
                           confidence, sensitivity, sharing_policy, last_verified_at, reviewer,
                           created_at, updated_at
                    FROM memory_items
                    WHERE principal_id = %s
                    ORDER BY created_at ASC, item_id ASC
                    LIMIT %s
                    """,
                    (principal, item_limit + 1),
                )
                rows = cur.fetchall()
        if len(rows) > item_limit:
            raise MemoryItemSnapshotLimitExceeded(
                principal_id=principal,
                max_items=item_limit,
            )
        return [self._from_row(row) for row in rows]
