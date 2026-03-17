from __future__ import annotations

from typing import Callable

from app.domain.models import ExecutionEvent, ExecutionSession, ExecutionStep, HumanTask, OperatorProfile
from app.repositories.human_tasks import _parse_assignment_source_filter
from app.services.human_task_routing_runtime_service import HumanTaskRoutingService
from app.services.operator_task_routing_service import OperatorTaskRoutingService


class ExecutionOperatorRoutingService:
    def __init__(
        self,
        *,
        human_task_routing: HumanTaskRoutingService,
        operator_task_routing: OperatorTaskRoutingService,
        get_session: Callable[[str], ExecutionSession | None],
        get_step: Callable[[str], ExecutionStep | None],
        update_step: Callable[[str, ...], object],
        append_event: Callable[[str, str, dict[str, object]], object],
        set_session_status: Callable[[str, str], object],
        create_human_task: Callable[..., HumanTask],
        require_session_principal_alignment: Callable[[ExecutionSession, str], object],
        fetch_human_task: Callable[[str], HumanTask | None],
        list_human_tasks_for_session: Callable[[str, int], list[HumanTask]],
        list_human_tasks_for_principal: Callable[..., list[HumanTask]],
        count_human_tasks_by_priority: Callable[..., dict[str, int]],
        fetch_session_for_principal: Callable[[str, str], ExecutionSession | None],
        fetch_operator_profile: Callable[[str, str], OperatorProfile | None],
    ) -> None:
        self._human_task_routing = human_task_routing
        self._operator_task_routing = operator_task_routing
        self._get_session = get_session
        self._get_step = get_step
        self._update_step = update_step
        self._append_event = append_event
        self._set_session_status = set_session_status
        self._create_human_task = create_human_task
        self._require_session_principal_alignment = require_session_principal_alignment
        self._fetch_human_task = fetch_human_task
        self._list_human_tasks_for_session = list_human_tasks_for_session
        self._list_human_tasks_for_principal = list_human_tasks_for_principal
        self._count_human_tasks_by_priority = count_human_tasks_by_priority
        self._fetch_session_for_principal = fetch_session_for_principal
        self._fetch_operator_profile = fetch_operator_profile

    def required_skill_tags(self, row: HumanTask) -> tuple[str, ...]:
        return self._human_task_routing.required_skill_tags(row)

    def required_trust_rank(self, authority_required: str) -> int:
        return self._human_task_routing.required_trust_rank(authority_required)

    def required_trust_tier(self, authority_required: str) -> str:
        return self._human_task_routing.required_trust_tier(authority_required)

    def operator_match_details(self, profile, row: HumanTask) -> dict[str, object]:
        return self._human_task_routing.operator_match_details(profile, row)

    def build_human_task_routing_hints(self, row: HumanTask) -> dict[str, object]:
        return self._human_task_routing.build_human_task_routing_hints(row)

    def human_task_assignment_events(self, row: HumanTask) -> list[ExecutionEvent]:
        return self._human_task_routing.human_task_assignment_events(row)

    def build_human_task_last_transition_summary(self, row: HumanTask) -> dict[str, object]:
        return self._human_task_routing.build_human_task_last_transition_summary(row)

    def decorate_human_task(self, row: HumanTask) -> HumanTask:
        return self._human_task_routing.decorate_human_task(row)

    def sort_human_tasks(
        self,
        rows: list[HumanTask],
        *,
        sort: str | None = None,
    ) -> list[HumanTask]:
        return self._human_task_routing.sort_human_tasks(rows, sort=sort)

    def filter_human_task_rows(
        self,
        rows: list[HumanTask],
        *,
        principal_id: str,
        status: str | None = None,
        role_required: str | None = None,
        priority: str | None = None,
        assigned_operator_id: str | None = None,
        assignment_state: str | None = None,
        assignment_source: str | None = None,
        overdue_only: bool = False,
    ) -> list[HumanTask]:
        return self._human_task_routing.filter_human_task_rows(
            rows,
            principal_id=principal_id,
            status=status,
            role_required=role_required,
            priority=priority,
            assigned_operator_id=assigned_operator_id,
            assignment_state=assignment_state,
            assignment_source=assignment_source,
            overdue_only=overdue_only,
        )

    def operator_matches_human_task(self, profile, row: HumanTask) -> bool:
        return self._human_task_routing.operator_matches_human_task(profile, row)

    def claim_human_task(
        self,
        human_task_id: str,
        *,
        principal_id: str,
        operator_id: str,
        assigned_by_actor_id: str | None = None,
    ) -> HumanTask | None:
        return self._operator_task_routing.claim_human_task(
            human_task_id,
            principal_id=principal_id,
            operator_id=operator_id,
            assigned_by_actor_id=assigned_by_actor_id,
        )

    def assign_human_task(
        self,
        human_task_id: str,
        *,
        principal_id: str,
        operator_id: str,
        assignment_source: str = "manual",
        assigned_by_actor_id: str | None = None,
    ) -> HumanTask | None:
        return self._operator_task_routing.assign_human_task(
            human_task_id,
            principal_id=principal_id,
            operator_id=operator_id,
            assignment_source=assignment_source,
            assigned_by_actor_id=assigned_by_actor_id,
        )

    def return_human_task(
        self,
        found: HumanTask,
        *,
        principal_id: str,
        operator_id: str,
        resolution: str,
        returned_payload_json: dict[str, object] | None = None,
        provenance_json: dict[str, object] | None = None,
    ) -> HumanTask | None:
        return self._operator_task_routing.return_human_task(
            found,
            principal_id=principal_id,
            operator_id=operator_id,
            resolution=resolution,
            returned_payload_json=returned_payload_json,
            provenance_json=provenance_json,
        )

    def return_human_task_by_id(
        self,
        human_task_id: str,
        *,
        principal_id: str,
        operator_id: str,
        resolution: str,
        returned_payload_json: dict[str, object] | None = None,
        provenance_json: dict[str, object] | None = None,
    ) -> HumanTask | None:
        found = self.fetch_human_task(human_task_id, principal_id=principal_id)
        if found is None:
            return None
        return self.return_human_task(
            found,
            principal_id=principal_id,
            operator_id=operator_id,
            resolution=resolution,
            returned_payload_json=returned_payload_json,
            provenance_json=provenance_json,
        )

    def create_human_task(
        self,
        *,
        session_id: str,
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
        step_id: str | None = None,
        resume_session_on_return: bool = False,
    ) -> HumanTask:
        session = self._get_session(session_id)
        if session is None:
            raise KeyError("session_not_found")
        self._require_session_principal_alignment(session, principal_id=principal_id)
        step: ExecutionStep | None = None
        if resume_session_on_return and not step_id:
            raise KeyError("step_id_required")
        if step_id:
            step = self._get_step(step_id)
            if step is None or step.session_id != session.session_id:
                raise KeyError("step_not_found")
        row = self._create_human_task(
            session_id=session.session_id,
            step_id=step_id,
            principal_id=principal_id,
            task_type=task_type,
            role_required=role_required,
            brief=brief,
            authority_required=authority_required,
            why_human=why_human,
            quality_rubric_json=quality_rubric_json,
            input_json=input_json,
            desired_output_json=desired_output_json,
            priority=priority,
            sla_due_at=sla_due_at,
            resume_session_on_return=resume_session_on_return,
        )
        if row.resume_session_on_return and step is not None:
            self._update_step(
                step.step_id,
                state="waiting_human",
                output_json=step.output_json,
                error_json={"reason": "human_task_required", "human_task_id": row.human_task_id},
                attempt_count=step.attempt_count,
            )
            self._set_session_status(session.session_id, "awaiting_human")
            self._append_event(
                session.session_id,
                "session_paused_for_human_task",
                {
                    "human_task_id": row.human_task_id,
                    "step_id": step.step_id,
                    "role_required": row.role_required,
                },
            )
        self._append_event(
            session.session_id,
            "human_task_created",
            {
                "human_task_id": row.human_task_id,
                "step_id": row.step_id or "",
                "task_type": row.task_type,
                "role_required": row.role_required,
                "authority_required": row.authority_required,
                "why_human": row.why_human,
                "quality_rubric_json": row.quality_rubric_json,
                "priority": row.priority,
                "sla_due_at": row.sla_due_at or "",
                "desired_output_json": row.desired_output_json,
                "assignment_state": row.assignment_state,
                "assigned_operator_id": row.assigned_operator_id,
                "assignment_source": row.assignment_source,
                "assigned_at": row.assigned_at or "",
                "assigned_by_actor_id": row.assigned_by_actor_id,
                "resume_session_on_return": row.resume_session_on_return,
            },
        )
        return self.decorate_human_task(row)

    def fetch_human_task(self, human_task_id: str, principal_id: str) -> HumanTask | None:
        found = self._fetch_human_task(human_task_id)
        if found is None or found.principal_id != str(principal_id or ""):
            return None
        return self.decorate_human_task(found)

    def list_human_tasks(
        self,
        *,
        principal_id: str,
        session_id: str | None = None,
        status: str | None = None,
        role_required: str | None = None,
        priority: str | None = None,
        assigned_operator_id: str | None = None,
        assignment_state: str | None = None,
        assignment_source: str | None = None,
        operator_id: str | None = None,
        overdue_only: bool = False,
        limit: int = 50,
        sort: str | None = None,
    ) -> list[HumanTask]:
        resolved_operator_id = str(operator_id or "").strip()
        session = str(session_id or "").strip()
        if session:
            if self._fetch_session_for_principal(session, principal_id=principal_id) is None:
                return []
            rows = self._list_human_tasks_for_session(session, limit=max(limit, 1))
            rows = self.filter_human_task_rows(
                rows,
                principal_id=principal_id,
                status=status,
                role_required=role_required,
                priority=priority,
                assigned_operator_id=assigned_operator_id,
                assignment_state=assignment_state,
                assignment_source=assignment_source,
                overdue_only=overdue_only,
            )
            decorated = [self.decorate_human_task(row) for row in rows]
            if not resolved_operator_id:
                return self.sort_human_tasks(decorated, sort=sort)
            profile = self._fetch_operator_profile(resolved_operator_id, principal_id=principal_id)
            if profile is None:
                return []
            return self.sort_human_tasks(
                [row for row in decorated if self.operator_matches_human_task(profile, row)],
                sort=sort,
            )

        rows = self._list_human_tasks_for_principal(
            principal_id,
            status=status,
            role_required=role_required,
            priority=priority,
            assigned_operator_id=assigned_operator_id,
            assignment_state=assignment_state,
            assignment_source=assignment_source,
            overdue_only=overdue_only,
            limit=limit,
        )
        if not resolved_operator_id:
            return self.sort_human_tasks(
                [self.decorate_human_task(row) for row in rows],
                sort=sort,
            )
        profile = self._fetch_operator_profile(resolved_operator_id, principal_id=principal_id)
        if profile is None:
            return []
        return self.sort_human_tasks(
            [
                self.decorate_human_task(row)
                for row in rows
                if self.operator_matches_human_task(profile, row)
            ],
            sort=sort,
        )

    def summarize_human_task_priorities(
        self,
        *,
        principal_id: str,
        status: str = "pending",
        role_required: str | None = None,
        operator_id: str | None = None,
        assigned_operator_id: str | None = None,
        assignment_state: str | None = None,
        assignment_source: str | None = None,
        overdue_only: bool = False,
    ) -> dict[str, object]:
        resolved_operator_id = str(operator_id or "").strip()
        requested_assignment_source = str(assignment_source or "").strip()
        if resolved_operator_id:
            profile = self._fetch_operator_profile(resolved_operator_id, principal_id=principal_id)
            if profile is None:
                counts: dict[str, int] = {}
            else:
                rows = self._list_human_tasks_for_principal(
                    principal_id,
                    status=status,
                    role_required=role_required,
                    assigned_operator_id=assigned_operator_id,
                    assignment_state=assignment_state,
                    assignment_source=assignment_source,
                    overdue_only=overdue_only,
                    limit=0,
                )
                counts = {}
                for row in rows:
                    if not self.operator_matches_human_task(profile, row):
                        continue
                    key = str(row.priority or "").strip().lower() or "normal"
                    counts[key] = counts.get(key, 0) + 1
        else:
            counts = self._count_human_tasks_by_priority(
                principal_id,
                status=status,
                role_required=role_required,
                assigned_operator_id=assigned_operator_id,
                assignment_state=assignment_state,
                assignment_source=assignment_source,
                overdue_only=overdue_only,
            )
        normalized = {
            "urgent": int(counts.get("urgent", 0)),
            "high": int(counts.get("high", 0)),
            "normal": int(counts.get("normal", 0)),
            "low": int(counts.get("low", 0)),
        }
        extra = {
            key: int(value)
            for key, value in counts.items()
            if key not in normalized
        }
        ordered = {**normalized, **dict(sorted(extra.items()))}
        highest_priority = next(
            (key for key in ("urgent", "high", "normal", "low") if ordered.get(key, 0) > 0),
            "",
        )
        return {
            "status": status,
            "role_required": str(role_required or ""),
            "operator_id": resolved_operator_id,
            "assigned_operator_id": str(assigned_operator_id or ""),
            "assignment_state": str(assignment_state or ""),
            "assignment_source": requested_assignment_source,
            "overdue_only": bool(overdue_only),
            "counts_json": ordered,
            "total": sum(ordered.values()),
            "highest_priority": highest_priority,
        }

    def list_human_task_assignment_history(
        self,
        human_task_id: str,
        *,
        principal_id: str,
        event_name: str | None = None,
        assigned_operator_id: str | None = None,
        assigned_by_actor_id: str | None = None,
        assignment_source: str | None = None,
        limit: int = 100,
    ) -> list[ExecutionEvent]:
        found = self.fetch_human_task(human_task_id, principal_id=principal_id)
        if found is None:
            return []
        event_filter = str(event_name or "").strip()
        operator_filter = str(assigned_operator_id or "").strip()
        actor_filter = str(assigned_by_actor_id or "").strip()
        has_source_filter, source_filter = _parse_assignment_source_filter(assignment_source)
        rows = self.human_task_assignment_events(found)
        if event_filter:
            rows = [event for event in rows if event.name == event_filter]
        if operator_filter:
            rows = [
                event
                for event in rows
                if str((event.payload or {}).get("assigned_operator_id") or (event.payload or {}).get("operator_id") or "")
                == operator_filter
            ]
        if actor_filter:
            rows = [
                event for event in rows if str((event.payload or {}).get("assigned_by_actor_id") or "") == actor_filter
            ]
        if has_source_filter:
            rows = [event for event in rows if str((event.payload or {}).get("assignment_source") or "") == source_filter]
        n = max(1, min(500, int(limit or 100)))
        if len(rows) <= n:
            return rows
        return rows[-n:]
