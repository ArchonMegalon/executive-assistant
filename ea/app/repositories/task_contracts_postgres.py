from __future__ import annotations

from datetime import datetime
from typing import Any

from app.domain.models import TaskContract, now_utc_iso


def _to_iso(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value or "")


class PostgresTaskContractRepository:
    def __init__(self, database_url: str) -> None:
        self._database_url = str(database_url or "").strip()
        if not self._database_url:
            raise ValueError("database_url is required for PostgresTaskContractRepository")
        self._ensure_schema()

    def _connect(self):  # type: ignore[no-untyped-def]
        try:
            import psycopg
        except Exception as exc:  # pragma: no cover - import guard
            raise RuntimeError("psycopg is required for postgres task-contract backend") from exc
        return psycopg.connect(self._database_url, autocommit=True)

    def _json_value(self, value: Any):  # type: ignore[no-untyped-def]
        from psycopg.types.json import Json

        return Json(value)

    def _ensure_schema(self) -> None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS task_contracts (
                        task_key TEXT PRIMARY KEY,
                        deliverable_type TEXT NOT NULL,
                        default_risk_class TEXT NOT NULL,
                        default_approval_class TEXT NOT NULL,
                        allowed_tools_json JSONB NOT NULL,
                        evidence_requirements_json JSONB NOT NULL,
                        memory_write_policy TEXT NOT NULL,
                        budget_policy_json JSONB NOT NULL,
                        runtime_policy_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                        updated_at TIMESTAMPTZ NOT NULL
                    )
                    """
                )
                cur.execute(
                    """
                    ALTER TABLE task_contracts
                    ADD COLUMN IF NOT EXISTS runtime_policy_json JSONB NOT NULL DEFAULT '{}'::jsonb
                    """
                )
                cur.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_task_contracts_updated
                    ON task_contracts(updated_at DESC)
                    """
                )

    def _from_row(self, row: tuple[Any, ...]) -> TaskContract:
        (
            task_key,
            deliverable_type,
            default_risk_class,
            default_approval_class,
            allowed_tools_json,
            evidence_requirements_json,
            memory_write_policy,
            budget_policy_json,
            runtime_policy_json,
            updated_at,
        ) = row
        return TaskContract(
            task_key=str(task_key),
            deliverable_type=str(deliverable_type),
            default_risk_class=str(default_risk_class),
            default_approval_class=str(default_approval_class),
            allowed_tools=tuple(str(v) for v in (allowed_tools_json or [])),
            evidence_requirements=tuple(str(v) for v in (evidence_requirements_json or [])),
            memory_write_policy=str(memory_write_policy),
            budget_policy_json=dict(budget_policy_json or {}),
            updated_at=_to_iso(updated_at),
            runtime_policy_json=dict(runtime_policy_json or {}),
        )

    def upsert(self, row: TaskContract) -> TaskContract:
        key = str(row.task_key or "").strip()
        if not key:
            raise ValueError("task_key is required")
        updated = TaskContract(
            task_key=key,
            deliverable_type=str(row.deliverable_type or ""),
            default_risk_class=str(row.default_risk_class or "low"),
            default_approval_class=str(row.default_approval_class or "none"),
            allowed_tools=tuple(str(v) for v in row.allowed_tools),
            evidence_requirements=tuple(str(v) for v in row.evidence_requirements),
            memory_write_policy=str(row.memory_write_policy or "reviewed_only"),
            budget_policy_json=dict(row.budget_policy_json or {}),
            updated_at=now_utc_iso(),
            runtime_policy_json=dict(row.runtime_policy_json or {}),
        )
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO task_contracts
                    (task_key, deliverable_type, default_risk_class, default_approval_class, allowed_tools_json,
                     evidence_requirements_json, memory_write_policy, budget_policy_json, runtime_policy_json, updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (task_key) DO UPDATE
                    SET deliverable_type = EXCLUDED.deliverable_type,
                        default_risk_class = EXCLUDED.default_risk_class,
                        default_approval_class = EXCLUDED.default_approval_class,
                        allowed_tools_json = EXCLUDED.allowed_tools_json,
                        evidence_requirements_json = EXCLUDED.evidence_requirements_json,
                        memory_write_policy = EXCLUDED.memory_write_policy,
                        budget_policy_json = EXCLUDED.budget_policy_json,
                        runtime_policy_json = EXCLUDED.runtime_policy_json,
                        updated_at = EXCLUDED.updated_at
                    RETURNING task_key, deliverable_type, default_risk_class, default_approval_class, allowed_tools_json,
                              evidence_requirements_json, memory_write_policy, budget_policy_json, runtime_policy_json, updated_at
                    """,
                    (
                        updated.task_key,
                        updated.deliverable_type,
                        updated.default_risk_class,
                        updated.default_approval_class,
                        self._json_value(list(updated.allowed_tools)),
                        self._json_value(list(updated.evidence_requirements)),
                        updated.memory_write_policy,
                        self._json_value(updated.budget_policy_json),
                        self._json_value(updated.runtime_policy_json),
                        updated.updated_at,
                    ),
                )
                out = cur.fetchone()
        if not out:
            return updated
        return self._from_row(out)

    def get(self, task_key: str) -> TaskContract | None:
        key = str(task_key or "").strip()
        if not key:
            return None
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT task_key, deliverable_type, default_risk_class, default_approval_class, allowed_tools_json,
                           evidence_requirements_json, memory_write_policy, budget_policy_json, runtime_policy_json, updated_at
                    FROM task_contracts
                    WHERE task_key = %s
                    """,
                    (key,),
                )
                row = cur.fetchone()
        if not row:
            return None
        return self._from_row(row)

    def list_all(self, limit: int = 100) -> list[TaskContract]:
        n = max(1, min(500, int(limit or 100)))
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT task_key, deliverable_type, default_risk_class, default_approval_class, allowed_tools_json,
                           evidence_requirements_json, memory_write_policy, budget_policy_json, runtime_policy_json, updated_at
                    FROM task_contracts
                    ORDER BY updated_at DESC, task_key DESC
                    LIMIT %s
                    """,
                    (n,),
                )
                rows = cur.fetchall()
        return [self._from_row(row) for row in rows]
