from __future__ import annotations

from app.product.models import BriefItem, CommitmentCandidate, CommitmentItem, DecisionItem, DecisionQueueItem, DraftCandidate, EvidenceItem, HandoffNote, PersonProfile, ProductSnapshot, RuleItem, ThreadItem


def _row(
    title: str,
    detail: str,
    tag: str,
    href: str = "",
    action_href: str = "",
    action_label: str = "",
    action_value: str = "",
    action_method: str = "",
    return_to: str = "",
    secondary_action_href: str = "",
    secondary_action_label: str = "",
    secondary_action_value: str = "",
    secondary_action_method: str = "",
    secondary_return_to: str = "",
) -> dict[str, str]:
    row = {"title": title, "detail": detail, "tag": tag}
    if href:
        row["href"] = href
    if action_href:
        row["action_href"] = action_href
    if action_label:
        row["action_label"] = action_label
    if action_value:
        row["action_value"] = action_value
    if action_method:
        row["action_method"] = action_method
    if return_to:
        row["return_to"] = return_to
    if secondary_action_href:
        row["secondary_action_href"] = secondary_action_href
    if secondary_action_label:
        row["secondary_action_label"] = secondary_action_label
    if secondary_action_value:
        row["secondary_action_value"] = secondary_action_value
    if secondary_action_method:
        row["secondary_action_method"] = secondary_action_method
    if secondary_return_to:
        row["secondary_return_to"] = secondary_return_to
    return row


def _brief_rows(values: tuple[BriefItem, ...], *, tag: str) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for value in values:
        href = ""
        object_ref = str(value.object_ref or "").strip()
        if object_ref.startswith("decision:"):
            href = f"/app/decisions/{object_ref}"
        elif object_ref.startswith(("commitment:", "follow_up:")):
            href = f"/app/commitment-items/{object_ref}"
        elif object_ref.startswith("human_task:"):
            href = f"/app/handoffs/{object_ref}"
        detail = " · ".join(
            part
            for part in (
                value.why_now or value.summary,
                f"{value.evidence_count} evidence" if value.evidence_count else "",
                f"{int(round(value.confidence * 100))}% confidence" if value.confidence else "",
            )
            if part
        )
        rows.append(_row(value.title, detail, tag, href=href))
    return rows


def _queue_rows(values: tuple[DecisionQueueItem, ...]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for value in values:
        due = f" · due {value.deadline[:10]}" if value.deadline else ""
        action_href = ""
        action_label = ""
        action_value = ""
        if value.id.startswith("approval:"):
            action_href = f"/app/actions/drafts/{value.id}/approve"
            action_label = "Approve"
        elif value.id.startswith(("commitment:", "follow_up:")):
            action_href = f"/app/actions/queue/{value.id}/resolve"
            action_label = "Close"
            action_value = "close"
        elif value.id.startswith(("decision:", "deadline:")):
            action_href = f"/app/actions/queue/{value.id}/resolve"
            action_label = "Resolve"
            action_value = "resolve"
        rows.append(
            _row(
                value.title,
                f"{value.summary}{due}".strip(),
                value.priority.capitalize(),
                action_href=action_href,
                action_label=action_label,
                action_value=action_value,
                return_to="/app/briefing",
                secondary_action_href=f"/app/actions/queue/{value.id}/resolve" if value.id.startswith(("commitment:", "follow_up:")) else "",
                secondary_action_label="Drop" if value.id.startswith(("commitment:", "follow_up:")) else "",
                secondary_action_value="drop" if value.id.startswith(("commitment:", "follow_up:")) else "",
                secondary_action_method="post" if value.id.startswith(("commitment:", "follow_up:")) else "",
                secondary_return_to="/app/briefing" if value.id.startswith(("commitment:", "follow_up:")) else "",
            )
        )
    return rows


def _decision_rows(values: tuple[DecisionItem, ...], *, return_to: str) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for value in values:
        detail = " · ".join(
            part
            for part in (
                value.decision_type.replace("_", " ").title() if value.decision_type else "",
                f"Recommend {value.recommendation}" if value.recommendation else "",
                f"Due {value.due_at[:10]}" if value.due_at else "",
                value.next_action or value.rationale or value.summary,
            )
            if part
        )
        rows.append(
            _row(
                value.title,
                detail or "Decision remains open.",
                value.priority.capitalize(),
                href=f"/app/decisions/{value.id}",
                action_href=f"/app/actions/queue/{value.id}/resolve",
                action_label="Resolve",
                action_value="resolve",
                return_to=return_to,
            )
        )
    return rows


def _commitment_rows(values: tuple[CommitmentItem, ...], *, return_to: str = "/app/inbox") -> list[dict[str, str]]:
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
        rows.append(
            _row(
                value.statement,
                detail or "Commitment is still open.",
                value.risk_level.capitalize(),
                href=f"/app/commitment-items/{value.id}",
                action_href=f"/app/actions/queue/{value.id}/resolve",
                action_label="Close",
                action_value="close",
                return_to=return_to,
                secondary_action_href=f"/app/actions/queue/{value.id}/resolve",
                secondary_action_label="Drop",
                secondary_action_value="drop",
                secondary_action_method="post",
                secondary_return_to=return_to,
            )
        )
    return rows


def _candidate_rows(values: tuple[CommitmentCandidate, ...]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for value in values:
        detail = " · ".join(
            part
            for part in (
                value.counterparty,
                f"Due {value.suggested_due_at[:10]}" if value.suggested_due_at else "",
                value.details[:96] if value.details else "",
            )
            if part
        )
        rows.append(
            _row(
                value.title,
                detail or "Review this extracted commitment before it becomes part of the ledger.",
                "Candidate",
                href=f"/app/commitments/candidates/{value.candidate_id}",
                action_href=f"/app/actions/commitments/candidates/{value.candidate_id}/accept",
                action_label="Accept",
                return_to="/app/inbox",
                secondary_action_href=f"/app/actions/commitments/candidates/{value.candidate_id}/reject",
                secondary_action_label="Reject",
                secondary_action_method="post",
                secondary_return_to="/app/inbox",
            )
        )
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
        rows.append(
            _row(
                value.recipient_summary or value.intent.title(),
                detail or "Draft awaiting review.",
                "Draft",
                action_href=f"/app/actions/drafts/{value.id}/approve",
                action_label="Approve",
                return_to="/app/inbox",
                secondary_action_href=f"/app/actions/drafts/{value.id}/reject",
                secondary_action_label="Reject",
                secondary_action_method="post",
                secondary_return_to="/app/inbox",
            )
        )
    return rows


def _thread_rows(values: tuple[ThreadItem, ...]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for value in values:
        detail = " · ".join(
            part
            for part in (
                ", ".join(value.counterparties[:2]) if value.counterparties else "",
                value.channel,
                value.status,
                value.summary[:96] if value.summary else "",
            )
            if part
        )
        rows.append(_row(value.title, detail or "Thread is active in the office loop.", value.channel.title(), href=f"/app/threads/{value.id}"))
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


def _handoff_rows(values: tuple[HandoffNote, ...], *, actionable: bool = True, return_to: str = "/app/follow-ups") -> list[dict[str, str]]:
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
        rows.append(
            _row(
                value.summary,
                detail or "Handoff remains open.",
                value.escalation_status.capitalize(),
                href=f"/app/handoffs/{value.id}",
                action_href=f"/app/actions/handoffs/{value.id}/assign" if actionable else "",
                action_label="Claim" if actionable else "",
                action_value="assign" if actionable else "",
                return_to=return_to if actionable else "",
                secondary_action_href=f"/app/actions/handoffs/{value.id}/complete" if actionable else "",
                secondary_action_label="Complete" if actionable else "",
                secondary_action_value="completed" if actionable else "",
                secondary_return_to=return_to if actionable else "",
            )
        )
    return rows


def _evidence_rows(values: tuple[EvidenceItem, ...]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for value in values:
        detail = " · ".join(
            part
            for part in (
                value.summary,
                ", ".join(value.related_object_refs[:2]) if value.related_object_refs else "",
            )
            if part
        )
        rows.append(_row(value.label, detail or "Evidence supports the current office state.", value.source_type.replace("_", " ").title(), href=f"/app/evidence/{value.id}"))
    return rows


def _rule_rows(values: tuple[RuleItem, ...]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for value in values:
        detail = " · ".join(
            part
            for part in (
                value.current_value,
                value.impact,
                value.simulated_effect,
            )
            if part
        )
        rows.append(_row(value.label, detail or value.summary, value.scope.replace("_", " ").title(), href=f"/app/rules/{value.id}"))
    return rows


def _diagnostic_rows(diagnostics: dict[str, object], *, return_to: str) -> list[dict[str, str]]:
    workspace = dict(diagnostics.get("workspace") or {})
    plan = dict(diagnostics.get("plan") or {})
    billing = dict(diagnostics.get("billing") or {})
    commercial = dict(diagnostics.get("commercial") or {})
    entitlements = dict(diagnostics.get("entitlements") or {})
    operators = dict(diagnostics.get("operators") or {})
    readiness = dict(diagnostics.get("readiness") or {})
    providers = dict(diagnostics.get("providers") or {})
    queue_health = dict(diagnostics.get("queue_health") or {})
    analytics = dict(diagnostics.get("analytics") or {})
    analytics_counts = dict(analytics.get("counts") or {})
    analytics_delivery = dict(analytics.get("delivery") or {})
    analytics_sync = dict(analytics.get("sync") or {})
    selected_channels = [str(value) for value in (diagnostics.get("selected_channels") or []) if str(value).strip()]
    feature_flags = [str(value).replace("_", " ") for value in (entitlements.get("feature_flags") or []) if str(value).strip()]
    return [
        _row("Workspace mode", str(workspace.get("mode") or "personal").replace("_", " ").title(), "Workspace", href="/app/settings/plan"),
        _row("Workspace plan", str(plan.get("display_name") or "Pilot"), "Plan", href="/app/settings/plan"),
        _row("Plan unit", str(plan.get("unit_of_sale") or "workspace"), "Plan", href="/app/settings/plan"),
        _row("Billing state", str(billing.get("billing_state") or "unknown"), "Billing", href="/app/settings/plan"),
        _row("Support tier", str(billing.get("support_tier") or "standard"), "Support", href="/app/settings/support"),
        _row("Renewal owner", str(billing.get("renewal_owner_role") or "principal").replace("_", " ").title(), "Billing", href="/app/settings/support"),
        _row("Contract note", str(billing.get("contract_note") or "Contract posture not set."), "Contract", href="/app/settings/plan"),
        _row("Channels", ", ".join(selected_channels) if selected_channels else "Google-first path", "Channels", href="/app/settings/plan"),
        _row("Operator seats", str(entitlements.get("operator_seats") or 0), "Entitlement", href="/app/settings/plan"),
        _row("Seats used", str(operators.get("seats_used") or 0), "Entitlement", href="/app/settings/usage"),
        _row("Seats remaining", str(operators.get("seats_remaining") or 0), "Entitlement", href="/app/settings/usage"),
        _row("Workspace health score", str(readiness.get("health_score") or 0), "Runtime", href="/app/settings/support"),
        _row("Provider risk", str(providers.get("risk_state") or "unknown").replace("_", " "), "Support", href="/app/settings/support"),
        _row("Fallback lanes", str(providers.get("lanes_with_fallback") or 0), "Support", href="/app/settings/support"),
        _row("Load score", str(queue_health.get("load_score") or 0), "Queue", href="/app/activity"),
        _row(
            "Messaging scope",
            "Included in this plan" if entitlements.get("messaging_channels_enabled") else "Upgrade required for Telegram and WhatsApp",
            "Entitlement",
            href="/app/settings/plan",
        ),
        _row("Audit retention", str(entitlements.get("audit_retention") or "standard"), "Entitlement", href="/app/settings/support"),
        _row("Enabled product loops", ", ".join(feature_flags) if feature_flags else "No feature flags enabled", "Entitlement", href="/app/settings/plan"),
        _row("Memos opened", str(analytics_counts.get("memo_opened") or 0), "Analytics", href="/app/settings/usage"),
        _row("Drafts approved", str(analytics_counts.get("draft_approved") or 0), "Analytics", href="/app/settings/usage"),
        _row("Commitments closed", str(analytics_counts.get("commitment_closed") or 0), "Analytics", href="/app/settings/usage"),
        _row("First value event", str(analytics.get("first_value_event") or "not reached").replace("_", " "), "Analytics", href="/app/settings/usage"),
        _row("Time to first value", str(analytics.get("time_to_first_value_seconds") or "pending"), "Analytics", href="/app/settings/usage"),
        _row(
            "Upgrade required for",
            ", ".join(str(value).replace("_", " ") for value in (commercial.get("blocked_actions") or [])[:4]) or "No blocked actions",
            "Support",
            href="/app/settings/support",
        ),
        _row(
            "Commercial warnings",
            "; ".join(str(value) for value in (commercial.get("warnings") or []) if str(value).strip()) or "No commercial warnings",
            "Support",
            href="/app/settings/support",
        ),
        _row(
            "Workspace diagnostics bundle",
            str(readiness.get("detail") or "Export support-ready workspace bundle"),
            "Bundle",
            href="/app/settings/support",
            action_href="/app/api/diagnostics/export",
            action_label="Open bundle",
            action_method="get",
            return_to=return_to,
        ),
    ]


def workspace_section_payload(
    section: str,
    snapshot: ProductSnapshot,
    diagnostics: dict[str, object] | None = None,
    *,
    operator_id: str = "",
) -> dict[str, object]:
    diagnostics = diagnostics or {}
    operator_key = str(operator_id or "").strip()
    queue_health = dict(diagnostics.get("queue_health") or {})
    provider_posture = dict(diagnostics.get("providers") or {})
    commercial = dict(diagnostics.get("commercial") or {})
    readiness = dict(diagnostics.get("readiness") or {})
    analytics = dict(diagnostics.get("analytics") or {})
    analytics_delivery = dict(analytics.get("delivery") or {})
    analytics_access = dict(analytics.get("access") or {})
    analytics_sync = dict(analytics.get("sync") or {})
    assignment_suggestions = [dict(value) for value in (queue_health.get("assignment_suggestions") or [])]
    assigned_handoffs = tuple(row for row in snapshot.handoffs if operator_key and row.owner == operator_key)
    unclaimed_handoffs = tuple(row for row in snapshot.handoffs if not operator_key or row.owner != operator_key)
    clearable_queue_items = tuple(row for row in snapshot.queue_items if not bool(row.requires_principal))
    suggested_handoff_ids = {
        str(item.get("id") or "").strip()
        for item in assignment_suggestions
        if str(item.get("id") or "").strip()
    }
    remaining_unclaimed_handoffs = tuple(row for row in unclaimed_handoffs if row.id not in suggested_handoff_ids)
    blocked_actions = [str(value).replace("_", " ") for value in list(commercial.get("blocked_actions") or []) if str(value).strip()]
    warning_messages = [str(value) for value in list(commercial.get("warnings") or []) if str(value).strip()]
    delivery_failure_total = (
        int(analytics_delivery.get("registration_failed") or 0)
        + int(analytics_delivery.get("invite_failed") or 0)
        + int(analytics_delivery.get("digest_failed") or 0)
    )
    exception_rows = [
        _row(
            "Delivery failures",
            (
                f"{int(queue_health.get('delivery_errors') or 0)} queue delivery errors · "
                f"{delivery_failure_total} email failures"
            ),
            "Support",
            href="/app/settings/support",
        )
        for _ in [0]
        if int(queue_health.get("delivery_errors") or 0) or delivery_failure_total
    ] + [
        _row(
            "SLA breaches",
            f"{int(queue_health.get('sla_breaches') or 0)} handoffs already breached their SLA.",
            "Queue",
            href="/app/activity",
        )
        for _ in [0]
        if int(queue_health.get("sla_breaches") or 0)
    ] + [
        _row(
            "Blocked actions",
            ", ".join(blocked_actions[:4]),
            "Plan",
            href="/app/settings/support",
        )
        for _ in [0]
        if blocked_actions
    ] + [
        _row(
            "Commercial warnings",
            "; ".join(warning_messages[:2]),
            "Support",
            href="/app/settings/support",
        )
        for _ in [0]
        if warning_messages
    ] + [
        _row(
            "Provider risk",
            str(provider_posture.get("risk_state") or "unknown").replace("_", " ").title(),
            "Provider",
            href="/app/settings/support",
        )
        for _ in [0]
        if str(provider_posture.get("risk_state") or "").strip().lower() in {"degraded", "critical", "failed"}
    ]
    stats = [
        {"label": "Memo items", "value": str(snapshot.stats_json.get("brief_items", 0))},
        {"label": "Queue items", "value": str(snapshot.stats_json.get("queue_items", 0))},
        {"label": "Commitments", "value": str(snapshot.stats_json.get("commitments", 0))},
        {"label": "Decisions", "value": str(snapshot.stats_json.get("decisions", 0))},
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
                    "eyebrow": "Blocked decisions",
                    "title": "What needs an explicit call",
                    "body": "Decisions are first-class product objects, not just queue summaries.",
                    "items": _decision_rows(snapshot.decisions[:6], return_to="/app/today"),
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
                    "body": "Each decision now carries ownership, timing, rationale, and an explicit next move.",
                    "items": _decision_rows(snapshot.decisions[:8], return_to="/app/briefing"),
                },
                {
                    "eyebrow": "Related queue",
                    "title": "What still needs queue handling",
                    "body": "Approvals, assignments, and deadlines still sit beside explicit decision objects.",
                    "items": _queue_rows(snapshot.queue_items[:6]),
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
                    "eyebrow": "Conversation threads",
                    "title": "What live conversations are shaping the queue",
                    "body": "Threads are now a first-class product object tied to drafts, commitments, and decisions.",
                    "items": _thread_rows(snapshot.threads[:6]),
                },
                {
                    "eyebrow": "Pending captures",
                    "title": "What still needs commitment review",
                    "body": "Extracted commitments stay reviewable before they enter the live ledger.",
                    "items": _candidate_rows(snapshot.commitment_candidates[:6]),
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
                    "items": _handoff_rows(snapshot.handoffs[:8], return_to="/app/follow-ups"),
                },
                {
                    "eyebrow": "Still open",
                    "title": "What handoffs are protecting",
                    "body": "Handoffs exist because commitments or approvals still need movement.",
                    "items": _commitment_rows(snapshot.commitments[:6], return_to="/app/follow-ups"),
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
                    "body": "Evidence is now a first-class product object instead of buried inside row notes.",
                    "items": _evidence_rows(snapshot.evidence[:8]),
                },
                {
                    "eyebrow": "Conversation threads",
                    "title": "Which threads produced the current pressure",
                    "body": "Evidence matters most when it stays connected to active conversations and commitments.",
                    "items": _thread_rows(snapshot.threads[:8]),
                },
                {
                    "eyebrow": "Relationship context",
                    "title": "Who the evidence touches",
                    "body": "Evidence is useful when it stays connected to the right people and commitments.",
                    "items": _people_rows(snapshot.people[:6]),
                },
            ],
        },
        "activity": {
            "title": "Operator Queue",
            "summary": "Assignments, follow-up handoffs, and principal waiting items stay visible as a real operating lane.",
            "cards": [
                {
                    "eyebrow": "Queue health",
                    "title": "Queue health",
                    "body": "SLA breaches, unclaimed work, approvals, and delivery backlog should stay visible in one operational view.",
                    "items": [
                        _row("Queue state", str(queue_health.get("state") or "healthy").title(), str(queue_health.get("state") or "healthy").title()),
                        _row("SLA breaches", str(queue_health.get("sla_breaches") or 0), "Queue"),
                        _row("Unclaimed handoffs", str(queue_health.get("unclaimed_handoffs") or 0), "Queue"),
                        _row("Pending approvals", str(queue_health.get("pending_approvals") or 0), "Queue"),
                        _row("Waiting on principal", str(queue_health.get("waiting_on_principal") or 0), "Queue"),
                        _row("Queued delivery", str(queue_health.get("pending_delivery") or 0), "Queue"),
                        _row("Retrying delivery", str(queue_health.get("retrying_delivery") or 0), "Queue"),
                        _row("Delivery errors", str(queue_health.get("delivery_errors") or 0), "Queue"),
                        _row("Load score", str(queue_health.get("load_score") or 0), "Queue"),
                        _row("Oldest handoff age", f"{queue_health.get('oldest_handoff_age_hours') or 0}h", "Queue"),
                        _row("Oldest queued delivery age", f"{queue_health.get('oldest_pending_delivery_age_hours') or 0}h", "Queue"),
                    ],
                },
                {
                    "eyebrow": "Provider posture",
                    "title": "Provider posture",
                    "body": "The operator lane is only trustworthy when provider risk, fallback coverage, and workspace health stay visible.",
                    "items": [
                        _row("Provider risk", str(provider_posture.get("risk_state") or "unknown").replace("_", " ").title(), "Provider"),
                        _row("Ready providers", str(provider_posture.get("ready_count") or 0), "Provider"),
                        _row("Degraded providers", str(provider_posture.get("degraded_count") or 0), "Provider"),
                        _row("Failed providers", str(provider_posture.get("failed_count") or 0), "Provider"),
                        _row("Fallback lanes", str(provider_posture.get("lanes_with_fallback") or 0), "Provider"),
                        _row("Failover-ready lanes", str(provider_posture.get("failover_ready_lanes") or 0), "Provider"),
                        _row("Workspace health score", str(readiness.get("health_score") or 0), "Runtime"),
                        _row("Google account", str(analytics_sync.get("google_account_email") or "Not connected"), "Sync", href="/app/settings/usage"),
                        _row("Google token status", str(analytics_sync.get("google_token_status") or "missing").replace("_", " ").title(), "Sync", href="/app/settings/usage"),
                        _row("Google sync runs", str(analytics_sync.get("google_sync_completed") or 0), "Sync", href="/app/settings/usage"),
                        _row("Last Google sync", str(analytics_sync.get("google_sync_last_completed_at") or "Not yet run"), "Sync", href="/app/settings/usage"),
                        _row("Office signals ingested", str(analytics_sync.get("office_signal_ingested") or 0), "Sync", href="/app/settings/usage"),
                        _row("Pending sync candidates", str(analytics_sync.get("pending_commitment_candidates") or 0), "Sync", href="/app/inbox"),
                    ],
                },
                {
                    "eyebrow": "Delivery and access",
                    "title": "Registration, invite, and digest delivery",
                    "body": "The operator lane should surface whether people can actually enter the workspace and receive the compact loop.",
                    "items": [
                        _row("Registration emails sent", str(analytics_delivery.get("registration_sent") or 0), "Email", href="/app/settings/usage"),
                        _row("Registration email failures", str(analytics_delivery.get("registration_failed") or 0), "Email", href="/app/settings/support"),
                        _row("Invite emails sent", str(analytics_delivery.get("invite_sent") or 0), "Email", href="/app/settings/support"),
                        _row("Invite email failures", str(analytics_delivery.get("invite_failed") or 0), "Email", href="/app/settings/support"),
                        _row("Digest emails sent", str(analytics_delivery.get("digest_sent") or 0), "Email", href="/app/channel-loop"),
                        _row("Digest email failures", str(analytics_delivery.get("digest_failed") or 0), "Email", href="/app/settings/support"),
                        _row("Active access sessions", str(analytics_access.get("active") or 0), "Access", href="/app/settings/support"),
                        _row("Access links opened", str(analytics_access.get("opened") or 0), "Access", href="/app/settings/support"),
                        _row("Access sessions revoked", str(analytics_access.get("revoked") or 0), "Access", href="/app/settings/support"),
                    ],
                },
                {
                    "eyebrow": "Suggested next claims",
                    "title": "Suggested next claims",
                    "body": "Claim suggestions rank unclaimed work before it ages into a visible office miss.",
                    "items": [
                        _row(
                            str(item.get("summary") or item.get("id") or "Suggested claim"),
                            " · ".join(
                                part
                                for part in (
                                    str(item.get("owner") or "").strip() or "Unclaimed",
                                    f"Due {str(item.get('due_time') or '')[:10]}" if str(item.get("due_time") or "").strip() else "",
                                    str(item.get("escalation_status") or "").replace("_", " ").title(),
                                )
                                if part
                            )
                            or "Claim this handoff before it misses the office loop.",
                            "Suggestion",
                            href=f"/app/handoffs/{str(item.get('id') or '')}" if str(item.get("id") or "").strip() else "",
                            action_href=f"/app/actions/handoffs/{str(item.get('id') or '')}/assign" if str(item.get("id") or "").strip() else "",
                            action_label="Claim" if str(item.get("id") or "").strip() else "",
                            action_value="assign" if str(item.get("id") or "").strip() else "",
                            return_to="/app/activity" if str(item.get("id") or "").strip() else "",
                        )
                        for item in assignment_suggestions[:3]
                    ]
                    or [_row("No claim suggestions", "The unclaimed operator lane is currently clear.", "Clear")],
                },
                {
                    "eyebrow": "Pre-clear",
                    "title": "Clear before principal",
                    "body": "These queue items can be closed, resolved, or approved inside the operator lane before they become principal noise.",
                    "items": _queue_rows(clearable_queue_items[:8])
                    or [_row("Nothing to pre-clear", "The remaining queue currently depends on the principal.", "Clear")],
                },
                {
                    "eyebrow": "Assigned to me",
                    "title": "What already belongs to this operator lane",
                    "body": "Assigned work should stay separate from the claimable backlog.",
                    "items": _handoff_rows(assigned_handoffs[:8], return_to="/app/activity"),
                },
                {
                    "eyebrow": "Unclaimed handoffs",
                    "title": "What can be claimed next",
                    "body": "Operator work should be explicit, claimable, and closable from the same queue.",
                    "items": _handoff_rows(remaining_unclaimed_handoffs[:8], return_to="/app/activity")
                    or [_row("No unclaimed handoffs", "Suggested claims already cover the current claimable backlog.", "Clear")],
                },
                {
                    "eyebrow": "Waiting on principal",
                    "title": "What still needs executive clearance",
                    "body": "Approval-backed drafts and decision windows should not disappear into admin surfaces.",
                    "items": _queue_rows(tuple(row for row in snapshot.queue_items if row.requires_principal)[:8]),
                },
                {
                    "eyebrow": "Exceptions",
                    "title": "Exception queue",
                    "body": "Failures, breaches, provider risk, and plan blockers belong in one exception lane instead of leaking into normal work.",
                    "items": exception_rows
                    or [_row("No active exceptions", "The operator lane is clear of delivery, SLA, provider, and commercial exceptions.", "Clear")],
                },
                {
                    "eyebrow": "Recently completed",
                    "title": "What just moved through the operator lane",
                    "body": "Returned handoffs should stay visible long enough to confirm the office loop actually closed.",
                    "items": _handoff_rows(snapshot.completed_handoffs[:6], actionable=False),
                },
                {
                    "eyebrow": "Commitment pressure",
                    "title": "What operator work is protecting",
                    "body": "Operator tasks are only useful when they keep the right commitments from slipping.",
                    "items": _commitment_rows(snapshot.commitments[:8], return_to="/app/activity"),
                },
                {
                    "eyebrow": "Affected stakeholders",
                    "title": "Who is attached to the operator queue",
                    "body": "The operator lane should stay tied to the people and relationships it serves.",
                    "items": _people_rows(snapshot.people[:6]),
                },
                {
                    "eyebrow": "Commercial pressure",
                    "title": "What the plan boundary is blocking",
                    "body": "Operator work gets noisy when seat limits, messaging scope, or support posture are out of sync with the office loop.",
                    "items": [
                        _row("Recommended plan", str(commercial.get("recommended_plan_label") or "Current plan"), "Plan", href="/app/settings/plan"),
                        _row(
                            "Blocked actions",
                            ", ".join(str(value).replace("_", " ") for value in (commercial.get("blocked_actions") or [])[:6]) or "No blocked actions",
                            "Support",
                            href="/app/settings/support",
                        ),
                        _row(
                            "Warnings",
                            "; ".join(str(value) for value in (commercial.get("warnings") or []) if str(value).strip()) or "No current warnings",
                            "Support",
                            href="/app/settings/support",
                        ),
                    ],
                },
            ],
        },
        "settings": {
            "title": "Rules",
            "summary": "Channel permissions, commercial boundaries, and support posture belong in one understandable control surface.",
            "cards": [
                {
                    "eyebrow": "Workspace rules",
                    "title": "Current plan, channels, and contract posture",
                    "body": "Rules are now modeled as first-class product objects with visible commercial and operational impact.",
                    "items": _rule_rows(snapshot.rules[:7])
                    + [
                        _row(
                            "Workspace diagnostics bundle",
                            str(dict(diagnostics.get("readiness") or {}).get("detail") or "Export support-ready workspace bundle"),
                            "Bundle",
                            href="/app/settings/support",
                            action_href="/app/api/diagnostics/export",
                            action_label="Open bundle",
                            action_method="get",
                            return_to="/app/settings",
                        )
                    ],
                },
                {
                    "eyebrow": "Queue and memo health",
                    "title": "What this ruleset is currently supporting",
                    "body": "Usage and queue pressure should stay attached to the commercial and support posture.",
                    "items": [
                        _row("Memo items", str(snapshot.stats_json.get("brief_items", 0)), "Usage"),
                        _row("Queue items", str(snapshot.stats_json.get("queue_items", 0)), "Usage"),
                        _row("Commitments", str(snapshot.stats_json.get("commitments", 0)), "Usage"),
                        _row("Handoffs", str(snapshot.stats_json.get("handoffs", 0)), "Usage"),
                        _row("Load score", str(queue_health.get("load_score") or 0), "Queue", href="/app/activity"),
                        _row("Retrying delivery", str(queue_health.get("retrying_delivery") or 0), "Queue", href="/app/settings/support"),
                        _row("Delivery errors", str(queue_health.get("delivery_errors") or 0), "Queue", href="/app/settings/support"),
                        _row("Active operators", str(dict(diagnostics.get("operators") or {}).get("active_count") or 0), "Usage", href="/app/settings/usage"),
                        _row("Memos opened", str(dict(dict(diagnostics.get("analytics") or {}).get("counts") or {}).get("memo_opened") or 0), "Analytics", href="/app/settings/usage"),
                        _row("Time to first value", str(dict(diagnostics.get("analytics") or {}).get("time_to_first_value_seconds") or "pending"), "Analytics", href="/app/settings/usage"),
                        _row("Google sync freshness", str(analytics_sync.get("google_sync_freshness_state") or "watch").replace("_", " ").title(), "Sync", href="/app/settings/usage"),
                        _row("Pending sync candidates", str(analytics_sync.get("pending_commitment_candidates") or 0), "Sync", href="/app/inbox"),
                        _row("Workspace health score", str(readiness.get("health_score") or 0), "Runtime", href="/app/settings/support"),
                    ],
                },
                {
                    "eyebrow": "Reviewable work",
                    "title": "What the current rules are gating",
                    "body": "Rules are useful when they explain what still needs approval, assignment, or follow-up.",
                    "items": _queue_rows(snapshot.queue_items[:8]),
                },
                {
                    "eyebrow": "Plan boundary",
                    "title": "What this workspace actually includes",
                    "body": "The commercial boundary should be visible where channel scope, support posture, and escalation rules are chosen.",
                    "items": [
                        _row("Workspace plan", str(dict(diagnostics.get("plan") or {}).get("display_name") or "Pilot"), "Plan", href="/app/settings/plan"),
                        _row("Plan unit", str(dict(diagnostics.get("plan") or {}).get("unit_of_sale") or "workspace"), "Plan", href="/app/settings/plan"),
                        _row("Support tier", str(dict(diagnostics.get("billing") or {}).get("support_tier") or "standard"), "Support", href="/app/settings/support"),
                        _row("Billing state", str(dict(diagnostics.get("billing") or {}).get("billing_state") or "unknown"), "Billing", href="/app/settings/plan"),
                        _row(
                            "Channels",
                            ", ".join(str(value) for value in (diagnostics.get("selected_channels") or []) if str(value).strip()) or "Google-first path",
                            "Channels",
                            href="/app/settings/plan",
                        ),
                        _row(
                            "Messaging scope",
                            "Included" if dict(diagnostics.get("entitlements") or {}).get("messaging_channels_enabled") else "Not included on this plan",
                            "Entitlement",
                            href="/app/settings/plan",
                        ),
                        _row(
                            "Feature flags",
                            ", ".join(str(value).replace("_", " ") for value in (dict(diagnostics.get("entitlements") or {}).get("feature_flags") or [])[:6]) or "No enabled features",
                            "Entitlement",
                            href="/app/settings/plan",
                        ),
                        _row("Provider risk", str(provider_posture.get("risk_state") or "unknown"), "Support", href="/app/settings/support"),
                        _row("Fallback lanes", str(provider_posture.get("lanes_with_fallback") or 0), "Support", href="/app/settings/support"),
                        _row("Recommended plan", str(commercial.get("recommended_plan_label") or "Current plan"), "Plan", href="/app/settings/plan"),
                        _row(
                            "Blocked actions",
                            ", ".join(str(value).replace("_", " ") for value in (commercial.get("blocked_actions") or [])[:6]) or "No blocked actions",
                            "Support",
                            href="/app/settings/support",
                        ),
                        _row(
                            "Warnings",
                            "; ".join(str(value) for value in (dict(diagnostics.get("commercial") or {}).get("warnings") or []) if str(value).strip()) or "No current warnings",
                            "Support",
                            href="/app/settings/support",
                        ),
                    ],
                },
            ],
        },
    }
    return {"stats": stats, **mapping[section]}
