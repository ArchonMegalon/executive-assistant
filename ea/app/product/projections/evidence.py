from __future__ import annotations

from dataclasses import replace

from app.product.models import BriefItem, CommitmentItem, DecisionItem, DecisionQueueItem, DraftCandidate, EvidenceItem, HandoffNote, ThreadItem


def evidence_items_from_objects(
    *,
    brief_items: tuple[BriefItem, ...],
    queue_items: tuple[DecisionQueueItem, ...],
    commitments: tuple[CommitmentItem, ...],
    drafts: tuple[DraftCandidate, ...],
    decisions: tuple[DecisionItem, ...],
    handoffs: tuple[HandoffNote, ...],
    threads: tuple[ThreadItem, ...],
    limit: int = 40,
) -> tuple[EvidenceItem, ...]:
    rows: dict[str, EvidenceItem] = {}
    related: dict[str, set[str]] = {}

    def _remember(object_ref: str, refs) -> None:  # type: ignore[no-untyped-def]
        for ref in refs:
            key = str(ref.ref_id or "").strip() or str(ref.label or "").strip()
            if not key:
                continue
            related.setdefault(key, set()).add(object_ref)
            if key in rows:
                continue
            rows[key] = EvidenceItem(
                id=key,
                label=ref.label,
                source_type=ref.source_type or "evidence",
                summary=ref.note or ref.label,
                href=ref.href,
                related_object_refs=(),
            )

    for item in brief_items:
        _remember(item.id, item.evidence_refs)
    for item in queue_items:
        _remember(item.id, item.evidence_refs)
    for item in commitments:
        _remember(item.id, item.proof_refs)
    for item in drafts:
        _remember(item.id, item.provenance_refs)
    for item in decisions:
        _remember(item.id, item.evidence_refs)
    for item in handoffs:
        _remember(item.id, item.evidence_refs)
    for item in threads:
        _remember(item.id, item.evidence_refs)

    built = [
        replace(item, related_object_refs=tuple(sorted(related.get(item.id, ()))[:8]))
        for item in rows.values()
    ]
    built.sort(key=lambda item: (item.source_type, item.label.lower(), item.id.lower()))
    return tuple(built[:limit])
