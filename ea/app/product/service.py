from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING

from app.domain.models import ApprovalRequest, Commitment, DecisionWindow, DeadlineWindow, FollowUp, HumanTask, Stakeholder
from app.product.commercial import workspace_plan_for_mode
from app.product.extractors import extract_commitment_candidates
from app.product.models import (
    BriefItem,
    CommitmentCandidate,
    CommitmentItem,
    DecisionQueueItem,
    DraftCandidate,
    EvidenceRef,
    HandoffNote,
    HistoryEntry,
    PersonDetail,
    PersonProfile,
    ProductSnapshot,
)
from app.product.projections import (
    commitment_item_from_commitment,
    commitment_item_from_follow_up,
    compact_text,
    contains_token,
    due_bonus,
    handoff_from_human_task,
    priority_weight,
    status_open,
)

if TYPE_CHECKING:
    from app.container import AppContainer


_TEMPERATURE_BY_IMPORTANCE = {
    "critical": "hot",
    "high": "warm",
    "medium": "steady",
    "low": "cool",
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _action_label(action_json: dict[str, object]) -> str:
    raw = str(action_json.get("action") or action_json.get("event_type") or "review").strip().replace("_", " ").replace(".", " ")
    return raw or "review"


class ProductService:
    def __init__(self, container: AppContainer) -> None:
        self._container = container

    def _record_product_event(
        self,
        *,
        principal_id: str,
        event_type: str,
        payload: dict[str, object] | None = None,
        source_id: str = "",
        dedupe_key: str = "",
    ) -> None:
        self._container.channel_runtime.ingest_observation(
            principal_id=principal_id,
            channel="product",
            event_type=event_type,
            payload=dict(payload or {}),
            source_id=source_id,
            dedupe_key=dedupe_key,
        )

    def _stakeholder_lookup(self, principal_id: str) -> dict[str, Stakeholder]:
        rows = self._container.memory_runtime.list_stakeholders(principal_id=principal_id, limit=200)
        return {row.stakeholder_id: row for row in rows}

    def _commitment_item_from_commitment(self, row: Commitment) -> CommitmentItem:
        return commitment_item_from_commitment(row)

    def _commitment_item_from_follow_up(self, row: FollowUp, stakeholders: dict[str, Stakeholder]) -> CommitmentItem:
        return commitment_item_from_follow_up(row, stakeholders)

    def _handoff_from_human_task(self, task: HumanTask) -> HandoffNote:
        return handoff_from_human_task(task)

    def list_commitments(self, *, principal_id: str, limit: int = 50) -> tuple[CommitmentItem, ...]:
        stakeholders = self._stakeholder_lookup(principal_id)
        rows: list[CommitmentItem] = []
        for commitment in self._container.memory_runtime.list_commitments(principal_id=principal_id, limit=limit, status=None):
            rows.append(self._commitment_item_from_commitment(commitment))
        for follow_up in self._container.memory_runtime.list_follow_ups(principal_id=principal_id, limit=limit, status=None):
            rows.append(self._commitment_item_from_follow_up(follow_up, stakeholders))
        rows = [row for row in rows if status_open(row.status)]
        rows.sort(key=lambda row: (priority_weight(row.risk_level), due_bonus(row.due_at), row.statement.lower()), reverse=True)
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

    def _history_entries(self, *, principal_id: str, source_ids: tuple[str, ...] = (), limit: int = 20) -> tuple[HistoryEntry, ...]:
        wanted = {str(value).strip() for value in source_ids if str(value).strip()}
        rows: list[HistoryEntry] = []
        for row in self._container.channel_runtime.list_recent_observations(limit=200, principal_id=principal_id):
            if str(row.channel or "").strip() != "product":
                continue
            source_id = str(row.source_id or "").strip()
            payload = dict(row.payload or {})
            if wanted and source_id not in wanted and str(payload.get("person_id") or "").strip() not in wanted:
                continue
            rows.append(
                HistoryEntry(
                    event_type=str(row.event_type or ""),
                    created_at=str(row.created_at or ""),
                    source_id=source_id,
                    actor=str(payload.get("actor") or payload.get("reviewer") or payload.get("decided_by") or ""),
                    detail=str(payload.get("reason") or payload.get("surface") or payload.get("candidate_id") or ""),
                )
            )
        rows.sort(key=lambda item: (str(item.created_at or ""), str(item.event_type or "")), reverse=True)
        return tuple(rows[:limit])

    def get_commitment_history(self, *, principal_id: str, commitment_ref: str, limit: int = 20) -> tuple[HistoryEntry, ...]:
        if ":" in commitment_ref:
            source_id = commitment_ref.split(":", 1)[1]
        else:
            source_id = commitment_ref
        return self._history_entries(principal_id=principal_id, source_ids=(source_id,), limit=limit)

    def create_commitment(
        self,
        *,
        principal_id: str,
        title: str,
        details: str = "",
        due_at: str | None = None,
        priority: str = "medium",
        counterparty: str = "",
        owner: str = "office",
        kind: str = "commitment",
        stakeholder_id: str = "",
        channel_hint: str = "email",
    ) -> CommitmentItem:
        normalized_kind = str(kind or "commitment").strip().lower()
        if normalized_kind == "follow_up" and stakeholder_id.strip():
            row = self._container.memory_runtime.upsert_follow_up(
                principal_id=principal_id,
                stakeholder_ref=stakeholder_id.strip(),
                topic=title,
                status="open",
                due_at=due_at,
                channel_hint=channel_hint,
                notes=details,
                source_json={"source_type": "manual", "counterparty": counterparty, "owner": owner},
            )
            self._record_product_event(
                principal_id=principal_id,
                event_type="commitment_created",
                payload={"kind": "follow_up", "title": title, "counterparty": counterparty, "due_at": due_at or ""},
                source_id=row.follow_up_id,
            )
            return self._commitment_item_from_follow_up(row, self._stakeholder_lookup(principal_id))
        row = self._container.memory_runtime.upsert_commitment(
            principal_id=principal_id,
            title=title,
            details=details,
            status="open",
            priority=priority,
            due_at=due_at,
            source_json={"source_type": "manual", "counterparty": counterparty, "owner": owner},
        )
        self._record_product_event(
            principal_id=principal_id,
            event_type="commitment_created",
            payload={"kind": "commitment", "title": title, "counterparty": counterparty, "due_at": due_at or ""},
            source_id=row.commitment_id,
        )
        return self._commitment_item_from_commitment(row)

    def extract_commitments(
        self,
        *,
        text: str,
        counterparty: str = "",
        due_at: str | None = None,
    ) -> tuple[CommitmentCandidate, ...]:
        return extract_commitment_candidates(text, counterparty=counterparty, due_at=due_at)

    def _candidate_from_memory_row(self, row) -> CommitmentCandidate:  # type: ignore[no-untyped-def]
        fact = dict(getattr(row, "fact_json", {}) or {})
        return CommitmentCandidate(
            candidate_id=str(getattr(row, "candidate_id", "") or ""),
            title=str(fact.get("title") or getattr(row, "summary", "") or "Commitment candidate"),
            details=str(fact.get("details") or getattr(row, "summary", "") or ""),
            source_text=str(fact.get("source_text") or ""),
            confidence=float(getattr(row, "confidence", 0.5) or 0.5),
            suggested_due_at=str(fact.get("suggested_due_at") or "") or None,
            counterparty=str(fact.get("counterparty") or ""),
            status=str(getattr(row, "status", "pending") or "pending"),
        )

    def list_commitment_candidates(self, *, principal_id: str, limit: int = 20) -> tuple[CommitmentCandidate, ...]:
        rows = self._container.memory_runtime.list_candidates(limit=max(limit * 3, 50), status="pending", principal_id=principal_id)
        filtered = [row for row in rows if str(getattr(row, "category", "") or "") == "product_commitment_candidate"]
        return tuple(self._candidate_from_memory_row(row) for row in filtered[:limit])

    def get_commitment_candidate(self, *, principal_id: str, candidate_id: str) -> CommitmentCandidate | None:
        row = self._container.memory_runtime.get_candidate(candidate_id, principal_id=principal_id)
        if row is None or str(getattr(row, "category", "") or "") != "product_commitment_candidate":
            return None
        return self._candidate_from_memory_row(row)

    def stage_extracted_commitments(
        self,
        *,
        principal_id: str,
        text: str,
        counterparty: str = "",
        due_at: str | None = None,
        kind: str = "commitment",
        stakeholder_id: str = "",
    ) -> tuple[CommitmentCandidate, ...]:
        extracted = self.extract_commitments(text=text, counterparty=counterparty, due_at=due_at)
        staged: list[CommitmentCandidate] = []
        for candidate in extracted:
            row = self._container.memory_runtime.stage_candidate(
                principal_id=principal_id,
                category="product_commitment_candidate",
                summary=candidate.title,
                fact_json={
                    "title": candidate.title,
                    "details": candidate.details,
                    "source_text": candidate.source_text,
                    "suggested_due_at": candidate.suggested_due_at or "",
                    "counterparty": candidate.counterparty,
                    "kind": kind,
                    "stakeholder_id": stakeholder_id,
                },
                confidence=candidate.confidence,
                sensitivity="internal",
            )
            staged.append(self._candidate_from_memory_row(row))
            self._record_product_event(
                principal_id=principal_id,
                event_type="commitment_candidate_staged",
                payload={"title": candidate.title, "kind": kind, "counterparty": candidate.counterparty},
                source_id=row.candidate_id,
            )
        return tuple(staged)

    def accept_commitment_candidate(
        self,
        *,
        principal_id: str,
        candidate_id: str,
        reviewer: str,
        title: str = "",
        details: str = "",
        due_at: str | None = None,
        counterparty: str = "",
        kind: str = "",
        stakeholder_id: str = "",
    ) -> CommitmentItem | None:
        promoted = self._container.memory_runtime.promote_candidate(
            candidate_id,
            principal_id=principal_id,
            reviewer=reviewer,
            sharing_policy="private",
        )
        if promoted is None:
            return None
        candidate, _item = promoted
        fact = dict(candidate.fact_json or {})
        created = self.create_commitment(
            principal_id=principal_id,
            title=title.strip() or str(fact.get("title") or candidate.summary or "Commitment"),
            details=details if details.strip() else str(fact.get("details") or ""),
            due_at=due_at if str(due_at or "").strip() else (str(fact.get("suggested_due_at") or "") or None),
            counterparty=counterparty.strip() or str(fact.get("counterparty") or ""),
            owner="office",
            kind=kind.strip() or str(fact.get("kind") or "commitment"),
            stakeholder_id=stakeholder_id.strip() or str(fact.get("stakeholder_id") or ""),
            channel_hint="email",
        )
        self._record_product_event(
            principal_id=principal_id,
            event_type="commitment_candidate_accepted",
            payload={
                "candidate_id": candidate_id,
                "reviewer": reviewer,
                "title_override": title.strip(),
                "due_at_override": str(due_at or "").strip(),
                "counterparty_override": counterparty.strip(),
                "kind_override": kind.strip(),
            },
            source_id=candidate_id,
        )
        return created

    def reject_commitment_candidate(
        self,
        *,
        principal_id: str,
        candidate_id: str,
        reviewer: str,
    ) -> CommitmentCandidate | None:
        row = self._container.memory_runtime.reject_candidate(candidate_id, principal_id=principal_id, reviewer=reviewer)
        if row is None:
            return None
        self._record_product_event(
            principal_id=principal_id,
            event_type="commitment_candidate_rejected",
            payload={"candidate_id": candidate_id, "reviewer": reviewer},
            source_id=candidate_id,
        )
        return self._candidate_from_memory_row(row)

    def _queue_item_from_approval(self, row: ApprovalRequest) -> DecisionQueueItem:
        action_json = dict(row.requested_action_json or {})
        action_label = _action_label(action_json)
        summary = compact_text(
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
            draft_text=compact_text(
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
        self._record_product_event(
            principal_id=principal_id,
            event_type="draft_approved",
            payload={"draft_ref": draft_ref, "decided_by": decided_by, "reason": reason or ""},
            source_id=request.approval_id,
        )
        return DraftCandidate(
            id=f"approval:{request.approval_id}",
            thread_ref=request.session_id,
            recipient_summary="Approved draft",
            intent="approved",
            draft_text=compact_text(request.reason, fallback="Approved from product draft queue."),
            tone="approved",
            requires_approval=True,
            approval_status="approved",
            provenance_refs=(EvidenceRef(ref_id=f"approval:{request.approval_id}", label="Approval request", source_type="approval", note=request.reason),),
            send_channel=str(dict(request.requested_action_json or {}).get("channel") or "email"),
        )

    def reject_draft(self, *, principal_id: str, draft_ref: str, decided_by: str, reason: str) -> DraftCandidate | None:
        if not draft_ref.startswith("approval:"):
            return None
        approval_id = draft_ref.split(":", 1)[1]
        allowed = {row.approval_id for row in self._container.orchestrator.list_pending_approvals_for_principal(principal_id=principal_id, limit=500)}
        if approval_id not in allowed:
            return None
        decided = self._container.orchestrator.decide_approval(
            approval_id,
            decision="rejected",
            decided_by=decided_by,
            reason=reason or "Rejected from product draft queue.",
        )
        if decided is None:
            return None
        request, _ = decided
        self._record_product_event(
            principal_id=principal_id,
            event_type="draft_rejected",
            payload={"draft_ref": draft_ref, "decided_by": decided_by, "reason": reason or ""},
            source_id=request.approval_id,
        )
        return DraftCandidate(
            id=f"approval:{request.approval_id}",
            thread_ref=request.session_id,
            recipient_summary="Rejected draft",
            intent="rejected",
            draft_text=compact_text(request.reason, fallback="Rejected from product draft queue."),
            tone="rejected",
            requires_approval=True,
            approval_status="rejected",
            provenance_refs=(EvidenceRef(ref_id=f"approval:{request.approval_id}", label="Approval request", source_type="approval", note=request.reason),),
            send_channel=str(dict(request.requested_action_json or {}).get("channel") or "email"),
        )

    def _queue_item_from_human_task(self, row: HumanTask) -> DecisionQueueItem:
        summary = " · ".join(
            part
            for part in (
                compact_text(row.why_human, fallback="Human judgment is still required."),
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
            summary=compact_text(
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
            summary=compact_text(row.context or row.notes, fallback="Decision window is open."),
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
            summary=compact_text(row.notes, fallback="Deadline window is active."),
            priority=row.priority,
            deadline=row.end_at or row.start_at,
            owner_role="office",
            requires_principal=False,
            evidence_refs=(EvidenceRef(ref_id=f"deadline:{row.window_id}", label="Deadline", source_type="deadline", note=row.status),),
            resolution_state=row.status,
        )

    def list_queue(self, *, principal_id: str, limit: int = 30, operator_id: str = "") -> tuple[DecisionQueueItem, ...]:
        operator_key = str(operator_id or "").strip()
        items: list[DecisionQueueItem] = []
        items.extend(self._queue_item_from_approval(row) for row in self._container.orchestrator.list_pending_approvals_for_principal(principal_id=principal_id, limit=limit))
        for row in self._container.orchestrator.list_human_tasks(principal_id=principal_id, status="pending", limit=limit):
            assigned = str(row.assigned_operator_id or "").strip()
            if operator_key and assigned and assigned != operator_key:
                continue
            items.append(self._queue_item_from_human_task(row))
        items.extend(self._queue_item_from_commitment(row) for row in self.list_commitments(principal_id=principal_id, limit=limit))
        for row in self._container.memory_runtime.list_decision_windows(principal_id=principal_id, limit=limit, status=None):
            if status_open(row.status):
                items.append(self._queue_item_from_decision(row))
        for row in self._container.memory_runtime.list_deadline_windows(principal_id=principal_id, limit=limit, status=None):
            if status_open(row.status):
                items.append(self._queue_item_from_deadline(row))
        items = [item for item in items if status_open(item.resolution_state)]
        items.sort(key=lambda item: (priority_weight(item.priority), due_bonus(item.deadline), item.title.lower()), reverse=True)
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
            self._record_product_event(
                principal_id=principal_id,
                event_type="queue_resolved",
                payload={"item_ref": item_ref, "action": decision, "actor": actor, "reason": reason or ""},
                source_id=request.approval_id,
            )
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
            if normalized in {"close", "done", "complete"}:
                next_status = "completed"
                event_type = "commitment_closed"
            elif normalized in {"drop", "dismiss"}:
                next_status = "cancelled"
                event_type = "commitment_dropped"
            else:
                next_status = "in_progress"
                event_type = "commitment_updated"
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
            self._record_product_event(
                principal_id=principal_id,
                event_type=event_type,
                payload={"item_ref": item_ref, "action": normalized or "update", "actor": actor, "reason": reason or ""},
                source_id=current.commitment_id,
            )
            return self._queue_item_from_commitment(self._commitment_item_from_commitment(updated))
        if item_ref.startswith("follow_up:"):
            current = self._container.memory_runtime.get_follow_up(item_ref.split(":", 1)[1], principal_id=principal_id)
            if current is None:
                return None
            if normalized in {"close", "done", "complete"}:
                next_status = "completed"
                event_type = "commitment_closed"
            elif normalized in {"drop", "dismiss"}:
                next_status = "cancelled"
                event_type = "commitment_dropped"
            else:
                next_status = "open"
                event_type = "commitment_updated"
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
            self._record_product_event(
                principal_id=principal_id,
                event_type=event_type,
                payload={"item_ref": item_ref, "action": normalized or "update", "actor": actor, "reason": reason or ""},
                source_id=current.follow_up_id,
            )
            return self._queue_item_from_commitment(
                self._commitment_item_from_follow_up(updated, self._stakeholder_lookup(principal_id))
            )
        if item_ref.startswith("human_task:"):
            current = self._container.orchestrator.fetch_human_task(item_ref.split(":", 1)[1], principal_id=principal_id)
            if current is None:
                return None
            operator_id = str(current.assigned_operator_id or actor or "").strip()
            if normalized in {"assign", "claim"}:
                updated = self._container.orchestrator.assign_human_task(
                    current.human_task_id,
                    principal_id=principal_id,
                    operator_id=operator_id,
                    assignment_source="manual",
                    assigned_by_actor_id=actor,
                )
            else:
                updated = self._container.orchestrator.return_human_task(
                    current.human_task_id,
                    principal_id=principal_id,
                    operator_id=operator_id,
                    resolution=reason or "completed",
                    returned_payload_json={"action": normalized or "complete"},
                    provenance_json={"source": "product_queue"},
                )
            if updated is None:
                return None
            self._record_product_event(
                principal_id=principal_id,
                event_type="handoff_completed" if normalized not in {"assign", "claim"} else "handoff_assigned",
                payload={"item_ref": item_ref, "action": normalized or "complete", "actor": actor, "operator_id": operator_id},
                source_id=current.human_task_id,
            )
            return self._queue_item_from_human_task(updated)
        if item_ref.startswith("decision:"):
            current = self._container.memory_runtime.get_decision_window(item_ref.split(":", 1)[1], principal_id=principal_id)
            if current is None:
                return None
            next_status = "decided" if normalized in {"resolve", "close", "done", "complete"} else "open"
            updated = self._container.memory_runtime.upsert_decision_window(
                principal_id=principal_id,
                decision_window_id=current.decision_window_id,
                title=current.title,
                context=current.context,
                opens_at=current.opens_at,
                closes_at=due_at or current.closes_at,
                urgency=current.urgency,
                authority_required=current.authority_required,
                status=next_status,
                notes=reason or current.notes,
                source_json=dict(current.source_json or {}),
            )
            self._record_product_event(
                principal_id=principal_id,
                event_type="queue_resolved",
                payload={"item_ref": item_ref, "action": normalized or "resolve", "actor": actor, "reason": reason or ""},
                source_id=current.decision_window_id,
            )
            return self._queue_item_from_decision(updated)
        if item_ref.startswith("deadline:"):
            current = self._container.memory_runtime.get_deadline_window(item_ref.split(":", 1)[1], principal_id=principal_id)
            if current is None:
                return None
            next_status = "elapsed" if normalized in {"resolve", "close", "done", "complete"} else "open"
            updated = self._container.memory_runtime.upsert_deadline_window(
                principal_id=principal_id,
                window_id=current.window_id,
                title=current.title,
                start_at=current.start_at,
                end_at=due_at or current.end_at,
                status=next_status,
                priority=current.priority,
                notes=reason or current.notes,
                source_json=dict(current.source_json or {}),
            )
            self._record_product_event(
                principal_id=principal_id,
                event_type="queue_resolved",
                payload={"item_ref": item_ref, "action": normalized or "resolve", "actor": actor, "reason": reason or ""},
                source_id=current.window_id,
            )
            return self._queue_item_from_deadline(updated)
        return None

    def _brief_item_from_queue(self, row: DecisionQueueItem, *, workspace_id: str) -> BriefItem:
        return BriefItem(
            id=row.id,
            workspace_id=workspace_id,
            kind=row.queue_kind,
            title=row.title,
            summary=row.summary,
            score=float(priority_weight(row.priority) + due_bonus(row.deadline)),
            why_now=row.summary,
            evidence_refs=row.evidence_refs,
            related_people=(),
            related_commitment_ids=(row.id,) if row.queue_kind == "close_commitment" else (),
            recommended_action=row.queue_kind.replace("_", " "),
            status=row.resolution_state,
        )

    def list_brief_items(self, *, principal_id: str, limit: int = 20, operator_id: str = "") -> tuple[BriefItem, ...]:
        queue = self.list_queue(principal_id=principal_id, limit=max(limit, 10), operator_id=operator_id)
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
            importance_score=priority_weight(importance_key),
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
            open_loops += sum(1 for follow_up in follow_ups if status_open(follow_up.status) and str(follow_up.stakeholder_ref or "") == row.stakeholder_id)
            open_loops += sum(1 for commitment in commitments if status_open(commitment.status) and row.display_name.lower() in str(commitment.details or "").lower())
            rows.append(self._person_profile(row, open_loops_count=open_loops))
        rows.sort(key=lambda row: (row.importance_score, row.open_loops_count, row.display_name.lower()), reverse=True)
        return tuple(rows[:limit])

    def get_person(self, *, principal_id: str, person_id: str) -> PersonProfile | None:
        found = self._container.memory_runtime.get_stakeholder(person_id, principal_id=principal_id)
        if found is None:
            return None
        people = {row.id: row for row in self.list_people(principal_id=principal_id, limit=200)}
        return people.get(found.stakeholder_id, self._person_profile(found, open_loops_count=len(dict(found.open_loops_json or {}))))

    def get_person_detail(self, *, principal_id: str, person_id: str, operator_id: str = "") -> PersonDetail | None:
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
            return any(contains_token(value, token) for token in person_tokens for value in values)

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
            for row in self.list_queue(principal_id=principal_id, limit=100, operator_id=operator_id)
            if _matches(
                row.title,
                row.summary,
                row.evidence_refs[0].note if row.evidence_refs else "",
            )
        )
        handoffs = tuple(
            row
            for row in self.list_handoffs(principal_id=principal_id, limit=100, operator_id=operator_id)
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
            history=self._history_entries(principal_id=principal_id, source_ids=(person_id,), limit=12),
        )

    def get_person_history(self, *, principal_id: str, person_id: str, limit: int = 20) -> tuple[HistoryEntry, ...]:
        return self._history_entries(principal_id=principal_id, source_ids=(person_id,), limit=limit)

    def correct_person_profile(
        self,
        *,
        principal_id: str,
        person_id: str,
        preferred_tone: str = "",
        add_theme: str = "",
        remove_theme: str = "",
        add_risk: str = "",
        remove_risk: str = "",
    ) -> PersonDetail | None:
        current = self._container.memory_runtime.get_stakeholder(person_id, principal_id=principal_id)
        if current is None:
            return None
        open_loops = dict(current.open_loops_json or {})
        risks = dict(current.friction_points_json or {})
        if add_theme.strip():
            open_loops[add_theme.strip().replace(" ", "_")] = True
        if remove_theme.strip():
            open_loops.pop(remove_theme.strip().replace(" ", "_"), None)
        if add_risk.strip():
            risks[add_risk.strip().replace(" ", "_")] = "user_corrected"
        if remove_risk.strip():
            risks.pop(remove_risk.strip().replace(" ", "_"), None)
        self._container.memory_runtime.upsert_stakeholder(
            principal_id=principal_id,
            stakeholder_id=current.stakeholder_id,
            display_name=current.display_name,
            channel_ref=current.channel_ref,
            authority_level=current.authority_level,
            importance=current.importance,
            response_cadence=current.response_cadence,
            tone_pref=preferred_tone.strip() or current.tone_pref,
            sensitivity=current.sensitivity,
            escalation_policy=current.escalation_policy,
            open_loops_json=open_loops,
            friction_points_json=risks,
            last_interaction_at=current.last_interaction_at,
            status=current.status,
            notes=current.notes,
        )
        self._record_product_event(
            principal_id=principal_id,
            event_type="memory_corrected",
            payload={
                "person_id": person_id,
                "preferred_tone": preferred_tone.strip(),
                "add_theme": add_theme.strip(),
                "remove_theme": remove_theme.strip(),
                "add_risk": add_risk.strip(),
                "remove_risk": remove_risk.strip(),
            },
            source_id=current.stakeholder_id,
        )
        return self.get_person_detail(principal_id=principal_id, person_id=person_id)

    def list_handoffs(
        self,
        *,
        principal_id: str,
        limit: int = 20,
        operator_id: str = "",
        status: str | None = "pending",
    ) -> tuple[HandoffNote, ...]:
        operator_key = str(operator_id or "").strip()
        rows: list[HandoffNote] = []
        for task in self._container.orchestrator.list_human_tasks(principal_id=principal_id, status=status, limit=limit):
            assigned = str(task.assigned_operator_id or "").strip()
            if operator_key and assigned and assigned != operator_key:
                continue
            rows.append(self._handoff_from_human_task(task))
        rows.sort(key=lambda row: (priority_weight(row.escalation_status), due_bonus(row.due_time), row.summary.lower()), reverse=True)
        return tuple(rows[:limit])

    def assign_handoff(self, *, principal_id: str, handoff_ref: str, operator_id: str, actor: str) -> HandoffNote | None:
        if not handoff_ref.startswith("human_task:"):
            return None
        updated = self._container.orchestrator.assign_human_task(
            handoff_ref.split(":", 1)[1],
            principal_id=principal_id,
            operator_id=operator_id,
            assignment_source="manual",
            assigned_by_actor_id=actor,
        )
        if updated is None:
            return None
        self._record_product_event(
            principal_id=principal_id,
            event_type="handoff_assigned",
            payload={"handoff_ref": handoff_ref, "operator_id": operator_id, "actor": actor},
            source_id=updated.human_task_id,
        )
        return self._handoff_from_human_task(updated)

    def complete_handoff(
        self,
        *,
        principal_id: str,
        handoff_ref: str,
        operator_id: str,
        actor: str,
        resolution: str,
    ) -> HandoffNote | None:
        if not handoff_ref.startswith("human_task:"):
            return None
        updated = self._container.orchestrator.return_human_task(
            handoff_ref.split(":", 1)[1],
            principal_id=principal_id,
            operator_id=operator_id,
            resolution=resolution or "completed",
            returned_payload_json={"source": "product_handoffs", "actor": actor},
            provenance_json={"source": "product_handoffs"},
        )
        if updated is None:
            return None
        self._record_product_event(
            principal_id=principal_id,
            event_type="handoff_completed",
            payload={"handoff_ref": handoff_ref, "operator_id": operator_id, "actor": actor, "resolution": resolution},
            source_id=updated.human_task_id,
        )
        return self._handoff_from_human_task(updated)

    def workspace_snapshot(self, *, principal_id: str, operator_id: str = "") -> ProductSnapshot:
        brief_items = self.list_brief_items(principal_id=principal_id, limit=8, operator_id=operator_id)
        queue_items = self.list_queue(principal_id=principal_id, limit=10, operator_id=operator_id)
        commitments = self.list_commitments(principal_id=principal_id, limit=10)
        commitment_candidates = self.list_commitment_candidates(principal_id=principal_id, limit=8)
        drafts = self.list_drafts(principal_id=principal_id, limit=8)
        people = self.list_people(principal_id=principal_id, limit=8)
        handoffs = self.list_handoffs(principal_id=principal_id, limit=8, operator_id=operator_id)
        completed_handoffs = self.list_handoffs(
            principal_id=principal_id,
            limit=6,
            operator_id=operator_id,
            status="returned",
        )
        return ProductSnapshot(
            brief_items=brief_items,
            queue_items=queue_items,
            commitments=commitments,
            commitment_candidates=commitment_candidates,
            drafts=drafts,
            people=people,
            handoffs=handoffs,
            completed_handoffs=completed_handoffs,
            stats_json={
                "brief_items": len(brief_items),
                "queue_items": len(queue_items),
                "commitments": len(commitments),
                "commitment_candidates": len(commitment_candidates),
                "drafts": len(drafts),
                "people": len(people),
                "handoffs": len(handoffs),
                "completed_handoffs": len(completed_handoffs),
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
        product_events = [
            row
            for row in self._container.channel_runtime.list_recent_observations(limit=200, principal_id=principal_id)
            if str(row.channel or "").strip() == "product"
        ]
        event_rows = sorted(product_events, key=lambda row: str(row.created_at or ""))
        analytics_counts: dict[str, int] = {}
        activation_started_at = ""
        first_value_at = ""
        first_value_event = ""
        first_value_types = {"draft_approved", "commitment_created", "commitment_closed", "handoff_completed", "memory_corrected", "memo_opened"}
        for row in event_rows:
            analytics_counts[row.event_type] = int(analytics_counts.get(row.event_type, 0) or 0) + 1
            created_at = str(row.created_at or "").strip()
            if row.event_type == "activation_opened" and created_at and not activation_started_at:
                activation_started_at = created_at
            if row.event_type in first_value_types and created_at and not first_value_at:
                first_value_at = created_at
                first_value_event = row.event_type
        first_value_seconds: int | None = None
        if activation_started_at and first_value_at:
            try:
                started = datetime.fromisoformat(activation_started_at.replace("Z", "+00:00"))
                reached = datetime.fromisoformat(first_value_at.replace("Z", "+00:00"))
                first_value_seconds = max(int((reached - started).total_seconds()), 0)
            except Exception:
                first_value_seconds = None
        seats_used = len(operators)
        seat_limit = int(plan.entitlements.operator_seats or 0)
        seats_remaining = max(seat_limit - seats_used, 0)
        seat_overage = max(seats_used - seat_limit, 0)
        selected_messaging = sorted({value for value in selected_channels if value in {"telegram", "whatsapp"}})
        warnings: list[str] = []
        if seat_overage:
            warnings.append("Active operators exceed included seats.")
        if selected_messaging and not plan.entitlements.messaging_channels_enabled:
            warnings.append("Messaging channels are selected but not included in this plan.")
        if not readiness_ok:
            warnings.append(str(readiness_label or "Runtime readiness needs attention."))
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
            "billing": {
                "billing_state": plan.billing_state,
                "support_tier": plan.support_tier,
                "renewal_owner_role": plan.renewal_owner_role,
                "contract_note": plan.contract_note,
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
                "active_count": seats_used,
                "seats_used": seats_used,
                "seats_remaining": seats_remaining,
                "seat_overage": seat_overage,
                "active_operator_ids": [str(row.operator_id or "") for row in operators if str(row.operator_id or "").strip()],
                "active_operator_names": [str(row.display_name or row.operator_id or "") for row in operators if str(row.display_name or row.operator_id or "").strip()],
            },
            "commercial": {
                "selected_messaging_channels": selected_messaging,
                "messaging_scope_mismatch": bool(selected_messaging and not plan.entitlements.messaging_channels_enabled),
                "warnings": warnings,
            },
            "providers": {
                "provider_count": int(registry.get("provider_count") or 0),
                "lane_count": int(registry.get("lane_count") or 0),
            },
            "usage": dict(snapshot.stats_json or {}),
            "analytics": {
                "counts": analytics_counts,
                "activation_started_at": activation_started_at,
                "first_value_at": first_value_at,
                "first_value_event": first_value_event,
                "time_to_first_value_seconds": first_value_seconds,
                "recent_events": [
                    {
                        "event_type": row.event_type,
                        "created_at": row.created_at,
                        "source_id": row.source_id,
                        "payload": dict(row.payload or {}),
                    }
                    for row in product_events[:12]
                ],
            },
        }

    def workspace_support_bundle(self, *, principal_id: str) -> dict[str, object]:
        diagnostics = self.workspace_diagnostics(principal_id=principal_id)
        approvals = self._container.orchestrator.list_pending_approvals_for_principal(principal_id=principal_id, limit=25)
        approval_history = self._container.orchestrator.list_approval_history_for_principal(principal_id=principal_id, limit=25)
        human_tasks = self._container.orchestrator.list_human_tasks(principal_id=principal_id, status=None, limit=25)
        provider_registry = self._container.provider_registry.registry_read_model(principal_id=principal_id)
        pending_delivery = self._container.channel_runtime.list_pending_delivery(limit=25, principal_id=principal_id)
        return {
            "workspace": diagnostics["workspace"],
            "selected_channels": diagnostics["selected_channels"],
            "plan": diagnostics["plan"],
            "billing": diagnostics["billing"],
            "entitlements": diagnostics["entitlements"],
            "readiness": diagnostics["readiness"],
            "usage": diagnostics["usage"],
            "analytics": diagnostics["analytics"],
            "approvals": {
                "pending": [
                    {
                        "approval_id": row.approval_id,
                        "reason": row.reason,
                        "status": row.status,
                        "expires_at": row.expires_at,
                        "session_id": row.session_id,
                    }
                    for row in approvals
                ],
                "recent_decisions": [
                    {
                        "decision_id": row.decision_id,
                        "approval_id": row.approval_id,
                        "decision": row.decision,
                        "reason": row.reason,
                        "created_at": row.created_at,
                    }
                    for row in approval_history
                ],
            },
            "human_tasks": [
                {
                    "human_task_id": row.human_task_id,
                    "brief": row.brief,
                    "status": row.status,
                    "assignment_state": row.assignment_state,
                    "assigned_operator_id": row.assigned_operator_id,
                    "priority": row.priority,
                    "sla_due_at": row.sla_due_at,
                }
                for row in human_tasks
            ],
            "providers": provider_registry,
            "pending_delivery": [
                {
                    "delivery_id": row.delivery_id,
                    "channel": row.channel,
                    "recipient": row.recipient,
                    "status": row.status,
                    "attempt_count": row.attempt_count,
                    "last_error": row.last_error,
                }
                for row in pending_delivery
            ],
        }

    def record_surface_event(
        self,
        *,
        principal_id: str,
        event_type: str,
        surface: str,
        actor: str = "",
        metadata: dict[str, object] | None = None,
    ) -> None:
        normalized_type = str(event_type or "").strip().lower()
        normalized_surface = str(surface or "").strip().lower()
        if not normalized_type or not normalized_surface:
            return
        payload = {
            "surface": normalized_surface,
            "actor": str(actor or "").strip() or "browser",
        }
        if metadata:
            payload.update(dict(metadata))
        self._record_product_event(
            principal_id=principal_id,
            event_type=normalized_type,
            payload=payload,
            source_id=normalized_surface,
        )


def build_product_service(container: AppContainer) -> ProductService:
    return ProductService(container)
