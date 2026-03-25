from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING

from app.domain.models import ApprovalRequest, Commitment, DecisionWindow, DeadlineWindow, FollowUp, HumanTask, Stakeholder
from app.product.commercial import workspace_plan_for_mode
from app.product.models import (
    BriefItem,
    CommitmentItem,
    DecisionQueueItem,
    DraftCandidate,
    EvidenceRef,
    HandoffNote,
    PersonDetail,
    PersonProfile,
    ProductSnapshot,
)

if TYPE_CHECKING:
    from app.container import AppContainer


_TERMINAL_STATUSES = {"done", "closed", "completed", "resolved", "cancelled", "canceled", "dropped", "rejected"}
_PRIORITY_WEIGHTS = {
    "critical": 100,
    "urgent": 90,
    "high": 80,
    "medium": 60,
    "normal": 50,
    "low": 30,
}
_TEMPERATURE_BY_IMPORTANCE = {
    "critical": "hot",
    "high": "warm",
    "medium": "steady",
    "low": "cool",
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_when(value: str | None) -> datetime | None:
    normalized = str(value or "").strip()
    if not normalized:
        return None
    try:
        return datetime.fromisoformat(normalized.replace("Z", "+00:00"))
    except ValueError:
        return None


def _priority_weight(value: str | None) -> int:
    normalized = str(value or "").strip().lower()
    return _PRIORITY_WEIGHTS.get(normalized, 40)


def _due_bonus(value: str | None) -> int:
    when = _parse_when(value)
    if when is None:
        return 0
    delta = when - datetime.now(timezone.utc)
    hours = delta.total_seconds() / 3600
    if hours <= 0:
        return 35
    if hours <= 12:
        return 28
    if hours <= 48:
        return 18
    if hours <= 168:
        return 8
    return 0


def _status_open(value: str | None) -> bool:
    normalized = str(value or "").strip().lower()
    if not normalized:
        return True
    return normalized not in _TERMINAL_STATUSES


def _compact_text(value: str | None, *, fallback: str, limit: int = 160) -> str:
    normalized = " ".join(str(value or "").split()).strip()
    if not normalized:
        return fallback
    if len(normalized) <= limit:
        return normalized
    return f"{normalized[: max(limit - 3, 0)]}..."


def _action_label(action_json: dict[str, object]) -> str:
    raw = str(action_json.get("action") or action_json.get("event_type") or "review").strip().replace("_", " ").replace(".", " ")
    return raw or "review"


def _contains_token(text: str | None, token: str) -> bool:
    haystack = str(text or "").strip().lower()
    needle = str(token or "").strip().lower()
    return bool(haystack and needle and needle in haystack)


class ProductService:
    def __init__(self, container: AppContainer) -> None:
        self._container = container

    def _stakeholder_lookup(self, principal_id: str) -> dict[str, Stakeholder]:
        rows = self._container.memory_runtime.list_stakeholders(principal_id=principal_id, limit=200)
        return {row.stakeholder_id: row for row in rows}

    def _commitment_item_from_commitment(self, row: Commitment) -> CommitmentItem:
        source = dict(row.source_json or {})
        return CommitmentItem(
            id=f"commitment:{row.commitment_id}",
            source_type=str(source.get("source_type") or "manual"),
            source_ref=str(source.get("source_ref") or row.commitment_id),
            statement=row.title,
            owner=str(source.get("owner") or "office"),
            counterparty=str(source.get("counterparty") or source.get("stakeholder") or ""),
            due_at=row.due_at,
            status=row.status,
            last_activity_at=row.updated_at,
            risk_level="high" if _due_bonus(row.due_at) >= 28 or _priority_weight(row.priority) >= 80 else "medium",
            proof_refs=(
                EvidenceRef(
                    ref_id=f"commitment:{row.commitment_id}",
                    label="Commitment",
                    source_type="commitment",
                    note=_compact_text(row.details, fallback="Commitment is stored in workspace memory."),
                ),
            ),
        )

    def _commitment_item_from_follow_up(self, row: FollowUp, stakeholders: dict[str, Stakeholder]) -> CommitmentItem:
        stakeholder = stakeholders.get(str(row.stakeholder_ref or "").strip())
        return CommitmentItem(
            id=f"follow_up:{row.follow_up_id}",
            source_type="follow_up",
            source_ref=row.follow_up_id,
            statement=row.topic,
            owner="office",
            counterparty=stakeholder.display_name if stakeholder is not None else str(row.stakeholder_ref or ""),
            due_at=row.due_at,
            status=row.status,
            last_activity_at=row.updated_at,
            risk_level="high" if _due_bonus(row.due_at) >= 28 else "medium",
            proof_refs=(
                EvidenceRef(
                    ref_id=f"follow_up:{row.follow_up_id}",
                    label="Follow-up",
                    source_type="follow_up",
                    note=_compact_text(row.notes, fallback="Follow-up remains open in the workspace ledger."),
                ),
            ),
        )

    def list_commitments(self, *, principal_id: str, limit: int = 50) -> tuple[CommitmentItem, ...]:
        stakeholders = self._stakeholder_lookup(principal_id)
        rows: list[CommitmentItem] = []
        for commitment in self._container.memory_runtime.list_commitments(principal_id=principal_id, limit=limit, status=None):
            rows.append(self._commitment_item_from_commitment(commitment))
        for follow_up in self._container.memory_runtime.list_follow_ups(principal_id=principal_id, limit=limit, status=None):
            rows.append(self._commitment_item_from_follow_up(follow_up, stakeholders))
        rows = [row for row in rows if _status_open(row.status)]
        rows.sort(key=lambda row: (_priority_weight(row.risk_level), _due_bonus(row.due_at), row.statement.lower()), reverse=True)
        return tuple(rows[:limit])

    def get_commitment(self, *, principal_id: str, commitment_ref: str) -> CommitmentItem | None:
        if commitment_ref.startswith("commitment:"):
            found = self._container.memory_runtime.get_commitment(commitment_ref.split(":", 1)[1], principal_id=principal_id)
            return None if found is None else self._commitment_item_from_commitment(found)
        if commitment_ref.startswith("follow_up:"):
            found = self._container.memory_runtime.get_follow_up(commitment_ref.split(":", 1)[1], principal_id=principal_id)
            if found is None:
                return None
            return self._commitment_item_from_follow_up(found, self._stakeholder_lookup(principal_id))
        return None

    def _queue_item_from_approval(self, row: ApprovalRequest) -> DecisionQueueItem:
        action_json = dict(row.requested_action_json or {})
        action_label = _action_label(action_json)
        summary = _compact_text(
            action_json.get("content") or action_json.get("draft_text") or row.reason,
            fallback="Approval is waiting for a decision.",
        )
        return DecisionQueueItem(
            id=f"approval:{row.approval_id}",
            queue_kind="approve_draft",
            title=row.reason or f"Approve {action_label}",
            summary=summary,
            priority="high",
            deadline=row.expires_at,
            owner_role="principal",
            requires_principal=True,
            evidence_refs=(
                EvidenceRef(ref_id=f"approval:{row.approval_id}", label="Approval", source_type="approval", note=action_label),
                EvidenceRef(ref_id=f"session:{row.session_id}", label="Session", source_type="session", note=row.step_id),
            ),
            resolution_state=row.status,
        )

    def _draft_from_approval(self, row: ApprovalRequest) -> DraftCandidate:
        action_json = dict(row.requested_action_json or {})
        return DraftCandidate(
            id=f"approval:{row.approval_id}",
            thread_ref=str(action_json.get("thread_ref") or row.session_id),
            recipient_summary=str(action_json.get("recipient") or action_json.get("to") or "Review required"),
            intent=_action_label(action_json),
            draft_text=_compact_text(
                action_json.get("content") or action_json.get("draft_text") or row.reason,
                fallback="Approval-backed draft ready for review.",
                limit=500,
            ),
            tone=str(action_json.get("tone") or "review"),
            requires_approval=True,
            approval_status=row.status,
            provenance_refs=(
                EvidenceRef(ref_id=f"approval:{row.approval_id}", label="Approval request", source_type="approval", note=row.reason),
                EvidenceRef(ref_id=f"session:{row.session_id}", label="Session", source_type="session", note=row.step_id),
            ),
            send_channel=str(action_json.get("channel") or "email"),
        )

    def list_drafts(self, *, principal_id: str, limit: int = 20) -> tuple[DraftCandidate, ...]:
        rows = self._container.orchestrator.list_pending_approvals_for_principal(principal_id=principal_id, limit=limit)
        return tuple(self._draft_from_approval(row) for row in rows[:limit])

    def approve_draft(self, *, principal_id: str, draft_ref: str, decided_by: str, reason: str) -> DraftCandidate | None:
        if not draft_ref.startswith("approval:"):
            return None
        approval_id = draft_ref.split(":", 1)[1]
        allowed = {row.approval_id for row in self._container.orchestrator.list_pending_approvals_for_principal(principal_id=principal_id, limit=500)}
        if approval_id not in allowed:
            return None
        decided = self._container.orchestrator.decide_approval(
            approval_id,
            decision="approved",
            decided_by=decided_by,
            reason=reason or "Approved from product draft queue.",
        )
        if decided is None:
            return None
        request, _ = decided
        return DraftCandidate(
            id=f"approval:{request.approval_id}",
            thread_ref=request.session_id,
            recipient_summary="Approved draft",
            intent="approved",
            draft_text=_compact_text(request.reason, fallback="Approved from product draft queue."),
            tone="approved",
            requires_approval=True,
            approval_status="approved",
            provenance_refs=(EvidenceRef(ref_id=f"approval:{request.approval_id}", label="Approval request", source_type="approval", note=request.reason),),
            send_channel=str(dict(request.requested_action_json or {}).get("channel") or "email"),
        )

    def _queue_item_from_human_task(self, row: HumanTask) -> DecisionQueueItem:
        summary = " · ".join(
            part
            for part in (
                _compact_text(row.why_human, fallback="Human judgment is still required."),
                f"Role {row.role_required}" if row.role_required else "",
                f"Due {row.sla_due_at[:10]}" if row.sla_due_at else "",
            )
            if part
        )
        return DecisionQueueItem(
            id=f"human_task:{row.human_task_id}",
            queue_kind="assign_owner",
            title=row.brief,
            summary=summary,
            priority=row.priority,
            deadline=row.sla_due_at,
            owner_role=row.role_required,
            requires_principal=False,
            evidence_refs=(
                EvidenceRef(ref_id=f"human_task:{row.human_task_id}", label="Human task", source_type="human_task", note=row.task_type),
                EvidenceRef(ref_id=f"session:{row.session_id}", label="Session", source_type="session", note=row.step_id or ""),
            ),
            resolution_state=row.status,
        )

    def _queue_item_from_commitment(self, row: CommitmentItem) -> DecisionQueueItem:
        return DecisionQueueItem(
            id=row.id,
            queue_kind="close_commitment",
            title=row.statement,
            summary=_compact_text(
                row.proof_refs[0].note if row.proof_refs else "",
                fallback="Commitment is still open and needs a visible next action.",
            ),
            priority=row.risk_level,
            deadline=row.due_at,
            owner_role=row.owner,
            requires_principal=False,
            evidence_refs=row.proof_refs,
            resolution_state=row.status,
        )

    def _queue_item_from_decision(self, row: DecisionWindow) -> DecisionQueueItem:
        return DecisionQueueItem(
            id=f"decision:{row.decision_window_id}",
            queue_kind="choose_option",
            title=row.title,
            summary=_compact_text(row.context or row.notes, fallback="Decision window is open."),
            priority=row.urgency,
            deadline=row.closes_at or row.opens_at,
            owner_role=row.authority_required,
            requires_principal=str(row.authority_required or "").strip().lower() in {"principal", "exec", "executive"},
            evidence_refs=(EvidenceRef(ref_id=f"decision:{row.decision_window_id}", label="Decision", source_type="decision", note=row.status),),
            resolution_state=row.status,
        )

    def _queue_item_from_deadline(self, row: DeadlineWindow) -> DecisionQueueItem:
        return DecisionQueueItem(
            id=f"deadline:{row.window_id}",
            queue_kind="defer",
            title=row.title,
            summary=_compact_text(row.notes, fallback="Deadline window is active."),
            priority=row.priority,
            deadline=row.end_at or row.start_at,
            owner_role="office",
            requires_principal=False,
            evidence_refs=(EvidenceRef(ref_id=f"deadline:{row.window_id}", label="Deadline", source_type="deadline", note=row.status),),
            resolution_state=row.status,
        )

    def list_queue(self, *, principal_id: str, limit: int = 30) -> tuple[DecisionQueueItem, ...]:
        items: list[DecisionQueueItem] = []
        items.extend(self._queue_item_from_approval(row) for row in self._container.orchestrator.list_pending_approvals_for_principal(principal_id=principal_id, limit=limit))
        items.extend(self._queue_item_from_human_task(row) for row in self._container.orchestrator.list_human_tasks(principal_id=principal_id, status="pending", limit=limit))
        items.extend(self._queue_item_from_commitment(row) for row in self.list_commitments(principal_id=principal_id, limit=limit))
        for row in self._container.memory_runtime.list_decision_windows(principal_id=principal_id, limit=limit, status=None):
            if _status_open(row.status):
                items.append(self._queue_item_from_decision(row))
        for row in self._container.memory_runtime.list_deadline_windows(principal_id=principal_id, limit=limit, status=None):
            if _status_open(row.status):
                items.append(self._queue_item_from_deadline(row))
        items = [item for item in items if _status_open(item.resolution_state)]
        items.sort(key=lambda item: (_priority_weight(item.priority), _due_bonus(item.deadline), item.title.lower()), reverse=True)
        return tuple(items[:limit])

    def resolve_queue_item(
        self,
        *,
        principal_id: str,
        item_ref: str,
        action: str,
        actor: str,
        reason: str = "",
        due_at: str | None = None,
    ) -> DecisionQueueItem | None:
        normalized = str(action or "").strip().lower()
        if item_ref.startswith("approval:"):
            decision = "approved" if normalized in {"approve", "approved", "close"} else "rejected"
            allowed = {row.approval_id for row in self._container.orchestrator.list_pending_approvals_for_principal(principal_id=principal_id, limit=500)}
            approval_id = item_ref.split(":", 1)[1]
            if approval_id not in allowed:
                return None
            decided = self._container.orchestrator.decide_approval(
                approval_id,
                decision=decision,
                decided_by=actor,
                reason=reason or f"{decision.capitalize()} from decision queue.",
            )
            if decided is None:
                return None
            request, decision_row = decided
            updated = self._queue_item_from_approval(request)
            return DecisionQueueItem(
                id=updated.id,
                queue_kind=updated.queue_kind,
                title=updated.title,
                summary=updated.summary,
                priority=updated.priority,
                deadline=updated.deadline,
                owner_role=updated.owner_role,
                requires_principal=updated.requires_principal,
                evidence_refs=updated.evidence_refs,
                resolution_state=decision_row.decision,
            )
        if item_ref.startswith("commitment:"):
            current = self._container.memory_runtime.get_commitment(item_ref.split(":", 1)[1], principal_id=principal_id)
            if current is None:
                return None
            next_status = "completed" if normalized in {"close", "done", "complete"} else "in_progress"
            updated = self._container.memory_runtime.upsert_commitment(
                principal_id=principal_id,
                commitment_id=current.commitment_id,
                title=current.title,
                details=current.details,
                status=next_status,
                priority=current.priority,
                due_at=due_at or current.due_at,
                source_json=dict(current.source_json or {}),
            )
            return self._queue_item_from_commitment(self._commitment_item_from_commitment(updated))
        if item_ref.startswith("follow_up:"):
            current = self._container.memory_runtime.get_follow_up(item_ref.split(":", 1)[1], principal_id=principal_id)
            if current is None:
                return None
            next_status = "completed" if normalized in {"close", "done", "complete"} else "open"
            updated = self._container.memory_runtime.upsert_follow_up(
                principal_id=principal_id,
                follow_up_id=current.follow_up_id,
                stakeholder_ref=current.stakeholder_ref,
                topic=current.topic,
                status=next_status,
                due_at=due_at or current.due_at,
                channel_hint=current.channel_hint,
                notes=current.notes if not reason else reason,
                source_json=dict(current.source_json or {}),
            )
            return self._queue_item_from_commitment(
                self._commitment_item_from_follow_up(updated, self._stakeholder_lookup(principal_id))
            )
        return None

    def _brief_item_from_queue(self, row: DecisionQueueItem, *, workspace_id: str) -> BriefItem:
        return BriefItem(
            id=row.id,
            workspace_id=workspace_id,
            kind=row.queue_kind,
            title=row.title,
            summary=row.summary,
            score=float(_priority_weight(row.priority) + _due_bonus(row.deadline)),
            why_now=row.summary,
            evidence_refs=row.evidence_refs,
            related_people=(),
            related_commitment_ids=(row.id,) if row.queue_kind == "close_commitment" else (),
            recommended_action=row.queue_kind.replace("_", " "),
            status=row.resolution_state,
        )

    def list_brief_items(self, *, principal_id: str, limit: int = 20) -> tuple[BriefItem, ...]:
        queue = self.list_queue(principal_id=principal_id, limit=max(limit, 10))
        items = [self._brief_item_from_queue(row, workspace_id=principal_id) for row in queue]
        items.sort(key=lambda row: (row.score, row.title.lower()), reverse=True)
        return tuple(items[:limit])

    def _person_profile(self, row: Stakeholder, *, open_loops_count: int) -> PersonProfile:
        themes = tuple(str(key).replace("_", " ") for key in dict(row.open_loops_json or {}).keys())
        risks = tuple(str(key).replace("_", " ") for key in dict(row.friction_points_json or {}).keys())
        importance_key = str(row.importance or "medium").strip().lower() or "medium"
        return PersonProfile(
            id=row.stakeholder_id,
            display_name=row.display_name,
            role_or_company=row.channel_ref or row.authority_level,
            importance_score=_priority_weight(importance_key),
            relationship_temperature=_TEMPERATURE_BY_IMPORTANCE.get(importance_key, "steady"),
            open_loops_count=open_loops_count,
            latest_touchpoint_at=row.last_interaction_at,
            preferred_tone=row.tone_pref,
            themes=themes,
            risks=risks or (("open loops",) if open_loops_count else ()),
        )

    def list_people(self, *, principal_id: str, limit: int = 25) -> tuple[PersonProfile, ...]:
        stakeholders = list(self._container.memory_runtime.list_stakeholders(principal_id=principal_id, limit=limit))
        follow_ups = list(self._container.memory_runtime.list_follow_ups(principal_id=principal_id, limit=200, status=None))
        commitments = list(self._container.memory_runtime.list_commitments(principal_id=principal_id, limit=200, status=None))
        rows: list[PersonProfile] = []
        for row in stakeholders:
            open_loops = len(dict(row.open_loops_json or {}))
            open_loops += sum(1 for follow_up in follow_ups if _status_open(follow_up.status) and str(follow_up.stakeholder_ref or "") == row.stakeholder_id)
            open_loops += sum(1 for commitment in commitments if _status_open(commitment.status) and row.display_name.lower() in str(commitment.details or "").lower())
            rows.append(self._person_profile(row, open_loops_count=open_loops))
        rows.sort(key=lambda row: (row.importance_score, row.open_loops_count, row.display_name.lower()), reverse=True)
        return tuple(rows[:limit])

    def get_person(self, *, principal_id: str, person_id: str) -> PersonProfile | None:
        found = self._container.memory_runtime.get_stakeholder(person_id, principal_id=principal_id)
        if found is None:
            return None
        people = {row.id: row for row in self.list_people(principal_id=principal_id, limit=200)}
        return people.get(found.stakeholder_id, self._person_profile(found, open_loops_count=len(dict(found.open_loops_json or {}))))

    def get_person_detail(self, *, principal_id: str, person_id: str) -> PersonDetail | None:
        profile = self.get_person(principal_id=principal_id, person_id=person_id)
        if profile is None:
            return None
        person_tokens = tuple(
            token
            for token in {
                profile.display_name,
                profile.role_or_company,
                profile.display_name.split(" ", 1)[0] if profile.display_name else "",
            }
            if str(token or "").strip()
        )

        def _matches(*values: str | None) -> bool:
            return any(_contains_token(value, token) for token in person_tokens for value in values)

        commitments = tuple(
            row
            for row in self.list_commitments(principal_id=principal_id, limit=100)
            if _matches(row.statement, row.counterparty, row.owner, row.proof_refs[0].note if row.proof_refs else "")
        )
        drafts = tuple(
            row
            for row in self.list_drafts(principal_id=principal_id, limit=100)
            if _matches(row.recipient_summary, row.draft_text, row.intent)
        )
        queue_items = tuple(
            row
            for row in self.list_queue(principal_id=principal_id, limit=100)
            if _matches(
                row.title,
                row.summary,
                row.evidence_refs[0].note if row.evidence_refs else "",
            )
        )
        handoffs = tuple(
            row
            for row in self.list_handoffs(principal_id=principal_id, limit=100)
            if _matches(
                row.summary,
                row.owner,
                row.evidence_refs[0].note if row.evidence_refs else "",
            )
        )
        evidence: list[EvidenceRef] = []
        seen: set[str] = set()
        for refs in [*(row.proof_refs for row in commitments), *(row.provenance_refs for row in drafts), *(row.evidence_refs for row in queue_items), *(row.evidence_refs for row in handoffs)]:
            for ref in refs:
                if ref.ref_id in seen:
                    continue
                seen.add(ref.ref_id)
                evidence.append(ref)
        return PersonDetail(
            profile=profile,
            commitments=commitments,
            drafts=drafts,
            queue_items=queue_items,
            handoffs=handoffs,
            evidence_refs=tuple(evidence[:12]),
        )

    def list_handoffs(self, *, principal_id: str, limit: int = 20) -> tuple[HandoffNote, ...]:
        rows: list[HandoffNote] = []
        for task in self._container.orchestrator.list_human_tasks(principal_id=principal_id, status="pending", limit=limit):
            rows.append(
                HandoffNote(
                    id=f"human_task:{task.human_task_id}",
                    queue_item_ref=f"human_task:{task.human_task_id}",
                    summary=task.brief,
                    owner=task.assigned_operator_id or task.role_required or "operator",
                    due_time=task.sla_due_at,
                    escalation_status=task.priority,
                    status=task.status,
                    evidence_refs=(
                        EvidenceRef(ref_id=f"human_task:{task.human_task_id}", label="Human task", source_type="human_task", note=task.why_human),
                        EvidenceRef(ref_id=f"session:{task.session_id}", label="Session", source_type="session", note=task.step_id or ""),
                    ),
                )
            )
        rows.sort(key=lambda row: (_priority_weight(row.escalation_status), _due_bonus(row.due_time), row.summary.lower()), reverse=True)
        return tuple(rows[:limit])

    def workspace_snapshot(self, *, principal_id: str) -> ProductSnapshot:
        brief_items = self.list_brief_items(principal_id=principal_id, limit=8)
        queue_items = self.list_queue(principal_id=principal_id, limit=10)
        commitments = self.list_commitments(principal_id=principal_id, limit=10)
        drafts = self.list_drafts(principal_id=principal_id, limit=8)
        people = self.list_people(principal_id=principal_id, limit=8)
        handoffs = self.list_handoffs(principal_id=principal_id, limit=8)
        return ProductSnapshot(
            brief_items=brief_items,
            queue_items=queue_items,
            commitments=commitments,
            drafts=drafts,
            people=people,
            handoffs=handoffs,
            stats_json={
                "brief_items": len(brief_items),
                "queue_items": len(queue_items),
                "commitments": len(commitments),
                "drafts": len(drafts),
                "people": len(people),
                "handoffs": len(handoffs),
            },
        )

    def workspace_diagnostics(self, *, principal_id: str) -> dict[str, object]:
        status = self._container.onboarding.status(principal_id=principal_id)
        workspace = dict(status.get("workspace") or {})
        selected_channels = tuple(str(value) for value in (status.get("selected_channels") or []) if str(value).strip())
        plan = workspace_plan_for_mode(str(workspace.get("mode") or "personal"))
        snapshot = self.workspace_snapshot(principal_id=principal_id)
        readiness_ok, readiness_label = self._container.readiness.check()
        registry = self._container.provider_registry.registry_read_model(principal_id=principal_id)
        operators = self._container.orchestrator.list_operator_profiles(principal_id=principal_id, status="active", limit=25)
        return {
            "workspace": {
                "name": str(workspace.get("name") or "Executive Workspace"),
                "mode": str(workspace.get("mode") or "personal"),
                "region": str(workspace.get("region") or ""),
                "language": str(workspace.get("language") or ""),
                "timezone": str(workspace.get("timezone") or ""),
            },
            "selected_channels": list(selected_channels),
            "plan": {
                "plan_key": plan.plan_key,
                "display_name": plan.display_name,
                "unit_of_sale": plan.unit_of_sale,
            },
            "entitlements": {
                "principal_seats": plan.entitlements.principal_seats,
                "operator_seats": plan.entitlements.operator_seats,
                "messaging_channels_enabled": plan.entitlements.messaging_channels_enabled,
                "audit_retention": plan.entitlements.audit_retention,
                "feature_flags": list(plan.entitlements.feature_flags),
            },
            "readiness": {
                "ready": readiness_ok,
                "detail": readiness_label,
            },
            "operators": {
                "active_count": len(operators),
            },
            "providers": {
                "provider_count": int(registry.get("provider_count") or 0),
                "lane_count": int(registry.get("lane_count") or 0),
            },
            "usage": dict(snapshot.stats_json or {}),
        }


def build_product_service(container: AppContainer) -> ProductService:
    return ProductService(container)
