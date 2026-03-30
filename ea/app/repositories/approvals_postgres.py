from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from app.domain.models import ApprovalDecision, ApprovalRequest, now_utc_iso


def _to_iso(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value or "")


def _expiry(minutes: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(minutes=max(1, int(minutes)))).isoformat()


class PostgresApprovalRepository:
    def __init__(self, database_url: str, default_ttl_minutes: int = 120) -> None:
        self._database_url = str(database_url or "").strip()
        if not self._database_url:
            raise ValueError("database_url is required for PostgresApprovalRepository")
        self._default_ttl_minutes = max(1, int(default_ttl_minutes))
        self._ensure_schema()

    def _connect(self):  # type: ignore[no-untyped-def]
        try:
            import psycopg
        except Exception as exc:  # pragma: no cover - import guard
            raise RuntimeError("psycopg is required for postgres approval backend") from exc
        return psycopg.connect(self._database_url, autocommit=True)

    def _json_value(self, value: dict[str, Any]):  # type: ignore[no-untyped-def]
        from psycopg.types.json import Json

        return Json(value)

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

    def _ensure_schema(self) -> None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS approval_requests (
                        approval_id TEXT PRIMARY KEY,
                        session_id TEXT NOT NULL,
                        step_id TEXT NOT NULL,
                        reason TEXT NOT NULL,
                        requested_action_json JSONB NOT NULL,
                        status TEXT NOT NULL,
                        expires_at TIMESTAMPTZ NULL,
                        created_at TIMESTAMPTZ NOT NULL,
                        updated_at TIMESTAMPTZ NOT NULL
                    )
                    """
                )
                cur.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_approval_requests_status_created
                    ON approval_requests(status, created_at DESC)
                    """
                )
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS approval_decisions (
                        decision_id TEXT PRIMARY KEY,
                        approval_id TEXT NOT NULL REFERENCES approval_requests(approval_id) ON DELETE CASCADE,
                        session_id TEXT NOT NULL,
                        step_id TEXT NOT NULL,
                        decision TEXT NOT NULL,
                        decided_by TEXT NOT NULL,
                        reason TEXT NOT NULL,
                        created_at TIMESTAMPTZ NOT NULL
                    )
                    """
                )
                cur.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_approval_decisions_session_created
                    ON approval_decisions(session_id, created_at DESC)
                    """
                )
                self._approval_request_columns = self._table_columns(cur, "approval_requests")
                self._approval_decision_columns = self._table_columns(cur, "approval_decisions")

    def _append_decision(self, cur, request: ApprovalRequest, *, decision: str, decided_by: str, reason: str) -> ApprovalDecision:  # type: ignore[no-untyped-def]
        row = ApprovalDecision(
            decision_id=str(uuid.uuid4()),
            approval_id=request.approval_id,
            session_id=request.session_id,
            step_id=request.step_id,
            decision=str(decision or ""),
            decided_by=str(decided_by or "unknown"),
            reason=str(reason or ""),
            created_at=now_utc_iso(),
        )
        decision_columns = set(getattr(self, "_approval_decision_columns", set()))
        request_columns = set(getattr(self, "_approval_request_columns", set()))
        legacy_request_id = None
        if "approval_request_id" in decision_columns and "approval_request_id" in request_columns:
            cur.execute(
                """
                SELECT approval_request_id
                FROM approval_requests
                WHERE approval_id = %s
                """,
                (request.approval_id,),
            )
            legacy_row = cur.fetchone()
            legacy_request_id = legacy_row[0] if legacy_row else None
            if legacy_request_id is None:
                raise KeyError(f"missing legacy approval_request_id for approval_id={request.approval_id}")

        if "approval_request_id" in decision_columns and "decision_payload_json" in decision_columns:
            cur.execute(
                """
                INSERT INTO approval_decisions
                (decision_id, approval_id, session_id, step_id, decision, decided_by, reason, created_at, approval_request_id, decision_payload_json)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    row.decision_id,
                    row.approval_id,
                    row.session_id,
                    row.step_id,
                    row.decision,
                    row.decided_by,
                    row.reason,
                    row.created_at,
                    legacy_request_id,
                    self._json_value({"decision": row.decision, "decided_by": row.decided_by, "reason": row.reason}),
                ),
            )
        elif "approval_request_id" in decision_columns:
            cur.execute(
                """
                INSERT INTO approval_decisions
                (decision_id, approval_id, session_id, step_id, decision, decided_by, reason, created_at, approval_request_id)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    row.decision_id,
                    row.approval_id,
                    row.session_id,
                    row.step_id,
                    row.decision,
                    row.decided_by,
                    row.reason,
                    row.created_at,
                    legacy_request_id,
                ),
            )
        else:
            cur.execute(
                """
                INSERT INTO approval_decisions
                (decision_id, approval_id, session_id, step_id, decision, decided_by, reason, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    row.decision_id,
                    row.approval_id,
                    row.session_id,
                    row.step_id,
                    row.decision,
                    row.decided_by,
                    row.reason,
                    row.created_at,
                ),
            )
        return row

    def _expire_pending(self, cur) -> int:  # type: ignore[no-untyped-def]
        cur.execute(
            """
            UPDATE approval_requests
            SET status = 'expired', updated_at = %s
            WHERE status = 'pending' AND expires_at IS NOT NULL AND expires_at <= NOW()
            RETURNING approval_id, session_id, step_id, reason, requested_action_json, status, expires_at, created_at, updated_at
            """,
            (now_utc_iso(),),
        )
        rows = cur.fetchall()
        for row in rows:
            request = self._request_from_row(row)
            self._append_decision(
                cur,
                request,
                decision="expired",
                decided_by="system",
                reason="approval_ttl_expired",
            )
        return len(rows)

    def _request_from_row(self, row: tuple[Any, ...]) -> ApprovalRequest:
        approval_id, session_id, step_id, reason, requested_action_json, status, expires_at, created_at, updated_at = row
        return ApprovalRequest(
            approval_id=str(approval_id),
            session_id=str(session_id),
            step_id=str(step_id),
            reason=str(reason),
            requested_action_json=dict(requested_action_json or {}),
            status=str(status),
            expires_at=_to_iso(expires_at) if expires_at else None,
            created_at=_to_iso(created_at),
            updated_at=_to_iso(updated_at),
        )

    def _decision_from_row(self, row: tuple[Any, ...]) -> ApprovalDecision:
        decision_id, approval_id, session_id, step_id, decision, decided_by, reason, created_at = row
        return ApprovalDecision(
            decision_id=str(decision_id),
            approval_id=str(approval_id),
            session_id=str(session_id),
            step_id=str(step_id),
            decision=str(decision),
            decided_by=str(decided_by),
            reason=str(reason),
            created_at=_to_iso(created_at),
        )

    def create_request(
        self,
        session_id: str,
        step_id: str,
        reason: str,
        requested_action_json: dict[str, object] | None = None,
        *,
        expires_at: str | None = None,
    ) -> ApprovalRequest:
        now = now_utc_iso()
        row = ApprovalRequest(
            approval_id=str(uuid.uuid4()),
            session_id=str(session_id or ""),
            step_id=str(step_id or ""),
            reason=str(reason or "approval_required"),
            requested_action_json=dict(requested_action_json or {}),
            status="pending",
            expires_at=str(expires_at or _expiry(self._default_ttl_minutes)),
            created_at=now,
            updated_at=now,
        )
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO approval_requests
                    (approval_id, session_id, step_id, reason, requested_action_json, status, expires_at, created_at, updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        row.approval_id,
                        row.session_id,
                        row.step_id,
                        row.reason,
                        self._json_value(row.requested_action_json),
                        row.status,
                        row.expires_at,
                        row.created_at,
                        row.updated_at,
                    ),
                )
        return row

    def list_pending(self, limit: int = 50) -> list[ApprovalRequest]:
        n = max(1, min(500, int(limit or 50)))
        with self._connect() as conn:
            with conn.cursor() as cur:
                self._expire_pending(cur)
                cur.execute(
                    """
                    SELECT approval_id, session_id, step_id, reason, requested_action_json, status, expires_at, created_at, updated_at
                    FROM approval_requests
                    WHERE status = 'pending'
                    ORDER BY created_at DESC, approval_id DESC
                    LIMIT %s
                    """,
                    (n,),
                )
                rows = cur.fetchall()
        return [self._request_from_row(row) for row in rows]

    def get_request(self, approval_id: str) -> ApprovalRequest | None:
        aid = str(approval_id or "").strip()
        if not aid:
            return None
        with self._connect() as conn:
            with conn.cursor() as cur:
                self._expire_pending(cur)
                cur.execute(
                    """
                    SELECT approval_id, session_id, step_id, reason, requested_action_json, status, expires_at, created_at, updated_at
                    FROM approval_requests
                    WHERE approval_id = %s
                    """,
                    (aid,),
                )
                row = cur.fetchone()
        if row is None:
            return None
        return self._request_from_row(row)

    def list_history(self, limit: int = 50, session_id: str | None = None) -> list[ApprovalDecision]:
        n = max(1, min(500, int(limit or 50)))
        sid = str(session_id or "").strip()
        with self._connect() as conn:
            with conn.cursor() as cur:
                if sid:
                    cur.execute(
                        """
                        SELECT decision_id, approval_id, session_id, step_id, decision, decided_by, reason, created_at
                        FROM approval_decisions
                        WHERE session_id = %s
                        ORDER BY created_at DESC, decision_id DESC
                        LIMIT %s
                        """,
                        (sid, n),
                    )
                else:
                    cur.execute(
                        """
                        SELECT decision_id, approval_id, session_id, step_id, decision, decided_by, reason, created_at
                        FROM approval_decisions
                        ORDER BY created_at DESC, decision_id DESC
                        LIMIT %s
                        """,
                        (n,),
                    )
                rows = cur.fetchall()
        return [self._decision_from_row(row) for row in rows]

    def decide(
        self,
        approval_id: str,
        *,
        decision: str,
        decided_by: str,
        reason: str,
    ) -> tuple[ApprovalRequest, ApprovalDecision] | None:
        aid = str(approval_id or "")
        if not aid:
            return None
        normalized_decision = str(decision or "").strip().lower()
        if normalized_decision in {"approve", "approved"}:
            status = "approved"
        elif normalized_decision in {"expire", "expired"}:
            status = "expired"
        else:
            status = "denied"
        with self._connect() as conn:
            with conn.cursor() as cur:
                self._expire_pending(cur)
                cur.execute(
                    """
                    UPDATE approval_requests
                    SET status = %s, updated_at = %s
                    WHERE approval_id = %s AND status = 'pending'
                    RETURNING approval_id, session_id, step_id, reason, requested_action_json, status, expires_at, created_at, updated_at
                    """,
                    (status, now_utc_iso(), aid),
                )
                req_row = cur.fetchone()
                if not req_row:
                    return None
                request = self._request_from_row(req_row)
                request_columns = set(getattr(self, "_approval_request_columns", set()))
                if "request_status" in request_columns or "decided_at" in request_columns:
                    update_parts: list[str] = []
                    update_params: list[object] = []
                    if "request_status" in request_columns:
                        update_parts.append("request_status = %s")
                        update_params.append(status)
                    if "decided_at" in request_columns:
                        update_parts.append(
                            """
                            decided_at = CASE
                                WHEN %s IN ('approved', 'expired', 'denied') THEN COALESCE(decided_at, %s)
                                ELSE decided_at
                            END
                            """
                        )
                        update_params.extend((status, now_utc_iso()))
                    cur.execute(
                        f"""
                        UPDATE approval_requests
                        SET {", ".join(update_parts)}
                        WHERE approval_id = %s
                        """,
                        tuple(update_params + [aid]),
                    )
                decision_row = self._append_decision(
                    cur,
                    request,
                    decision=status,
                    decided_by=decided_by,
                    reason=reason,
                )
        return request, decision_row

    def expire(
        self,
        approval_id: str,
        *,
        decided_by: str,
        reason: str,
    ) -> tuple[ApprovalRequest, ApprovalDecision] | None:
        return self.decide(
            approval_id,
            decision="expired",
            decided_by=decided_by,
            reason=reason,
        )
