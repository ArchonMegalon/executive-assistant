from __future__ import annotations

from app.domain.models import DecisionWindow
from app.product.models import DecisionItem, EvidenceRef
from app.product.projections.common import compact_text


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
        due_at=row.closes_at or row.opens_at,
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
    )
