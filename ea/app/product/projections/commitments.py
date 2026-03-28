from __future__ import annotations

from app.domain.models import Commitment, FollowUp, Stakeholder
from app.product.models import CommitmentItem, EvidenceRef
from app.product.projections.common import compact_text, due_bonus, priority_weight, product_commitment_status


def _as_float(value: object, *, default: float = 0.5) -> float:
    try:
        return float(value if value is not None else default)
    except (TypeError, ValueError):
        return default


def _as_str_tuple(value: object) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    return tuple(str(item).strip() for item in value if str(item).strip())


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
        confidence=_as_float(source.get("confidence"), default=0.82),
        channel_hint=str(source.get("channel_hint") or "email"),
        resolution_code=str(source.get("resolution_code") or ""),
        resolution_reason=str(source.get("resolution_reason") or ""),
        duplicate_of_ref=str(source.get("duplicate_of_ref") or ""),
        merged_into_ref=str(source.get("merged_into_ref") or ""),
        merged_from_refs=_as_str_tuple(source.get("merged_from_refs")),
    )


def commitment_item_from_follow_up(row: FollowUp, stakeholders: dict[str, Stakeholder]) -> CommitmentItem:
    source = dict(row.source_json or {})
    stakeholder = stakeholders.get(str(row.stakeholder_ref or "").strip())
    return CommitmentItem(
        id=f"follow_up:{row.follow_up_id}",
        source_type=str(source.get("source_type") or "follow_up"),
        source_ref=str(source.get("source_ref") or row.follow_up_id),
        statement=row.topic,
        owner=str(source.get("owner") or "office"),
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
        confidence=_as_float(source.get("confidence"), default=0.78),
        channel_hint=str(source.get("channel_hint") or row.channel_hint or "email"),
        resolution_code=str(source.get("resolution_code") or ""),
        resolution_reason=str(source.get("resolution_reason") or ""),
        duplicate_of_ref=str(source.get("duplicate_of_ref") or ""),
        merged_into_ref=str(source.get("merged_into_ref") or ""),
        merged_from_refs=_as_str_tuple(source.get("merged_from_refs")),
    )
