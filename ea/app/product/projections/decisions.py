from __future__ import annotations

from app.domain.models import DecisionWindow
from app.product.models import DecisionItem, EvidenceRef
from app.product.projections.common import compact_text


def _decision_sla_status(status: str, due_at: str | None) -> str:
    normalized_status = str(status or "").strip().lower()
    if normalized_status in {"decided", "closed", "completed"}:
        return "resolved"
    normalized_due = str(due_at or "").strip()
    if not normalized_due:
        return "unscheduled"
    if normalized_due <= "2026-03-25T23:59:59+00:00":
        return "due_now"
    if normalized_due <= "2026-03-27T00:00:00+00:00":
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
    rationale = compact_text(
        row.context or row.notes,
        fallback="Decision window is open and needs an explicit owner or choice.",
    )
    return DecisionItem(
        id=f"decision:{row.decision_window_id}",
        title=row.title,
        summary=rationale,
        priority=row.urgency,
        owner_role=row.authority_required or "principal",
        due_at=due_at,
        status=row.status,
        recommendation=recommendation,
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
        related_people=tuple(str(value).strip() for value in related_people_raw if str(value).strip()),
        impact_summary=impact_summary,
        sla_status=_decision_sla_status(row.status, due_at),
        resolution_reason=str(source.get("resolution_reason") or source.get("escalation_reason") or "").strip(),
    )
