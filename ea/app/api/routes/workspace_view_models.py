from __future__ import annotations

from app.product.models import BriefItem, CommitmentItem, DecisionQueueItem, DraftCandidate, HandoffNote, PersonProfile, ProductSnapshot


def _row(title: str, detail: str, tag: str, href: str = "") -> dict[str, str]:
    row = {"title": title, "detail": detail, "tag": tag}
    if href:
        row["href"] = href
    return row


def _brief_rows(values: tuple[BriefItem, ...], *, tag: str) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for value in values:
        rows.append(_row(value.title, value.why_now or value.summary, tag))
    return rows


def _queue_rows(values: tuple[DecisionQueueItem, ...]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for value in values:
        due = f" · due {value.deadline[:10]}" if value.deadline else ""
        rows.append(_row(value.title, f"{value.summary}{due}".strip(), value.priority.capitalize()))
    return rows


def _commitment_rows(values: tuple[CommitmentItem, ...]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for value in values:
        detail = " · ".join(
            part
            for part in (
                value.counterparty,
                f"Due {value.due_at[:10]}" if value.due_at else "",
                value.proof_refs[0].note if value.proof_refs else "",
            )
            if part
        )
        rows.append(_row(value.statement, detail or "Commitment is still open.", value.risk_level.capitalize()))
    return rows


def _draft_rows(values: tuple[DraftCandidate, ...]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for value in values:
        detail = " · ".join(
            part
            for part in (
                value.intent.title(),
                value.send_channel,
                value.approval_status,
                value.draft_text[:96] if value.draft_text else "",
            )
            if part
        )
        rows.append(_row(value.recipient_summary or value.intent.title(), detail or "Draft awaiting review.", "Draft"))
    return rows


def _people_rows(values: tuple[PersonProfile, ...]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for value in values:
        detail = " · ".join(
            part
            for part in (
                value.role_or_company,
                f"{value.open_loops_count} open loops" if value.open_loops_count else "",
                ", ".join(value.themes[:2]) if value.themes else "",
            )
            if part
        )
        rows.append(_row(value.display_name, detail or "Relationship context is still forming.", value.relationship_temperature.title(), href=f"/app/people/{value.id}"))
    return rows


def _handoff_rows(values: tuple[HandoffNote, ...]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for value in values:
        detail = " · ".join(
            part
            for part in (
                value.owner,
                f"Due {value.due_time[:10]}" if value.due_time else "",
                value.evidence_refs[0].note if value.evidence_refs else "",
            )
            if part
        )
        rows.append(_row(value.summary, detail or "Handoff remains open.", value.escalation_status.capitalize()))
    return rows


def workspace_section_payload(section: str, snapshot: ProductSnapshot) -> dict[str, object]:
    stats = [
        {"label": "Memo items", "value": str(snapshot.stats_json.get("brief_items", 0))},
        {"label": "Queue items", "value": str(snapshot.stats_json.get("queue_items", 0))},
        {"label": "Commitments", "value": str(snapshot.stats_json.get("commitments", 0))},
        {"label": "People", "value": str(snapshot.stats_json.get("people", 0))},
    ]
    mapping: dict[str, dict[str, object]] = {
        "today": {
            "title": "Morning Memo",
            "summary": "What changed, what is blocked, and what deserves attention before the day drifts.",
            "cards": [
                {
                    "eyebrow": "Morning memo",
                    "title": "What changed since the last clear loop",
                    "body": "The memo is now backed by real queue objects, active commitments, and real stakeholder pressure.",
                    "items": _brief_rows(snapshot.brief_items[:6], tag="Memo"),
                },
                {
                    "eyebrow": "Next to clear",
                    "title": "What needs a decision now",
                    "body": "Approvals, assignments, and deadlines belong in one bounded queue.",
                    "items": _queue_rows(snapshot.queue_items[:6]),
                },
                {
                    "eyebrow": "Commitments at risk",
                    "title": "What is most likely to slip",
                    "body": "Promises, deadlines, and follow-ups are visible instead of buried inside inbox state.",
                    "items": _commitment_rows(snapshot.commitments[:6]),
                },
                {
                    "eyebrow": "Stakeholder movement",
                    "title": "Who needs attention",
                    "body": "People pressure is part of the office loop, not an afterthought.",
                    "items": _people_rows(snapshot.people[:6]),
                },
            ],
        },
        "briefing": {
            "title": "Decision Queue",
            "summary": "Clear the day by resolving what is blocked, what needs approval, and which commitments are running out of runway.",
            "cards": [
                {
                    "eyebrow": "Decision queue",
                    "title": "What must be resolved next",
                    "body": "Each row is a real queue item with evidence and an obvious next move.",
                    "items": _queue_rows(snapshot.queue_items[:8]),
                },
                {
                    "eyebrow": "Memo context",
                    "title": "Why these items surfaced",
                    "body": "The memo should explain the queue, not duplicate it.",
                    "items": _brief_rows(snapshot.brief_items[:6], tag="Reason"),
                },
                {
                    "eyebrow": "Stakeholders",
                    "title": "Who is affected",
                    "body": "People stay attached to decisions, approvals, and commitments.",
                    "items": _people_rows(snapshot.people[:6]),
                },
                {
                    "eyebrow": "Open commitments",
                    "title": "What the queue is protecting",
                    "body": "Decisions only matter because they keep commitments from slipping.",
                    "items": _commitment_rows(snapshot.commitments[:6]),
                },
            ],
        },
        "inbox": {
            "title": "Commitments",
            "summary": "The inbox is now a commitment ledger: active promises, reviewable drafts, and the next outbound moves.",
            "cards": [
                {
                    "eyebrow": "Commitment ledger",
                    "title": "What is still open",
                    "body": "Messages and meetings matter because they create or update commitments.",
                    "items": _commitment_rows(snapshot.commitments[:8]),
                },
                {
                    "eyebrow": "Draft queue",
                    "title": "What is ready for review",
                    "body": "Drafts are backed by approval requests instead of generic placeholder cards.",
                    "items": _draft_rows(snapshot.drafts[:6]),
                },
                {
                    "eyebrow": "Decision pressure",
                    "title": "What will force movement next",
                    "body": "The commitment loop stays honest when decisions and deadlines remain visible.",
                    "items": _queue_rows(snapshot.queue_items[:6]),
                },
            ],
        },
        "follow-ups": {
            "title": "Handoffs",
            "summary": "Keep operator work, principal review, and unresolved follow-up movement visible in one lane.",
            "cards": [
                {
                    "eyebrow": "Open handoffs",
                    "title": "What is waiting on a human",
                    "body": "Handoffs are backed by real human tasks instead of suggestion copy.",
                    "items": _handoff_rows(snapshot.handoffs[:8]),
                },
                {
                    "eyebrow": "Still open",
                    "title": "What handoffs are protecting",
                    "body": "Handoffs exist because commitments or approvals still need movement.",
                    "items": _commitment_rows(snapshot.commitments[:6]),
                },
                {
                    "eyebrow": "Related queue",
                    "title": "What will come back for review",
                    "body": "Operator work should feed back into the queue cleanly.",
                    "items": _queue_rows(snapshot.queue_items[:6]),
                },
                {
                    "eyebrow": "Stakeholders",
                    "title": "Who the handoff affects",
                    "body": "The office loop stays legible when people stay attached to the work.",
                    "items": _people_rows(snapshot.people[:6]),
                },
            ],
        },
        "memory": {
            "title": "People Graph",
            "summary": "People, relationship temperature, open loops, and recurring themes live in one durable relationship system.",
            "cards": [
                {
                    "eyebrow": "People graph",
                    "title": "Who matters right now",
                    "body": "This surface is now backed by stakeholder records and open loops instead of memo hints alone.",
                    "items": _people_rows(snapshot.people[:8]),
                },
                {
                    "eyebrow": "Open loops",
                    "title": "What still hangs off those relationships",
                    "body": "Relationship value comes from the loops still attached to each person.",
                    "items": _commitment_rows(snapshot.commitments[:6]),
                },
                {
                    "eyebrow": "Office pressure",
                    "title": "Which people are shaping the queue",
                    "body": "The queue should stay attached to the people who make it matter.",
                    "items": _queue_rows(snapshot.queue_items[:6]),
                },
            ],
        },
        "contacts": {
            "title": "Evidence",
            "summary": "Evidence should explain why something surfaced, what supports it, and what action it is driving.",
            "cards": [
                {
                    "eyebrow": "Evidence refs",
                    "title": "What supports the memo",
                    "body": "Brief items and queue items carry references instead of relying on trust-note filler.",
                    "items": _brief_rows(snapshot.brief_items[:8], tag="Evidence"),
                },
                {
                    "eyebrow": "Queue provenance",
                    "title": "Where the current pressure came from",
                    "body": "Approvals, tasks, commitments, and deadlines should all remain explainable.",
                    "items": _queue_rows(snapshot.queue_items[:8]),
                },
                {
                    "eyebrow": "Relationship context",
                    "title": "Who the evidence touches",
                    "body": "Evidence is useful when it stays connected to the right people and commitments.",
                    "items": _people_rows(snapshot.people[:6]),
                },
            ],
        },
    }
    return {"stats": stats, **mapping[section]}
