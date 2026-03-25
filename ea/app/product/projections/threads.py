from __future__ import annotations

from app.product.models import CommitmentItem, DecisionItem, DraftCandidate, ThreadItem
from app.product.projections.common import compact_text, contains_token


def thread_items_from_objects(
    drafts: tuple[DraftCandidate, ...],
    commitments: tuple[CommitmentItem, ...],
    decisions: tuple[DecisionItem, ...],
    *,
    limit: int = 20,
) -> tuple[ThreadItem, ...]:
    rows: list[ThreadItem] = []
    seen: set[str] = set()
    for draft in drafts:
        thread_ref = str(draft.thread_ref or draft.id).strip() or draft.id
        thread_id = thread_ref if thread_ref.startswith("thread:") else f"thread:{thread_ref}"
        if thread_id in seen:
            continue
        seen.add(thread_id)
        counterparties = tuple(
            value
            for value in {
                str(draft.recipient_summary or "").strip(),
                str(draft.send_channel or "").strip(),
            }
            if value and value != draft.send_channel
        )
        related_commitments = tuple(
            item.id
            for item in commitments
            if contains_token(item.counterparty, draft.recipient_summary)
            or contains_token(item.statement, draft.recipient_summary)
            or contains_token(item.statement, draft.thread_ref)
        )
        related_decisions = tuple(
            item.id
            for item in decisions
            if contains_token(item.title, draft.recipient_summary)
            or contains_token(item.summary, draft.recipient_summary)
        )
        rows.append(
            ThreadItem(
                id=thread_id,
                title=str(draft.recipient_summary or draft.intent or thread_ref),
                channel=str(draft.send_channel or "email"),
                status=str(draft.approval_status or "open"),
                last_activity_at=None,
                summary=compact_text(draft.draft_text, fallback="Draft-backed thread is active in the decision loop."),
                counterparties=counterparties,
                draft_ids=(draft.id,),
                related_commitment_ids=related_commitments,
                related_decision_ids=related_decisions,
                evidence_refs=draft.provenance_refs,
            )
        )
    rows.sort(key=lambda item: (item.status, item.title.lower()))
    return tuple(rows[:limit])
