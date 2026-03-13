from __future__ import annotations

import uuid
from dataclasses import replace
from datetime import datetime, timezone
from typing import Dict, List, Protocol

from app.domain.models import HumanTask, now_utc_iso


def _parse_assignment_source_filter(value: str | None) -> tuple[bool, str]:
    raw = str(value or "").strip()
    if not raw:
        return False, ""
    if raw.lower() in {"none", "unassigned", "ownerless"}:
        return True, ""
    return True, raw


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
        authority_required: str = "",
        why_human: str = "",
        quality_rubric_json: dict[str, object] | None = None,
        input_json: dict[str, object] | None = None,
        desired_output_json: dict[str, object] | None = None,
        priority: str = "normal",
        sla_due_at: str | None = None,
        resume_session_on_return: bool = False,
    ) -> HumanTask:
        ...

    def get(self, human_task_id: str) -> HumanTask | None:
        ...

    def list_for_principal(
        self,
        principal_id: str,
        *,
        status: str | None = None,
        role_required: str | None = None,
        priority: str | None = None,
        assigned_operator_id: str | None = None,
        assignment_state: str | None = None,
        assignment_source: str | None = None,
        overdue_only: bool = False,
        limit: int = 50,
    ) -> list[HumanTask]:
        ...

    def list_for_session(self, session_id: str, *, limit: int = 200) -> list[HumanTask]:
        ...

    def count_by_priority_for_principal(
        self,
        principal_id: str,
        *,
        status: str | None = None,
        role_required: str | None = None,
        assigned_operator_id: str | None = None,
        assignment_state: str | None = None,
        assignment_source: str | None = None,
        overdue_only: bool = False,
    ) -> dict[str, int]:
        ...

    def claim(
        self,
        human_task_id: str,
        *,
        operator_id: str,
        assigned_by_actor_id: str | None = None,
    ) -> HumanTask | None:
        ...

    def assign(
        self,
        human_task_id: str,
        *,
        operator_id: str,
        assignment_source: str = "manual",
        assigned_by_actor_id: str | None = None,
    ) -> HumanTask | None:
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
        authority_required: str = "",
        why_human: str = "",
        quality_rubric_json: dict[str, object] | None = None,
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
            authority_required=str(authority_required or ""),
            why_human=str(why_human or ""),
            quality_rubric_json=dict(quality_rubric_json or {}),
            input_json=dict(input_json or {}),
            desired_output_json=dict(desired_output_json or {}),
            priority=str(priority or "normal"),
            sla_due_at=str(sla_due_at) if sla_due_at else None,
            status="pending",
            assignment_state="unassigned",
            assigned_operator_id="",
            assignment_source="",
            assigned_at=None,
            assigned_by_actor_id="",
            resolution="",
            created_at=ts,
            updated_at=ts,
            resume_session_on_return=bool(resume_session_on_return),
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
        role_required: str | None = None,
        priority: str | None = None,
        assigned_operator_id: str | None = None,
        assignment_state: str | None = None,
        assignment_source: str | None = None,
        overdue_only: bool = False,
        limit: int = 50,
    ) -> list[HumanTask]:
        principal = str(principal_id or "")
        status_filter = str(status or "").strip()
        role_filter = str(role_required or "").strip()
        priority_filters = {
            value.strip().lower()
            for value in str(priority or "").split(",")
            if value.strip()
        }
        operator_filter = str(assigned_operator_id or "").strip()
        assignment_filter = str(assignment_state or "").strip().lower()
        has_source_filter, source_filter = _parse_assignment_source_filter(assignment_source)
        raw_limit = int(limit or 0)
        n = max(1, min(500, raw_limit)) if raw_limit > 0 else 0
        rows = [self._rows[row_id] for row_id in reversed(self._order) if row_id in self._rows]
        rows = [row for row in rows if row.principal_id == principal]
        if status_filter:
            rows = [row for row in rows if row.status == status_filter]
        if role_filter:
            rows = [row for row in rows if row.role_required == role_filter]
        if priority_filters:
            rows = [row for row in rows if str(row.priority or "").strip().lower() in priority_filters]
        if operator_filter:
            rows = [row for row in rows if row.assigned_operator_id == operator_filter]
        if assignment_filter:
            rows = [row for row in rows if row.assignment_state == assignment_filter]
        if has_source_filter:
            rows = [row for row in rows if row.assignment_source == source_filter]
        if overdue_only:
            now = datetime.now(timezone.utc)
            overdue_rows: list[HumanTask] = []
            for row in rows:
                raw = str(row.sla_due_at or "").strip()
                if not raw:
                    continue
                try:
                    due = datetime.fromisoformat(raw)
                except ValueError:
                    continue
                if due.tzinfo is None:
                    due = due.replace(tzinfo=timezone.utc)
                if due <= now:
                    overdue_rows.append(row)
            rows = overdue_rows
        if n <= 0:
            return rows
        return rows[:n]

    def list_for_session(self, session_id: str, *, limit: int = 200) -> list[HumanTask]:
        session = str(session_id or "")
        n = max(1, min(1000, int(limit or 200)))
        rows = [self._rows[row_id] for row_id in self._order if row_id in self._rows]
        rows = [row for row in rows if row.session_id == session]
        return rows[:n]

    def count_by_priority_for_principal(
        self,
        principal_id: str,
        *,
        status: str | None = None,
        role_required: str | None = None,
        assigned_operator_id: str | None = None,
        assignment_state: str | None = None,
        assignment_source: str | None = None,
        overdue_only: bool = False,
    ) -> dict[str, int]:
        principal = str(principal_id or "")
        status_filter = str(status or "").strip()
        role_filter = str(role_required or "").strip()
        operator_filter = str(assigned_operator_id or "").strip()
        assignment_filter = str(assignment_state or "").strip().lower()
        has_source_filter, source_filter = _parse_assignment_source_filter(assignment_source)
        rows = [self._rows[row_id] for row_id in self._order if row_id in self._rows]
        rows = [row for row in rows if row.principal_id == principal]
        if status_filter:
            rows = [row for row in rows if row.status == status_filter]
        if role_filter:
            rows = [row for row in rows if row.role_required == role_filter]
        if operator_filter:
            rows = [row for row in rows if row.assigned_operator_id == operator_filter]
        if assignment_filter:
            rows = [row for row in rows if row.assignment_state == assignment_filter]
        if has_source_filter:
            rows = [row for row in rows if row.assignment_source == source_filter]
        if overdue_only:
            now = datetime.now(timezone.utc)
            overdue_rows: list[HumanTask] = []
            for row in rows:
                raw = str(row.sla_due_at or "").strip()
                if not raw:
                    continue
                try:
                    due = datetime.fromisoformat(raw)
                except ValueError:
                    continue
                if due.tzinfo is None:
                    due = due.replace(tzinfo=timezone.utc)
                if due <= now:
                    overdue_rows.append(row)
            rows = overdue_rows
        counts: dict[str, int] = {}
        for row in rows:
            key = str(row.priority or "").strip().lower() or "normal"
            counts[key] = counts.get(key, 0) + 1
        return counts

    def claim(
        self,
        human_task_id: str,
        *,
        operator_id: str,
        assigned_by_actor_id: str | None = None,
    ) -> HumanTask | None:
        found = self._rows.get(str(human_task_id or ""))
        if not found or found.status != "pending":
            return None
        updated = replace(
            found,
            status="claimed",
            assignment_state="claimed",
            assigned_operator_id=str(operator_id or ""),
            assignment_source=found.assignment_source,
            assigned_at=now_utc_iso(),
            assigned_by_actor_id=str(assigned_by_actor_id or operator_id or ""),
            updated_at=now_utc_iso(),
        )
        self._rows[updated.human_task_id] = updated
        return updated

    def assign(
        self,
        human_task_id: str,
        *,
        operator_id: str,
        assignment_source: str = "manual",
        assigned_by_actor_id: str | None = None,
    ) -> HumanTask | None:
        found = self._rows.get(str(human_task_id or ""))
        if not found or found.status not in {"pending", "claimed"}:
            return None
        updated = replace(
            found,
            assignment_state="assigned",
            assigned_operator_id=str(operator_id or ""),
            assignment_source=str(assignment_source or "manual"),
            assigned_at=now_utc_iso(),
            assigned_by_actor_id=str(assigned_by_actor_id or operator_id or ""),
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
            assignment_state="returned",
            assigned_operator_id=str(operator_id or found.assigned_operator_id or ""),
            assignment_source=found.assignment_source,
            assigned_at=found.assigned_at,
            assigned_by_actor_id=found.assigned_by_actor_id,
            resolution=str(resolution or ""),
            returned_payload_json=dict(returned_payload_json or {}),
            provenance_json=dict(provenance_json or {}),
            updated_at=now_utc_iso(),
        )
        self._rows[updated.human_task_id] = updated
        return updated
