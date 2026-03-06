from __future__ import annotations

import uuid
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Protocol

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


class ExecutionLedgerRepository(Protocol):
    def start_session(self, intent: IntentSpecV3) -> ExecutionSession:
        ...

    def complete_session(self, session_id: str, status: str = "completed") -> ExecutionSession | None:
        ...

    def append_event(self, session_id: str, name: str, payload: dict[str, object] | None = None) -> ExecutionEvent:
        ...

    def get_session(self, session_id: str) -> ExecutionSession | None:
        ...

    def events_for(self, session_id: str) -> list[ExecutionEvent]:
        ...

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
        ...

    def update_step(
        self,
        step_id: str,
        *,
        state: str,
        output_json: dict[str, object] | None = None,
        error_json: dict[str, object] | None = None,
        attempt_count: int | None = None,
    ) -> ExecutionStep | None:
        ...

    def steps_for(self, session_id: str) -> list[ExecutionStep]:
        ...

    def get_step(self, step_id: str) -> ExecutionStep | None:
        ...

    def enqueue_step(
        self,
        session_id: str,
        step_id: str,
        *,
        idempotency_key: str,
        next_attempt_at: str | None = None,
    ) -> ExecutionQueueItem:
        ...

    def lease_queue_item(self, queue_id: str, *, lease_owner: str, lease_seconds: int = 60) -> ExecutionQueueItem | None:
        ...

    def lease_next_queue_item(self, *, lease_owner: str, lease_seconds: int = 60) -> ExecutionQueueItem | None:
        ...

    def complete_queue_item(self, queue_id: str, *, state: str = "done") -> ExecutionQueueItem | None:
        ...

    def fail_queue_item(self, queue_id: str, *, last_error: str) -> ExecutionQueueItem | None:
        ...

    def queue_for_session(self, session_id: str) -> list[ExecutionQueueItem]:
        ...

    def append_tool_receipt(
        self,
        session_id: str,
        step_id: str,
        tool_name: str,
        action_kind: str,
        target_ref: str,
        receipt_json: dict[str, object] | None = None,
    ) -> ToolReceipt:
        ...

    def receipts_for(self, session_id: str) -> list[ToolReceipt]:
        ...

    def get_receipt(self, receipt_id: str) -> ToolReceipt | None:
        ...

    def append_run_cost(
        self,
        session_id: str,
        model_name: str,
        *,
        tokens_in: int,
        tokens_out: int,
        cost_usd: float,
    ) -> RunCost:
        ...

    def run_costs_for(self, session_id: str) -> list[RunCost]:
        ...

    def get_run_cost(self, cost_id: str) -> RunCost | None:
        ...


class InMemoryExecutionLedgerRepository:
    def __init__(self) -> None:
        self._sessions: Dict[str, ExecutionSession] = {}
        self._events: Dict[str, List[ExecutionEvent]] = {}
        self._steps: Dict[str, ExecutionStep] = {}
        self._step_order: Dict[str, List[str]] = {}
        self._queue_items: Dict[str, ExecutionQueueItem] = {}
        self._queue_order: Dict[str, List[str]] = {}
        self._queue_idempotency: Dict[str, str] = {}
        self._receipts: Dict[str, ToolReceipt] = {}
        self._receipt_order: Dict[str, List[str]] = {}
        self._costs: Dict[str, RunCost] = {}
        self._cost_order: Dict[str, List[str]] = {}

    def start_session(self, intent: IntentSpecV3) -> ExecutionSession:
        ts = now_utc_iso()
        session = ExecutionSession(
            session_id=str(uuid.uuid4()),
            intent=intent,
            status="running",
            created_at=ts,
            updated_at=ts,
        )
        self._sessions[session.session_id] = session
        self._events[session.session_id] = []
        self._step_order[session.session_id] = []
        self._queue_order[session.session_id] = []
        self._receipt_order[session.session_id] = []
        self._cost_order[session.session_id] = []
        return session

    def complete_session(self, session_id: str, status: str = "completed") -> ExecutionSession | None:
        session = self._sessions.get(str(session_id or ""))
        if not session:
            return None
        updated = replace(session, status=str(status or "completed"), updated_at=now_utc_iso())
        self._sessions[updated.session_id] = updated
        return updated

    def append_event(self, session_id: str, name: str, payload: dict[str, object] | None = None) -> ExecutionEvent:
        sid = str(session_id or "")
        if sid not in self._sessions:
            raise KeyError(f"unknown session: {sid}")
        event = ExecutionEvent(
            event_id=str(uuid.uuid4()),
            session_id=sid,
            name=str(name or "event"),
            payload=dict(payload or {}),
            created_at=now_utc_iso(),
        )
        self._events[sid].append(event)
        return event

    def get_session(self, session_id: str) -> ExecutionSession | None:
        return self._sessions.get(str(session_id or ""))

    def events_for(self, session_id: str) -> list[ExecutionEvent]:
        return list(self._events.get(str(session_id or ""), []))

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
        if sid not in self._sessions:
            raise KeyError(f"unknown session: {sid}")
        ts = now_utc_iso()
        step = ExecutionStep(
            step_id=str(uuid.uuid4()),
            session_id=sid,
            parent_step_id=parent_step_id,
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
        self._steps[step.step_id] = step
        self._step_order.setdefault(sid, []).append(step.step_id)
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
        step = self._steps.get(sid)
        if not step:
            return None
        updated = replace(
            step,
            state=str(state or step.state),
            output_json=step.output_json if output_json is None else dict(output_json),
            error_json=step.error_json if error_json is None else dict(error_json),
            attempt_count=step.attempt_count if attempt_count is None else max(0, int(attempt_count)),
            updated_at=now_utc_iso(),
        )
        self._steps[updated.step_id] = updated
        return updated

    def steps_for(self, session_id: str) -> list[ExecutionStep]:
        sid = str(session_id or "")
        return [self._steps[i] for i in self._step_order.get(sid, []) if i in self._steps]

    def get_step(self, step_id: str) -> ExecutionStep | None:
        return self._steps.get(str(step_id or ""))

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
        if sid not in self._sessions:
            raise KeyError(f"unknown session: {sid}")
        step = self._steps.get(stid)
        if not step or step.session_id != sid:
            raise KeyError(f"unknown step for session: {step_id}")
        existing_id = self._queue_idempotency.get(key)
        if existing_id:
            existing = self._queue_items.get(existing_id)
            if existing is not None:
                return existing
        ts = now_utc_iso()
        row = ExecutionQueueItem(
            queue_id=str(uuid.uuid4()),
            session_id=sid,
            step_id=stid,
            state="queued",
            lease_owner="",
            lease_expires_at=None,
            attempt_count=0,
            next_attempt_at=next_attempt_at,
            idempotency_key=key,
            last_error="",
            created_at=ts,
            updated_at=ts,
        )
        self._queue_items[row.queue_id] = row
        self._queue_order.setdefault(sid, []).append(row.queue_id)
        self._queue_idempotency[key] = row.queue_id
        return row

    def _eligible_queue_item_ids(self) -> list[str]:
        now = datetime.now(timezone.utc)
        eligible: list[str] = []
        for queue_id, row in self._queue_items.items():
            if row.state == "queued":
                if row.next_attempt_at:
                    try:
                        if datetime.fromisoformat(row.next_attempt_at) > now:
                            continue
                    except ValueError:
                        pass
                eligible.append(queue_id)
                continue
            if row.state == "leased" and row.lease_expires_at:
                try:
                    if datetime.fromisoformat(row.lease_expires_at) <= now:
                        eligible.append(queue_id)
                except ValueError:
                    continue
        return eligible

    def lease_queue_item(self, queue_id: str, *, lease_owner: str, lease_seconds: int = 60) -> ExecutionQueueItem | None:
        qid = str(queue_id or "")
        row = self._queue_items.get(qid)
        if not row:
            return None
        if qid not in self._eligible_queue_item_ids():
            return None
        now = datetime.now(timezone.utc)
        leased = replace(
            row,
            state="leased",
            lease_owner=str(lease_owner or "worker"),
            lease_expires_at=(now + timedelta(seconds=max(1, int(lease_seconds)))).isoformat(),
            attempt_count=row.attempt_count + 1,
            updated_at=now.isoformat(),
        )
        self._queue_items[qid] = leased
        return leased

    def lease_next_queue_item(self, *, lease_owner: str, lease_seconds: int = 60) -> ExecutionQueueItem | None:
        eligible = sorted(
            (
                self._queue_items[qid]
                for qid in self._eligible_queue_item_ids()
            ),
            key=lambda row: (row.created_at, row.queue_id),
        )
        if not eligible:
            return None
        return self.lease_queue_item(eligible[0].queue_id, lease_owner=lease_owner, lease_seconds=lease_seconds)

    def complete_queue_item(self, queue_id: str, *, state: str = "done") -> ExecutionQueueItem | None:
        qid = str(queue_id or "")
        row = self._queue_items.get(qid)
        if not row:
            return None
        updated = replace(
            row,
            state=str(state or "done"),
            lease_owner="",
            lease_expires_at=None,
            last_error="",
            updated_at=now_utc_iso(),
        )
        self._queue_items[qid] = updated
        return updated

    def fail_queue_item(self, queue_id: str, *, last_error: str) -> ExecutionQueueItem | None:
        qid = str(queue_id or "")
        row = self._queue_items.get(qid)
        if not row:
            return None
        updated = replace(
            row,
            state="failed",
            lease_owner="",
            lease_expires_at=None,
            last_error=str(last_error or "execution_failed"),
            updated_at=now_utc_iso(),
        )
        self._queue_items[qid] = updated
        return updated

    def queue_for_session(self, session_id: str) -> list[ExecutionQueueItem]:
        sid = str(session_id or "")
        return [self._queue_items[i] for i in self._queue_order.get(sid, []) if i in self._queue_items]

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
        if sid not in self._sessions:
            raise KeyError(f"unknown session: {sid}")
        step = self._steps.get(str(step_id or ""))
        if not step or step.session_id != sid:
            raise KeyError(f"unknown step for session: {step_id}")
        row = ToolReceipt(
            receipt_id=str(uuid.uuid4()),
            session_id=sid,
            step_id=step.step_id,
            tool_name=str(tool_name or "tool"),
            action_kind=str(action_kind or "action"),
            target_ref=str(target_ref or ""),
            receipt_json=dict(receipt_json or {}),
            created_at=now_utc_iso(),
        )
        self._receipts[row.receipt_id] = row
        self._receipt_order.setdefault(sid, []).append(row.receipt_id)
        return row

    def receipts_for(self, session_id: str) -> list[ToolReceipt]:
        sid = str(session_id or "")
        return [self._receipts[i] for i in self._receipt_order.get(sid, []) if i in self._receipts]

    def get_receipt(self, receipt_id: str) -> ToolReceipt | None:
        return self._receipts.get(str(receipt_id or ""))

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
        if sid not in self._sessions:
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
        self._costs[row.cost_id] = row
        self._cost_order.setdefault(sid, []).append(row.cost_id)
        return row

    def run_costs_for(self, session_id: str) -> list[RunCost]:
        sid = str(session_id or "")
        return [self._costs[i] for i in self._cost_order.get(sid, []) if i in self._costs]

    def get_run_cost(self, cost_id: str) -> RunCost | None:
        return self._costs.get(str(cost_id or ""))
