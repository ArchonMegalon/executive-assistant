from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from app.domain.models import HumanTask, now_utc_iso


def _to_iso(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value or "")


class PostgresHumanTaskRepository:
    def __init__(self, database_url: str) -> None:
        self._database_url = str(database_url or "").strip()
        if not self._database_url:
            raise ValueError("database_url is required for PostgresHumanTaskRepository")
        self._ensure_schema()

    def _connect(self):  # type: ignore[no-untyped-def]
        try:
            import psycopg
        except Exception as exc:  # pragma: no cover - import guard
            raise RuntimeError("psycopg is required for postgres human-task backend") from exc
        return psycopg.connect(self._database_url, autocommit=True)

    def _json_value(self, value: dict[str, Any]):  # type: ignore[no-untyped-def]
        from psycopg.types.json import Json

        return Json(value)

    def _ensure_schema(self) -> None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS human_tasks (
                        human_task_id TEXT PRIMARY KEY,
                        session_id TEXT NOT NULL REFERENCES execution_sessions(session_id) ON DELETE CASCADE,
                        step_id TEXT NULL REFERENCES execution_steps(step_id) ON DELETE SET NULL,
                        principal_id TEXT NOT NULL,
                        task_type TEXT NOT NULL,
                        role_required TEXT NOT NULL,
                        brief TEXT NOT NULL,
                        input_json JSONB NOT NULL,
                        desired_output_json JSONB NOT NULL,
                        priority TEXT NOT NULL,
                        sla_due_at TIMESTAMPTZ NULL,
                        status TEXT NOT NULL,
                        assigned_operator_id TEXT NOT NULL,
                        resolution TEXT NOT NULL,
                        resume_session_on_return BOOLEAN NOT NULL DEFAULT FALSE,
                        returned_payload_json JSONB NOT NULL,
                        provenance_json JSONB NOT NULL,
                        created_at TIMESTAMPTZ NOT NULL,
                        updated_at TIMESTAMPTZ NOT NULL
                    )
                    """
                )
                cur.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_human_tasks_principal_status_created
                    ON human_tasks(principal_id, status, created_at DESC, human_task_id DESC)
                    """
                )
                cur.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_human_tasks_session_created
                    ON human_tasks(session_id, created_at ASC, human_task_id ASC)
                    """
                )
                cur.execute(
                    """
                    ALTER TABLE human_tasks
                    ADD COLUMN IF NOT EXISTS resume_session_on_return BOOLEAN NOT NULL DEFAULT FALSE
                    """
                )

    def _from_row(self, row: tuple[Any, ...]) -> HumanTask:
        (
            human_task_id,
            session_id,
            step_id,
            principal_id,
            task_type,
            role_required,
            brief,
            input_json,
            desired_output_json,
            priority,
            sla_due_at,
            status,
            assigned_operator_id,
            resolution,
            resume_session_on_return,
            returned_payload_json,
            provenance_json,
            created_at,
            updated_at,
        ) = row
        return HumanTask(
            human_task_id=str(human_task_id),
            session_id=str(session_id),
            step_id=str(step_id) if step_id else None,
            principal_id=str(principal_id),
            task_type=str(task_type),
            role_required=str(role_required),
            brief=str(brief),
            input_json=dict(input_json or {}),
            desired_output_json=dict(desired_output_json or {}),
            priority=str(priority),
            sla_due_at=_to_iso(sla_due_at) if sla_due_at else None,
            status=str(status),
            assigned_operator_id=str(assigned_operator_id or ""),
            resolution=str(resolution or ""),
            resume_session_on_return=bool(resume_session_on_return),
            created_at=_to_iso(created_at),
            updated_at=_to_iso(updated_at),
            returned_payload_json=dict(returned_payload_json or {}),
            provenance_json=dict(provenance_json or {}),
        )

    def create(
        self,
        *,
        session_id: str,
        step_id: str | None,
        principal_id: str,
        task_type: str,
        role_required: str,
        brief: str,
        input_json: dict[str, object] | None = None,
        desired_output_json: dict[str, object] | None = None,
        priority: str = "normal",
        sla_due_at: str | None = None,
        resume_session_on_return: bool = False,
    ) -> HumanTask:
        ts = now_utc_iso()
        row = HumanTask(
            human_task_id=str(uuid.uuid4()),
            session_id=str(session_id or ""),
            step_id=str(step_id) if step_id else None,
            principal_id=str(principal_id or ""),
            task_type=str(task_type or ""),
            role_required=str(role_required or ""),
            brief=str(brief or ""),
            input_json=dict(input_json or {}),
            desired_output_json=dict(desired_output_json or {}),
            priority=str(priority or "normal"),
            sla_due_at=str(sla_due_at) if sla_due_at else None,
            status="pending",
            assigned_operator_id="",
            resolution="",
            created_at=ts,
            updated_at=ts,
            resume_session_on_return=bool(resume_session_on_return),
            returned_payload_json={},
            provenance_json={},
        )
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO human_tasks (
                        human_task_id, session_id, step_id, principal_id, task_type, role_required, brief,
                        input_json, desired_output_json, priority, sla_due_at, status, assigned_operator_id,
                        resolution, resume_session_on_return, returned_payload_json, provenance_json, created_at, updated_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        row.human_task_id,
                        row.session_id,
                        row.step_id,
                        row.principal_id,
                        row.task_type,
                        row.role_required,
                        row.brief,
                        self._json_value(row.input_json),
                        self._json_value(row.desired_output_json),
                        row.priority,
                        row.sla_due_at,
                        row.status,
                        row.assigned_operator_id,
                        row.resolution,
                        row.resume_session_on_return,
                        self._json_value(row.returned_payload_json),
                        self._json_value(row.provenance_json),
                        row.created_at,
                        row.updated_at,
                    ),
                )
        return row

    def get(self, human_task_id: str) -> HumanTask | None:
        task_id = str(human_task_id or "")
        if not task_id:
            return None
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT human_task_id, session_id, step_id, principal_id, task_type, role_required, brief,
                           input_json, desired_output_json, priority, sla_due_at, status, assigned_operator_id,
                           resolution, resume_session_on_return, returned_payload_json, provenance_json, created_at, updated_at
                    FROM human_tasks
                    WHERE human_task_id = %s
                    """,
                    (task_id,),
                )
                row = cur.fetchone()
        if not row:
            return None
        return self._from_row(row)

    def list_for_principal(
        self,
        principal_id: str,
        *,
        status: str | None = None,
        role_required: str | None = None,
        assigned_operator_id: str | None = None,
        overdue_only: bool = False,
        limit: int = 50,
    ) -> list[HumanTask]:
        principal = str(principal_id or "")
        status_filter = str(status or "").strip()
        role_filter = str(role_required or "").strip()
        operator_filter = str(assigned_operator_id or "").strip()
        n = max(1, min(500, int(limit or 50)))
        clauses = ["principal_id = %s"]
        params: list[object] = [principal]
        if status_filter:
            clauses.append("status = %s")
            params.append(status_filter)
        if role_filter:
            clauses.append("role_required = %s")
            params.append(role_filter)
        if operator_filter:
            clauses.append("assigned_operator_id = %s")
            params.append(operator_filter)
        if overdue_only:
            clauses.append("sla_due_at IS NOT NULL")
            clauses.append("sla_due_at <= NOW()")
        params.append(n)
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT human_task_id, session_id, step_id, principal_id, task_type, role_required, brief,
                           input_json, desired_output_json, priority, sla_due_at, status, assigned_operator_id,
                           resolution, resume_session_on_return, returned_payload_json, provenance_json, created_at, updated_at
                    FROM human_tasks
                    WHERE {' AND '.join(clauses)}
                    ORDER BY created_at DESC, human_task_id DESC
                    LIMIT %s
                    """,
                    tuple(params),
                )
                rows = cur.fetchall()
        return [self._from_row(row) for row in rows]

    def list_for_session(self, session_id: str, *, limit: int = 200) -> list[HumanTask]:
        session = str(session_id or "")
        n = max(1, min(1000, int(limit or 200)))
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT human_task_id, session_id, step_id, principal_id, task_type, role_required, brief,
                           input_json, desired_output_json, priority, sla_due_at, status, assigned_operator_id,
                           resolution, resume_session_on_return, returned_payload_json, provenance_json, created_at, updated_at
                    FROM human_tasks
                    WHERE session_id = %s
                    ORDER BY created_at ASC, human_task_id ASC
                    LIMIT %s
                    """,
                    (session, n),
                )
                rows = cur.fetchall()
        return [self._from_row(row) for row in rows]

    def claim(self, human_task_id: str, *, operator_id: str) -> HumanTask | None:
        task_id = str(human_task_id or "")
        if not task_id:
            return None
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE human_tasks
                    SET status = 'claimed',
                        assigned_operator_id = %s,
                        updated_at = %s
                    WHERE human_task_id = %s AND status = 'pending'
                    RETURNING human_task_id, session_id, step_id, principal_id, task_type, role_required, brief,
                              input_json, desired_output_json, priority, sla_due_at, status, assigned_operator_id,
                              resolution, resume_session_on_return, returned_payload_json, provenance_json, created_at, updated_at
                    """,
                    (str(operator_id or ""), now_utc_iso(), task_id),
                )
                row = cur.fetchone()
        if not row:
            return None
        return self._from_row(row)

    def assign(self, human_task_id: str, *, operator_id: str) -> HumanTask | None:
        task_id = str(human_task_id or "")
        if not task_id:
            return None
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE human_tasks
                    SET assigned_operator_id = %s,
                        updated_at = %s
                    WHERE human_task_id = %s AND status = 'pending'
                    RETURNING human_task_id, session_id, step_id, principal_id, task_type, role_required, brief,
                              input_json, desired_output_json, priority, sla_due_at, status, assigned_operator_id,
                              resolution, resume_session_on_return, returned_payload_json, provenance_json, created_at, updated_at
                    """,
                    (str(operator_id or ""), now_utc_iso(), task_id),
                )
                row = cur.fetchone()
        if not row:
            return None
        return self._from_row(row)

    def return_task(
        self,
        human_task_id: str,
        *,
        operator_id: str,
        resolution: str,
        returned_payload_json: dict[str, object] | None = None,
        provenance_json: dict[str, object] | None = None,
    ) -> HumanTask | None:
        task_id = str(human_task_id or "")
        if not task_id:
            return None
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE human_tasks
                    SET status = 'returned',
                        assigned_operator_id = %s,
                        resolution = %s,
                        returned_payload_json = %s,
                        provenance_json = %s,
                        updated_at = %s
                    WHERE human_task_id = %s AND status IN ('pending', 'claimed')
                    RETURNING human_task_id, session_id, step_id, principal_id, task_type, role_required, brief,
                              input_json, desired_output_json, priority, sla_due_at, status, assigned_operator_id,
                              resolution, resume_session_on_return, returned_payload_json, provenance_json, created_at, updated_at
                    """,
                    (
                        str(operator_id or ""),
                        str(resolution or ""),
                        self._json_value(dict(returned_payload_json or {})),
                        self._json_value(dict(provenance_json or {})),
                        now_utc_iso(),
                        task_id,
                    ),
                )
                row = cur.fetchone()
        if not row:
            return None
        return self._from_row(row)
