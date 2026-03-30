from __future__ import annotations

import uuid
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from typing import Any

from app.domain.models import (
    ExecutionEvent,
    ExecutionQueueItem,
    ExecutionSession,
    ExecutionStep,
    IntentSpecV3,
    RunCost,
    ToolReceipt,
    now_utc_iso,
)


def _to_iso(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value or "")


def _intent_from_row(raw: dict[str, Any]) -> IntentSpecV3:
    return IntentSpecV3(
        principal_id=str(raw.get("principal_id") or ""),
        goal=str(raw.get("goal") or ""),
        task_type=str(raw.get("task_type") or ""),
        deliverable_type=str(raw.get("deliverable_type") or ""),
        risk_class=str(raw.get("risk_class") or ""),
        approval_class=str(raw.get("approval_class") or ""),
        budget_class=str(raw.get("budget_class") or ""),
        stakeholders=tuple(raw.get("stakeholders") or ()),
        evidence_requirements=tuple(raw.get("evidence_requirements") or ()),
        allowed_tools=tuple(raw.get("allowed_tools") or ()),
        desired_artifact=str(raw.get("desired_artifact") or ""),
        time_horizon=str(raw.get("time_horizon") or "immediate"),
        interruption_budget=str(raw.get("interruption_budget") or "low"),
        memory_write_policy=str(raw.get("memory_write_policy") or "reviewed_only"),
    )


class PostgresExecutionLedgerRepository:
    def __init__(self, database_url: str) -> None:
        self._database_url = str(database_url or "").strip()
        if not self._database_url:
            raise ValueError("database_url is required for PostgresExecutionLedgerRepository")
        self._ensure_schema()

    def _connect(self):  # type: ignore[no-untyped-def]
        try:
            import psycopg
        except Exception as exc:  # pragma: no cover - import guard
            raise RuntimeError("psycopg is required for postgres ledger backend") from exc
        return psycopg.connect(self._database_url, autocommit=True)

    def _json_value(self, value: dict[str, Any]):  # type: ignore[no-untyped-def]
        from psycopg.types.json import Json

        return Json(value)

    def _column_type(self, cur, table_name: str, column_name: str, default: str = "text") -> str:  # type: ignore[no-untyped-def]
        cur.execute(
            """
            SELECT format_type(a.atttypid, a.atttypmod)
            FROM pg_attribute a
            JOIN pg_class c ON c.oid = a.attrelid
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = 'public'
              AND c.relname = %s
              AND a.attname = %s
              AND a.attnum > 0
              AND NOT a.attisdropped
            """,
            (table_name, column_name),
        )
        row = cur.fetchone()
        raw = str(row[0] if row else "").strip().lower()
        return raw or (str(default or "text").strip().lower() or "text")

    def _table_columns(self, cur, table_name: str) -> set[str]:  # type: ignore[no-untyped-def]
        cur.execute(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = %s
            """,
            (table_name,),
        )
        return {str(row[0] or "").strip() for row in cur.fetchall()}

    def _ensure_execution_events_compatibility(self, cur) -> None:  # type: ignore[no-untyped-def]
        cur.execute(
            """
            ALTER TABLE execution_events
            ADD COLUMN IF NOT EXISTS name TEXT
            """
        )
        if self._column_type(cur, "execution_events", "event_id", "text") != "text":
            cur.execute(
                """
                ALTER TABLE execution_events
                ALTER COLUMN event_id DROP DEFAULT
                """
            )
            cur.execute(
                """
                ALTER TABLE execution_events
                ALTER COLUMN event_id TYPE TEXT USING event_id::text
                """
            )

        event_columns = self._table_columns(cur, "execution_events")
        name_sources = ["NULLIF(name, '')"]
        if "event_type" in event_columns:
            name_sources.append("NULLIF(event_type, '')")
            cur.execute(
                """
                ALTER TABLE execution_events
                ALTER COLUMN event_type SET DEFAULT 'event'
                """
            )
        if "message" in event_columns:
            name_sources.append("NULLIF(message, '')")
            cur.execute(
                """
                ALTER TABLE execution_events
                ALTER COLUMN message SET DEFAULT ''
                """
            )
        name_sources.append("'event'")
        cur.execute(
            f"""
            UPDATE execution_events
            SET name = COALESCE({", ".join(name_sources)})
            WHERE COALESCE(name, '') = ''
            """
        )
        if "event_type" in event_columns:
            cur.execute(
                """
                UPDATE execution_events
                SET event_type = COALESCE(NULLIF(event_type, ''), name, 'event')
                WHERE COALESCE(event_type, '') = ''
                """
            )
        if "message" in event_columns:
            cur.execute(
                """
                UPDATE execution_events
                SET message = COALESCE(message, '')
                """
            )
        cur.execute(
            """
            UPDATE execution_events
            SET payload_json = COALESCE(payload_json, '{}'::jsonb),
                created_at = COALESCE(created_at, NOW())
            """
        )
        cur.execute(
            """
            ALTER TABLE execution_events
            ALTER COLUMN name SET NOT NULL,
            ALTER COLUMN payload_json SET NOT NULL,
            ALTER COLUMN created_at SET NOT NULL
            """
        )
        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_execution_events_session_created
            ON execution_events(session_id, created_at)
            """
        )

    def _ensure_execution_steps_compatibility(self, cur) -> None:  # type: ignore[no-untyped-def]
        cur.execute(
            """
            ALTER TABLE execution_steps
            ADD COLUMN IF NOT EXISTS parent_step_id TEXT,
            ADD COLUMN IF NOT EXISTS step_kind TEXT,
            ADD COLUMN IF NOT EXISTS state TEXT,
            ADD COLUMN IF NOT EXISTS attempt_count INT,
            ADD COLUMN IF NOT EXISTS input_json JSONB,
            ADD COLUMN IF NOT EXISTS output_json JSONB,
            ADD COLUMN IF NOT EXISTS error_json JSONB,
            ADD COLUMN IF NOT EXISTS correlation_id TEXT,
            ADD COLUMN IF NOT EXISTS causation_id TEXT,
            ADD COLUMN IF NOT EXISTS actor_type TEXT,
            ADD COLUMN IF NOT EXISTS actor_id TEXT
            """
        )

        step_columns = self._table_columns(cur, "execution_steps")

        step_kind_sources = ["NULLIF(step_kind, '')"]
        if "step_key" in step_columns:
            step_kind_sources.append("NULLIF(step_key, '')")
        if "step_title" in step_columns:
            step_kind_sources.append("NULLIF(step_title, '')")
        step_kind_sources.append("'step'")
        cur.execute(
            f"""
            UPDATE execution_steps
            SET step_kind = COALESCE({", ".join(step_kind_sources)})
            WHERE COALESCE(step_kind, '') = ''
            """
        )

        state_sources = ["NULLIF(state, '')"]
        if "status" in step_columns:
            state_sources.append("NULLIF(status, '')")
        state_sources.append("'queued'")
        cur.execute(
            f"""
            UPDATE execution_steps
            SET state = COALESCE({", ".join(state_sources)})
            WHERE COALESCE(state, '') = ''
            """
        )

        input_sources = ["input_json"]
        if "preconditions_json" in step_columns:
            input_sources.append("preconditions_json")
        input_sources.append("'{}'::jsonb")
        cur.execute(
            f"""
            UPDATE execution_steps
            SET input_json = COALESCE({", ".join(input_sources)})
            WHERE input_json IS NULL
            """
        )

        output_sources = ["output_json"]
        if "result_json" in step_columns:
            output_sources.append("NULLIF(result_json, '{}'::jsonb)")
        if "evidence_json" in step_columns:
            output_sources.append("NULLIF(evidence_json, '{}'::jsonb)")
        output_sources.append("'{}'::jsonb")
        cur.execute(
            f"""
            UPDATE execution_steps
            SET output_json = COALESCE({", ".join(output_sources)})
            WHERE output_json IS NULL
            """
        )

        if "error_text" in step_columns:
            cur.execute(
                """
                UPDATE execution_steps
                SET error_json = CASE
                    WHEN COALESCE(BTRIM(error_text), '') <> '' THEN jsonb_build_object('message', error_text)
                    ELSE '{}'::jsonb
                END
                WHERE error_json IS NULL
                """
            )
        else:
            cur.execute(
                """
                UPDATE execution_steps
                SET error_json = '{}'::jsonb
                WHERE error_json IS NULL
                """
            )

        cur.execute(
            """
            UPDATE execution_steps
            SET attempt_count = COALESCE(attempt_count, 0),
                correlation_id = COALESCE(correlation_id, ''),
                causation_id = COALESCE(causation_id, ''),
                actor_type = COALESCE(NULLIF(actor_type, ''), 'system'),
                actor_id = COALESCE(NULLIF(actor_id, ''), 'orchestrator')
            """
        )
        cur.execute(
            """
            ALTER TABLE execution_steps
            ALTER COLUMN step_kind SET NOT NULL,
            ALTER COLUMN state SET NOT NULL,
            ALTER COLUMN attempt_count SET NOT NULL,
            ALTER COLUMN input_json SET NOT NULL,
            ALTER COLUMN output_json SET NOT NULL,
            ALTER COLUMN error_json SET NOT NULL,
            ALTER COLUMN correlation_id SET NOT NULL,
            ALTER COLUMN causation_id SET NOT NULL,
            ALTER COLUMN actor_type SET NOT NULL,
            ALTER COLUMN actor_id SET NOT NULL
            """
        )
        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_execution_steps_session_created
            ON execution_steps(session_id, created_at, step_id)
            """
        )

    def _ensure_schema(self) -> None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS execution_sessions (
                        session_id TEXT PRIMARY KEY,
                        intent_json JSONB NOT NULL,
                        status TEXT NOT NULL,
                        created_at TIMESTAMPTZ NOT NULL,
                        updated_at TIMESTAMPTZ NOT NULL
                    )
                    """
                )
                session_id_type = self._column_type(cur, "execution_sessions", "session_id", "text")
                if session_id_type not in {"text", "uuid"}:
                    session_id_type = "text"
                cur.execute(
                    f"""
                    CREATE TABLE IF NOT EXISTS execution_events (
                        event_id TEXT PRIMARY KEY,
                        session_id {session_id_type} NOT NULL REFERENCES execution_sessions(session_id) ON DELETE CASCADE,
                        name TEXT NOT NULL,
                        payload_json JSONB NOT NULL,
                        created_at TIMESTAMPTZ NOT NULL
                    )
                    """
                )
                self._ensure_execution_events_compatibility(cur)
                cur.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_execution_events_session_created
                    ON execution_events(session_id, created_at)
                    """
                )
                cur.execute(
                    f"""
                    CREATE TABLE IF NOT EXISTS execution_steps (
                        step_id TEXT PRIMARY KEY,
                        session_id {session_id_type} NOT NULL REFERENCES execution_sessions(session_id) ON DELETE CASCADE,
                        parent_step_id TEXT NULL,
                        step_kind TEXT NOT NULL,
                        state TEXT NOT NULL,
                        attempt_count INT NOT NULL,
                        input_json JSONB NOT NULL,
                        output_json JSONB NOT NULL,
                        error_json JSONB NOT NULL,
                        correlation_id TEXT NOT NULL,
                        causation_id TEXT NOT NULL,
                        actor_type TEXT NOT NULL,
                        actor_id TEXT NOT NULL,
                        created_at TIMESTAMPTZ NOT NULL,
                        updated_at TIMESTAMPTZ NOT NULL
                    )
                    """
                )
                self._ensure_execution_steps_compatibility(cur)
                step_id_type = self._column_type(cur, "execution_steps", "step_id", "text")
                if step_id_type not in {"text", "uuid"}:
                    step_id_type = "text"
                cur.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_execution_steps_session_created
                    ON execution_steps(session_id, created_at, step_id)
                    """
                )
                cur.execute(
                    f"""
                    CREATE TABLE IF NOT EXISTS execution_queue (
                        queue_id TEXT PRIMARY KEY,
                        session_id {session_id_type} NOT NULL REFERENCES execution_sessions(session_id) ON DELETE CASCADE,
                        step_id {step_id_type} NOT NULL REFERENCES execution_steps(step_id) ON DELETE CASCADE,
                        state TEXT NOT NULL,
                        lease_owner TEXT NOT NULL,
                        lease_expires_at TIMESTAMPTZ NULL,
                        attempt_count INT NOT NULL,
                        next_attempt_at TIMESTAMPTZ NULL,
                        idempotency_key TEXT NOT NULL UNIQUE,
                        last_error TEXT NOT NULL,
                        created_at TIMESTAMPTZ NOT NULL,
                        updated_at TIMESTAMPTZ NOT NULL
                    )
                    """
                )
                cur.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_execution_queue_state_next_attempt
                    ON execution_queue(state, next_attempt_at, created_at, queue_id)
                    """
                )
                cur.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_execution_queue_session_created
                    ON execution_queue(session_id, created_at, queue_id)
                    """
                )
                cur.execute(
                    f"""
                    CREATE TABLE IF NOT EXISTS tool_receipts (
                        receipt_id TEXT PRIMARY KEY,
                        session_id {session_id_type} NOT NULL REFERENCES execution_sessions(session_id) ON DELETE CASCADE,
                        step_id {step_id_type} NOT NULL REFERENCES execution_steps(step_id) ON DELETE CASCADE,
                        tool_name TEXT NOT NULL,
                        action_kind TEXT NOT NULL,
                        target_ref TEXT NOT NULL,
                        receipt_json JSONB NOT NULL,
                        created_at TIMESTAMPTZ NOT NULL
                    )
                    """
                )
                cur.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_tool_receipts_session_created
                    ON tool_receipts(session_id, created_at, receipt_id)
                    """
                )
                cur.execute(
                    f"""
                    CREATE TABLE IF NOT EXISTS run_costs (
                        cost_id TEXT PRIMARY KEY,
                        session_id {session_id_type} NOT NULL REFERENCES execution_sessions(session_id) ON DELETE CASCADE,
                        model_name TEXT NOT NULL,
                        tokens_in BIGINT NOT NULL,
                        tokens_out BIGINT NOT NULL,
                        cost_usd DOUBLE PRECISION NOT NULL,
                        created_at TIMESTAMPTZ NOT NULL
                    )
                    """
                )
                cur.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_run_costs_session_created
                    ON run_costs(session_id, created_at, cost_id)
                    """
                )
                self._execution_event_columns = self._table_columns(cur, "execution_events")

    def _session_from_db_row(self, row: tuple[Any, Any, Any, Any, Any]) -> ExecutionSession:
        session_id, intent_json, status, created_at, updated_at = row
        return ExecutionSession(
            session_id=str(session_id),
            intent=_intent_from_row(dict(intent_json or {})),
            status=str(status),
            created_at=_to_iso(created_at),
            updated_at=_to_iso(updated_at),
        )

    def _step_from_db_row(self, row: tuple[Any, ...]) -> ExecutionStep:
        (
            step_id,
            session_id,
            parent_step_id,
            step_kind,
            state,
            attempt_count,
            input_json,
            output_json,
            error_json,
            correlation_id,
            causation_id,
            actor_type,
            actor_id,
            created_at,
            updated_at,
        ) = row
        return ExecutionStep(
            step_id=str(step_id),
            session_id=str(session_id),
            parent_step_id=str(parent_step_id) if parent_step_id else None,
            step_kind=str(step_kind),
            state=str(state),
            attempt_count=int(attempt_count),
            input_json=dict(input_json or {}),
            output_json=dict(output_json or {}),
            error_json=dict(error_json or {}),
            correlation_id=str(correlation_id),
            causation_id=str(causation_id),
            actor_type=str(actor_type),
            actor_id=str(actor_id),
            created_at=_to_iso(created_at),
            updated_at=_to_iso(updated_at),
        )

    def _receipt_from_db_row(self, row: tuple[Any, ...]) -> ToolReceipt:
        receipt_id, session_id, step_id, tool_name, action_kind, target_ref, receipt_json, created_at = row
        return ToolReceipt(
            receipt_id=str(receipt_id),
            session_id=str(session_id),
            step_id=str(step_id),
            tool_name=str(tool_name),
            action_kind=str(action_kind),
            target_ref=str(target_ref),
            receipt_json=dict(receipt_json or {}),
            created_at=_to_iso(created_at),
        )

    def _queue_from_db_row(self, row: tuple[Any, ...]) -> ExecutionQueueItem:
        (
            queue_id,
            session_id,
            step_id,
            state,
            lease_owner,
            lease_expires_at,
            attempt_count,
            next_attempt_at,
            idempotency_key,
            last_error,
            created_at,
            updated_at,
        ) = row
        return ExecutionQueueItem(
            queue_id=str(queue_id),
            session_id=str(session_id),
            step_id=str(step_id),
            state=str(state),
            lease_owner=str(lease_owner or ""),
            lease_expires_at=_to_iso(lease_expires_at) if lease_expires_at else None,
            attempt_count=int(attempt_count),
            next_attempt_at=_to_iso(next_attempt_at) if next_attempt_at else None,
            idempotency_key=str(idempotency_key or ""),
            last_error=str(last_error or ""),
            created_at=_to_iso(created_at),
            updated_at=_to_iso(updated_at),
        )

    def _cost_from_db_row(self, row: tuple[Any, ...]) -> RunCost:
        cost_id, session_id, model_name, tokens_in, tokens_out, cost_usd, created_at = row
        return RunCost(
            cost_id=str(cost_id),
            session_id=str(session_id),
            model_name=str(model_name),
            tokens_in=int(tokens_in),
            tokens_out=int(tokens_out),
            cost_usd=float(cost_usd),
            created_at=_to_iso(created_at),
        )

    def start_session(self, intent: IntentSpecV3) -> ExecutionSession:
        session_id = str(uuid.uuid4())
        ts = now_utc_iso()
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO execution_sessions (session_id, intent_json, status, created_at, updated_at)
                    VALUES (%s, %s, %s, %s, %s)
                    """,
                    (session_id, self._json_value(asdict(intent)), "running", ts, ts),
                )
        return ExecutionSession(
            session_id=session_id,
            intent=intent,
            status="running",
            created_at=ts,
            updated_at=ts,
        )

    def set_session_status(self, session_id: str, status: str) -> ExecutionSession | None:
        sid = str(session_id or "")
        if not sid:
            return None
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE execution_sessions
                    SET status = %s, updated_at = %s
                    WHERE session_id = %s
                    RETURNING session_id, intent_json, status, created_at, updated_at
                    """,
                    (str(status or "running"), now_utc_iso(), sid),
                )
                row = cur.fetchone()
        if not row:
            return None
        return self._session_from_db_row(row)

    def complete_session(self, session_id: str, status: str = "completed") -> ExecutionSession | None:
        return self.set_session_status(session_id, str(status or "completed") or "completed")

    def append_event(self, session_id: str, name: str, payload: dict[str, object] | None = None) -> ExecutionEvent:
        sid = str(session_id or "")
        if not sid or not self.get_session(sid):
            raise KeyError(f"unknown session: {sid}")
        event = ExecutionEvent(
            event_id=str(uuid.uuid4()),
            session_id=sid,
            name=str(name or "event"),
            payload=dict(payload or {}),
            created_at=now_utc_iso(),
        )
        with self._connect() as conn:
            with conn.cursor() as cur:
                event_columns = set(getattr(self, "_execution_event_columns", set()))
                if {"event_type", "message"}.issubset(event_columns):
                    cur.execute(
                        """
                        INSERT INTO execution_events (event_id, session_id, name, event_type, message, payload_json, created_at)
                        VALUES (%s, %s, %s, %s, %s, %s, %s)
                        """,
                        (
                            event.event_id,
                            event.session_id,
                            event.name,
                            event.name,
                            "",
                            self._json_value(event.payload),
                            event.created_at,
                        ),
                    )
                elif "event_type" in event_columns:
                    cur.execute(
                        """
                        INSERT INTO execution_events (event_id, session_id, name, event_type, payload_json, created_at)
                        VALUES (%s, %s, %s, %s, %s, %s)
                        """,
                        (
                            event.event_id,
                            event.session_id,
                            event.name,
                            event.name,
                            self._json_value(event.payload),
                            event.created_at,
                        ),
                    )
                else:
                    cur.execute(
                        """
                        INSERT INTO execution_events (event_id, session_id, name, payload_json, created_at)
                        VALUES (%s, %s, %s, %s, %s)
                        """,
                        (
                            event.event_id,
                            event.session_id,
                            event.name,
                            self._json_value(event.payload),
                            event.created_at,
                        ),
                    )
        return event

    def get_session(self, session_id: str) -> ExecutionSession | None:
        sid = str(session_id or "")
        if not sid:
            return None
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT session_id, intent_json, status, created_at, updated_at
                    FROM execution_sessions
                    WHERE session_id = %s
                    """,
                    (sid,),
                )
                row = cur.fetchone()
        if not row:
            return None
        return self._session_from_db_row(row)

    def events_for(self, session_id: str) -> list[ExecutionEvent]:
        sid = str(session_id or "")
        if not sid:
            return []
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT event_id, session_id, name, payload_json, created_at
                    FROM execution_events
                    WHERE session_id = %s
                    ORDER BY created_at ASC, event_id ASC
                    """,
                    (sid,),
                )
                rows = cur.fetchall()
        return [
            ExecutionEvent(
                event_id=str(event_id),
                session_id=str(found_sid),
                name=str(name),
                payload=dict(payload_json or {}),
                created_at=_to_iso(created_at),
            )
            for event_id, found_sid, name, payload_json, created_at in rows
        ]

    def start_step(
        self,
        session_id: str,
        step_kind: str,
        *,
        parent_step_id: str | None = None,
        input_json: dict[str, object] | None = None,
        correlation_id: str = "",
        causation_id: str = "",
        actor_type: str = "system",
        actor_id: str = "orchestrator",
        state: str = "queued",
    ) -> ExecutionStep:
        sid = str(session_id or "")
        if not sid or not self.get_session(sid):
            raise KeyError(f"unknown session: {sid}")
        ts = now_utc_iso()
        step = ExecutionStep(
            step_id=str(uuid.uuid4()),
            session_id=sid,
            parent_step_id=str(parent_step_id) if parent_step_id else None,
            step_kind=str(step_kind or "step"),
            state=str(state or "queued"),
            attempt_count=0,
            input_json=dict(input_json or {}),
            output_json={},
            error_json={},
            correlation_id=str(correlation_id or ""),
            causation_id=str(causation_id or ""),
            actor_type=str(actor_type or "system"),
            actor_id=str(actor_id or "orchestrator"),
            created_at=ts,
            updated_at=ts,
        )
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO execution_steps
                    (step_id, session_id, parent_step_id, step_kind, state, attempt_count, input_json, output_json, error_json,
                     correlation_id, causation_id, actor_type, actor_id, created_at, updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        step.step_id,
                        step.session_id,
                        step.parent_step_id,
                        step.step_kind,
                        step.state,
                        step.attempt_count,
                        self._json_value(step.input_json),
                        self._json_value(step.output_json),
                        self._json_value(step.error_json),
                        step.correlation_id,
                        step.causation_id,
                        step.actor_type,
                        step.actor_id,
                        step.created_at,
                        step.updated_at,
                    ),
                )
        return step

    def update_step(
        self,
        step_id: str,
        *,
        state: str,
        output_json: dict[str, object] | None = None,
        error_json: dict[str, object] | None = None,
        attempt_count: int | None = None,
    ) -> ExecutionStep | None:
        sid = str(step_id or "")
        if not sid:
            return None
        current = self.get_step(sid)
        if current is None:
            return None
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE execution_steps
                    SET state = %s,
                        output_json = %s,
                        error_json = %s,
                        attempt_count = COALESCE(%s, attempt_count),
                        updated_at = %s
                    WHERE step_id = %s
                    RETURNING step_id, session_id, parent_step_id, step_kind, state, attempt_count, input_json, output_json, error_json,
                              correlation_id, causation_id, actor_type, actor_id, created_at, updated_at
                    """,
                    (
                        str(state or "completed"),
                        self._json_value(current.output_json if output_json is None else dict(output_json)),
                        self._json_value(current.error_json if error_json is None else dict(error_json)),
                        max(0, int(attempt_count)) if attempt_count is not None else None,
                        now_utc_iso(),
                        sid,
                    ),
                )
                row = cur.fetchone()
        if not row:
            return None
        return self._step_from_db_row(row)

    def steps_for(self, session_id: str) -> list[ExecutionStep]:
        sid = str(session_id or "")
        if not sid:
            return []
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT step_id, session_id, parent_step_id, step_kind, state, attempt_count, input_json, output_json, error_json,
                           correlation_id, causation_id, actor_type, actor_id, created_at, updated_at
                    FROM execution_steps
                    WHERE session_id = %s
                    ORDER BY created_at ASC, step_id ASC
                    """,
                    (sid,),
                )
                rows = cur.fetchall()
        return [self._step_from_db_row(row) for row in rows]

    def get_step(self, step_id: str) -> ExecutionStep | None:
        sid = str(step_id or "")
        if not sid:
            return None
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT step_id, session_id, parent_step_id, step_kind, state, attempt_count, input_json, output_json, error_json,
                           correlation_id, causation_id, actor_type, actor_id, created_at, updated_at
                    FROM execution_steps
                    WHERE step_id = %s
                    """,
                    (sid,),
                )
                row = cur.fetchone()
        if not row:
            return None
        return self._step_from_db_row(row)

    def enqueue_step(
        self,
        session_id: str,
        step_id: str,
        *,
        idempotency_key: str,
        next_attempt_at: str | None = None,
    ) -> ExecutionQueueItem:
        sid = str(session_id or "")
        stid = str(step_id or "")
        key = str(idempotency_key or "")
        if not sid or not self.get_session(sid):
            raise KeyError(f"unknown session: {sid}")
        step = self.get_step(stid)
        if step is None or step.session_id != sid:
            raise KeyError(f"unknown step for session: {stid}")
        if not key:
            raise ValueError("idempotency_key is required")
        ts = now_utc_iso()
        queue_id = str(uuid.uuid4())
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO execution_queue
                    (queue_id, session_id, step_id, state, lease_owner, lease_expires_at, attempt_count, next_attempt_at,
                     idempotency_key, last_error, created_at, updated_at)
                    VALUES (%s, %s, %s, 'queued', '', NULL, %s, %s, %s, '', %s, %s)
                    ON CONFLICT (idempotency_key) DO UPDATE
                    SET updated_at = execution_queue.updated_at
                    RETURNING queue_id, session_id, step_id, state, lease_owner, lease_expires_at, attempt_count, next_attempt_at,
                              idempotency_key, last_error, created_at, updated_at
                    """,
                    (queue_id, sid, stid, max(0, int(step.attempt_count)), next_attempt_at, key, ts, ts),
                )
                row = cur.fetchone()
        if not row:
            raise RuntimeError("failed to enqueue execution step")
        return self._queue_from_db_row(row)

    def lease_queue_item(self, queue_id: str, *, lease_owner: str, lease_seconds: int = 60) -> ExecutionQueueItem | None:
        qid = str(queue_id or "")
        if not qid:
            return None
        now = datetime.now(timezone.utc)
        lease_expires = (now + timedelta(seconds=max(1, int(lease_seconds)))).isoformat()
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE execution_queue
                    SET state = 'leased',
                        lease_owner = %s,
                        lease_expires_at = %s,
                        attempt_count = CASE
                            WHEN execution_queue.attempt_count > 0 AND COALESCE(execution_queue.last_error, '') = '' THEN execution_queue.attempt_count
                            ELSE execution_queue.attempt_count + 1
                        END,
                        updated_at = %s
                    FROM execution_sessions
                    WHERE execution_queue.queue_id = %s
                      AND execution_sessions.session_id = execution_queue.session_id
                      AND execution_sessions.status IN ('running', 'queued')
                      AND (
                        (execution_queue.state = 'queued' AND (execution_queue.next_attempt_at IS NULL OR execution_queue.next_attempt_at <= %s))
                        OR (
                            execution_queue.state = 'leased'
                            AND execution_queue.lease_expires_at IS NOT NULL
                            AND execution_queue.lease_expires_at <= %s
                        )
                      )
                    RETURNING execution_queue.queue_id, execution_queue.session_id, execution_queue.step_id, execution_queue.state,
                              execution_queue.lease_owner, execution_queue.lease_expires_at, execution_queue.attempt_count,
                              execution_queue.next_attempt_at, execution_queue.idempotency_key, execution_queue.last_error,
                              execution_queue.created_at, execution_queue.updated_at
                    """,
                    (str(lease_owner or "worker"), lease_expires, now.isoformat(), qid, now.isoformat(), now.isoformat()),
                )
                row = cur.fetchone()
        if not row:
            return None
        return self._queue_from_db_row(row)

    def lease_next_queue_item(self, *, lease_owner: str, lease_seconds: int = 60) -> ExecutionQueueItem | None:
        now = datetime.now(timezone.utc)
        lease_expires = (now + timedelta(seconds=max(1, int(lease_seconds)))).isoformat()
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    WITH candidate AS (
                        SELECT execution_queue.queue_id
                        FROM execution_queue
                        JOIN execution_sessions
                          ON execution_sessions.session_id = execution_queue.session_id
                        WHERE execution_sessions.status IN ('running', 'queued')
                          AND (
                            (execution_queue.state = 'queued' AND (execution_queue.next_attempt_at IS NULL OR execution_queue.next_attempt_at <= %s))
                            OR (
                                execution_queue.state = 'leased'
                                AND execution_queue.lease_expires_at IS NOT NULL
                                AND execution_queue.lease_expires_at <= %s
                            )
                          )
                        ORDER BY execution_queue.created_at ASC, execution_queue.queue_id ASC
                        LIMIT 1
                        FOR UPDATE SKIP LOCKED
                    )
                    UPDATE execution_queue
                    SET state = 'leased',
                        lease_owner = %s,
                        lease_expires_at = %s,
                        attempt_count = CASE
                            WHEN execution_queue.attempt_count > 0 AND COALESCE(execution_queue.last_error, '') = '' THEN execution_queue.attempt_count
                            ELSE execution_queue.attempt_count + 1
                        END,
                        updated_at = %s
                    FROM candidate
                    WHERE execution_queue.queue_id = candidate.queue_id
                    RETURNING execution_queue.queue_id, execution_queue.session_id, execution_queue.step_id, execution_queue.state,
                              execution_queue.lease_owner, execution_queue.lease_expires_at, execution_queue.attempt_count,
                              execution_queue.next_attempt_at, execution_queue.idempotency_key, execution_queue.last_error,
                              execution_queue.created_at, execution_queue.updated_at
                    """,
                    (
                        now.isoformat(),
                        now.isoformat(),
                        str(lease_owner or "worker"),
                        lease_expires,
                        now.isoformat(),
                    ),
                )
                row = cur.fetchone()
        if not row:
            return None
        return self._queue_from_db_row(row)

    def complete_queue_item(self, queue_id: str, *, state: str = "done") -> ExecutionQueueItem | None:
        qid = str(queue_id or "")
        if not qid:
            return None
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE execution_queue
                    SET state = %s,
                        lease_owner = '',
                        lease_expires_at = NULL,
                        last_error = '',
                        updated_at = %s
                    WHERE queue_id = %s
                    RETURNING queue_id, session_id, step_id, state, lease_owner, lease_expires_at, attempt_count, next_attempt_at,
                              idempotency_key, last_error, created_at, updated_at
                    """,
                    (str(state or "done"), now_utc_iso(), qid),
                )
                row = cur.fetchone()
        if not row:
            return None
        return self._queue_from_db_row(row)

    def fail_queue_item(self, queue_id: str, *, last_error: str) -> ExecutionQueueItem | None:
        qid = str(queue_id or "")
        if not qid:
            return None
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE execution_queue
                    SET state = 'failed',
                        lease_owner = '',
                        lease_expires_at = NULL,
                        last_error = %s,
                        updated_at = %s
                    WHERE queue_id = %s
                    RETURNING queue_id, session_id, step_id, state, lease_owner, lease_expires_at, attempt_count, next_attempt_at,
                              idempotency_key, last_error, created_at, updated_at
                    """,
                    (str(last_error or "execution_failed"), now_utc_iso(), qid),
                )
                row = cur.fetchone()
        if not row:
            return None
        return self._queue_from_db_row(row)

    def retry_queue_item(
        self,
        queue_id: str,
        *,
        last_error: str,
        next_attempt_at: str | None,
        lease_owner: str | None = None,
    ) -> ExecutionQueueItem | None:
        qid = str(queue_id or "")
        if not qid:
            return None
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE execution_queue
                    SET state = 'queued',
                        lease_owner = %s,
                        lease_expires_at = NULL,
                        last_error = %s,
                        next_attempt_at = %s,
                        updated_at = %s
                    WHERE queue_id = %s
                    RETURNING queue_id, session_id, step_id, state, lease_owner, lease_expires_at, attempt_count, next_attempt_at,
                              idempotency_key, last_error, created_at, updated_at
                    """,
                    (str(lease_owner or ""), str(last_error or "execution_failed"), next_attempt_at, now_utc_iso(), qid),
                )
                row = cur.fetchone()
        if not row:
            return None
        return self._queue_from_db_row(row)

    def queue_for_session(self, session_id: str) -> list[ExecutionQueueItem]:
        sid = str(session_id or "")
        if not sid:
            return []
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT queue_id, session_id, step_id, state, lease_owner, lease_expires_at, attempt_count, next_attempt_at,
                           idempotency_key, last_error, created_at, updated_at
                    FROM execution_queue
                    WHERE session_id = %s
                    ORDER BY created_at ASC, queue_id ASC
                    """,
                    (sid,),
                )
                rows = cur.fetchall()
        return [self._queue_from_db_row(row) for row in rows]

    def append_tool_receipt(
        self,
        session_id: str,
        step_id: str,
        tool_name: str,
        action_kind: str,
        target_ref: str,
        receipt_json: dict[str, object] | None = None,
    ) -> ToolReceipt:
        sid = str(session_id or "")
        stid = str(step_id or "")
        if not sid or not self.get_session(sid):
            raise KeyError(f"unknown session: {sid}")
        row = ToolReceipt(
            receipt_id=str(uuid.uuid4()),
            session_id=sid,
            step_id=stid,
            tool_name=str(tool_name or "tool"),
            action_kind=str(action_kind or "action"),
            target_ref=str(target_ref or ""),
            receipt_json=dict(receipt_json or {}),
            created_at=now_utc_iso(),
        )
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO tool_receipts
                    (receipt_id, session_id, step_id, tool_name, action_kind, target_ref, receipt_json, created_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        row.receipt_id,
                        row.session_id,
                        row.step_id,
                        row.tool_name,
                        row.action_kind,
                        row.target_ref,
                        self._json_value(row.receipt_json),
                        row.created_at,
                    ),
                )
        return row

    def receipts_for(self, session_id: str) -> list[ToolReceipt]:
        sid = str(session_id or "")
        if not sid:
            return []
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT receipt_id, session_id, step_id, tool_name, action_kind, target_ref, receipt_json, created_at
                    FROM tool_receipts
                    WHERE session_id = %s
                    ORDER BY created_at ASC, receipt_id ASC
                    """,
                    (sid,),
                )
                rows = cur.fetchall()
        return [self._receipt_from_db_row(row) for row in rows]

    def get_receipt(self, receipt_id: str) -> ToolReceipt | None:
        rid = str(receipt_id or "")
        if not rid:
            return None
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT receipt_id, session_id, step_id, tool_name, action_kind, target_ref, receipt_json, created_at
                    FROM tool_receipts
                    WHERE receipt_id = %s
                    """,
                    (rid,),
                )
                row = cur.fetchone()
        if not row:
            return None
        return self._receipt_from_db_row(row)

    def append_run_cost(
        self,
        session_id: str,
        model_name: str,
        *,
        tokens_in: int,
        tokens_out: int,
        cost_usd: float,
    ) -> RunCost:
        sid = str(session_id or "")
        if not sid or not self.get_session(sid):
            raise KeyError(f"unknown session: {sid}")
        row = RunCost(
            cost_id=str(uuid.uuid4()),
            session_id=sid,
            model_name=str(model_name or "unknown"),
            tokens_in=max(0, int(tokens_in)),
            tokens_out=max(0, int(tokens_out)),
            cost_usd=float(cost_usd),
            created_at=now_utc_iso(),
        )
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO run_costs
                    (cost_id, session_id, model_name, tokens_in, tokens_out, cost_usd, created_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        row.cost_id,
                        row.session_id,
                        row.model_name,
                        row.tokens_in,
                        row.tokens_out,
                        row.cost_usd,
                        row.created_at,
                    ),
                )
        return row

    def run_costs_for(self, session_id: str) -> list[RunCost]:
        sid = str(session_id or "")
        if not sid:
            return []
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT cost_id, session_id, model_name, tokens_in, tokens_out, cost_usd, created_at
                    FROM run_costs
                    WHERE session_id = %s
                    ORDER BY created_at ASC, cost_id ASC
                    """,
                    (sid,),
                )
                rows = cur.fetchall()
        return [self._cost_from_db_row(row) for row in rows]

    def get_run_cost(self, cost_id: str) -> RunCost | None:
        cid = str(cost_id or "")
        if not cid:
            return None
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT cost_id, session_id, model_name, tokens_in, tokens_out, cost_usd, created_at
                    FROM run_costs
                    WHERE cost_id = %s
                    """,
                    (cid,),
                )
                row = cur.fetchone()
        if not row:
            return None
        return self._cost_from_db_row(row)
