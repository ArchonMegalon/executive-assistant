from __future__ import annotations

import uuid
from dataclasses import replace
from typing import Dict, List, Protocol

from app.domain.models import HumanTask, now_utc_iso


class HumanTaskRepository(Protocol):
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
    ) -> HumanTask:
        ...

    def get(self, human_task_id: str) -> HumanTask | None:
        ...

    def list_for_principal(
        self,
        principal_id: str,
        *,
        status: str | None = None,
        limit: int = 50,
    ) -> list[HumanTask]:
        ...

    def list_for_session(self, session_id: str, *, limit: int = 200) -> list[HumanTask]:
        ...

    def claim(self, human_task_id: str, *, operator_id: str) -> HumanTask | None:
        ...

    def return_task(
        self,
        human_task_id: str,
        *,
        operator_id: str,
        resolution: str,
        returned_payload_json: dict[str, object] | None = None,
        provenance_json: dict[str, object] | None = None,
    ) -> HumanTask | None:
        ...


class InMemoryHumanTaskRepository:
    def __init__(self) -> None:
        self._rows: Dict[str, HumanTask] = {}
        self._order: List[str] = []

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
            returned_payload_json={},
            provenance_json={},
        )
        self._rows[row.human_task_id] = row
        self._order.append(row.human_task_id)
        return row

    def get(self, human_task_id: str) -> HumanTask | None:
        return self._rows.get(str(human_task_id or ""))

    def list_for_principal(
        self,
        principal_id: str,
        *,
        status: str | None = None,
        limit: int = 50,
    ) -> list[HumanTask]:
        principal = str(principal_id or "")
        status_filter = str(status or "").strip()
        n = max(1, min(500, int(limit or 50)))
        rows = [self._rows[row_id] for row_id in reversed(self._order) if row_id in self._rows]
        rows = [row for row in rows if row.principal_id == principal]
        if status_filter:
            rows = [row for row in rows if row.status == status_filter]
        return rows[:n]

    def list_for_session(self, session_id: str, *, limit: int = 200) -> list[HumanTask]:
        session = str(session_id or "")
        n = max(1, min(1000, int(limit or 200)))
        rows = [self._rows[row_id] for row_id in self._order if row_id in self._rows]
        rows = [row for row in rows if row.session_id == session]
        return rows[:n]

    def claim(self, human_task_id: str, *, operator_id: str) -> HumanTask | None:
        found = self._rows.get(str(human_task_id or ""))
        if not found or found.status != "pending":
            return None
        updated = replace(
            found,
            status="claimed",
            assigned_operator_id=str(operator_id or ""),
            updated_at=now_utc_iso(),
        )
        self._rows[updated.human_task_id] = updated
        return updated

    def return_task(
        self,
        human_task_id: str,
        *,
        operator_id: str,
        resolution: str,
        returned_payload_json: dict[str, object] | None = None,
        provenance_json: dict[str, object] | None = None,
    ) -> HumanTask | None:
        found = self._rows.get(str(human_task_id or ""))
        if not found or found.status not in {"pending", "claimed"}:
            return None
        updated = replace(
            found,
            status="returned",
            assigned_operator_id=str(operator_id or found.assigned_operator_id or ""),
            resolution=str(resolution or ""),
            returned_payload_json=dict(returned_payload_json or {}),
            provenance_json=dict(provenance_json or {}),
            updated_at=now_utc_iso(),
        )
        self._rows[updated.human_task_id] = updated
        return updated
