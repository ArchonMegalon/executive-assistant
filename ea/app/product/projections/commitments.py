from __future__ import annotations

from app.domain.models import Commitment, FollowUp, Stakeholder
from app.product.models import CommitmentItem, EvidenceRef
from app.product.projections.common import compact_text, due_bonus, priority_weight, product_commitment_status


def commitment_item_from_commitment(row: Commitment) -> CommitmentItem:
    source = dict(row.source_json or {})
    return CommitmentItem(
        id=f"commitment:{row.commitment_id}",
        source_type=str(source.get("source_type") or "manual"),
        source_ref=str(source.get("source_ref") or row.commitment_id),
        statement=row.title,
        owner=str(source.get("owner") or "office"),
        counterparty=str(source.get("counterparty") or source.get("stakeholder") or ""),
        due_at=row.due_at,
        status=product_commitment_status(row.status),
        last_activity_at=row.updated_at,
        risk_level="high" if due_bonus(row.due_at) >= 28 or priority_weight(row.priority) >= 80 else "medium",
        proof_refs=(
            EvidenceRef(
                ref_id=f"commitment:{row.commitment_id}",
                label="Commitment",
                source_type="commitment",
                note=compact_text(row.details, fallback="Commitment is stored in workspace memory."),
            ),
        ),
    )


def commitment_item_from_follow_up(row: FollowUp, stakeholders: dict[str, Stakeholder]) -> CommitmentItem:
    stakeholder = stakeholders.get(str(row.stakeholder_ref or "").strip())
    return CommitmentItem(
        id=f"follow_up:{row.follow_up_id}",
        source_type="follow_up",
        source_ref=row.follow_up_id,
        statement=row.topic,
        owner="office",
        counterparty=stakeholder.display_name if stakeholder is not None else str(row.stakeholder_ref or ""),
        due_at=row.due_at,
        status=product_commitment_status(row.status),
        last_activity_at=row.updated_at,
        risk_level="high" if due_bonus(row.due_at) >= 28 else "medium",
        proof_refs=(
            EvidenceRef(
                ref_id=f"follow_up:{row.follow_up_id}",
                label="Follow-up",
                source_type="follow_up",
                note=compact_text(row.notes, fallback="Follow-up remains open in the workspace ledger."),
            ),
        ),
    )
