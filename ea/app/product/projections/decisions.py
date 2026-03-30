from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.domain.models import DecisionWindow
from app.product.models import DecisionItem, EvidenceRef
from app.product.projections.common import compact_text, parse_when


def _decision_sla_status(status: str, due_at: str | None, *, now: datetime | None = None) -> str:
    normalized_status = str(status or "").strip().lower()
    if normalized_status in {"decided", "closed", "completed"}:
        return "resolved"
    due_when = parse_when(due_at)
    if due_when is None:
        return "unscheduled"
    current = now or datetime.now(timezone.utc)
    if due_when <= current:
        return "due_now"
    if due_when <= current + timedelta(days=2):
        return "due_soon"
    return "on_track"


def decision_item_from_window(row: DecisionWindow) -> DecisionItem:
    source = dict(row.source_json or {})
    options_raw = source.get("options") or ()
    if not isinstance(options_raw, (list, tuple)):
        options_raw = ()
    related_commitments_raw = source.get("commitment_refs") or source.get("commitment_ids") or ()
    if not isinstance(related_commitments_raw, (list, tuple)):
        related_commitments_raw = ()
    thread_refs_raw = source.get("thread_refs") or source.get("thread_ids") or ()
    if not isinstance(thread_refs_raw, (list, tuple)):
        thread_refs_raw = (thread_refs_raw,) if thread_refs_raw else ()
    related_people_raw = source.get("people") or source.get("stakeholders") or ()
    if not isinstance(related_people_raw, (list, tuple)):
        related_people_raw = ()
    options = tuple(str(value).strip() for value in options_raw if str(value).strip())
    recommendation = str(source.get("recommended_option") or source.get("recommendation") or "").strip()
    if not recommendation and options:
        recommendation = options[0]
    impact_summary = str(source.get("impact_summary") or source.get("impact") or "").strip()
    if not impact_summary:
        if related_commitments_raw:
            impact_summary = f"Protects {len(tuple(str(value).strip() for value in related_commitments_raw if str(value).strip()))} downstream commitments."
        elif related_people_raw:
            impact_summary = f"Affects {len(tuple(str(value).strip() for value in related_people_raw if str(value).strip()))} key stakeholders."
        else:
            impact_summary = "Keeps the office loop from stalling on an open choice."
    due_at = row.closes_at or row.opens_at
    decision_type = str(source.get("decision_type") or source.get("kind") or source.get("category") or "office_decision").strip()
    rationale = compact_text(
        row.context or row.notes,
        fallback="Decision window is open and needs an explicit owner or choice.",
    )
    next_action = str(source.get("next_action") or "").strip()
    if not next_action:
        if str(row.status or "").strip().lower() in {"decided", "closed", "completed"}:
            next_action = "Review downstream commitments and confirm the office loop actually moved."
        elif str(row.authority_required or "").strip().lower() in {"principal", "exec", "executive"}:
            next_action = "Escalate the current recommendation to the principal and clear the blocking choice."
        else:
            next_action = "Resolve the choice, then confirm the affected commitments and threads were updated."
    return DecisionItem(
        id=f"decision:{row.decision_window_id}",
        title=row.title,
        summary=rationale,
        priority=row.urgency,
        owner_role=row.authority_required or "principal",
        due_at=due_at,
        status=row.status,
        decision_type=decision_type,
        recommendation=recommendation,
        next_action=next_action,
        rationale=rationale,
        options=options,
        evidence_refs=(
            EvidenceRef(
                ref_id=f"decision:{row.decision_window_id}",
                label="Decision window",
                source_type="decision",
                note=row.notes or row.context or row.status,
            ),
        ),
        related_commitment_ids=tuple(str(value).strip() for value in related_commitments_raw if str(value).strip()),
        linked_thread_ids=tuple(str(value).strip() for value in thread_refs_raw if str(value).strip()),
        related_people=tuple(str(value).strip() for value in related_people_raw if str(value).strip()),
        impact_summary=impact_summary,
        sla_status=_decision_sla_status(row.status, due_at),
        resolution_reason=str(source.get("resolution_reason") or source.get("escalation_reason") or "").strip(),
    )
