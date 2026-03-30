from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.product.models import BriefItem, CommitmentCandidate, CommitmentItem, DecisionItem, DecisionQueueItem, DraftCandidate, EvidenceItem, HandoffNote, PersonProfile, ProductSnapshot, RuleItem, ThreadItem
from app.product.projections.common import due_bonus, parse_when, priority_weight, status_open
from app.product.projections.handoffs import handoff_action_options, handoff_action_plan


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
    tertiary_action_href: str = "",
    tertiary_action_label: str = "",
    tertiary_action_value: str = "",
    tertiary_action_method: str = "",
    tertiary_return_to: str = "",
    quaternary_action_href: str = "",
    quaternary_action_label: str = "",
    quaternary_action_value: str = "",
    quaternary_action_method: str = "",
    quaternary_return_to: str = "",
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
    if tertiary_action_href:
        row["tertiary_action_href"] = tertiary_action_href
    if tertiary_action_label:
        row["tertiary_action_label"] = tertiary_action_label
    if tertiary_action_value:
        row["tertiary_action_value"] = tertiary_action_value
    if tertiary_action_method:
        row["tertiary_action_method"] = tertiary_action_method
    if tertiary_return_to:
        row["tertiary_return_to"] = tertiary_return_to
    if quaternary_action_href:
        row["quaternary_action_href"] = quaternary_action_href
    if quaternary_action_label:
        row["quaternary_action_label"] = quaternary_action_label
    if quaternary_action_value:
        row["quaternary_action_value"] = quaternary_action_value
    if quaternary_action_method:
        row["quaternary_action_method"] = quaternary_action_method
    if quaternary_return_to:
        row["quaternary_return_to"] = quaternary_return_to
    return row


def _google_settings_action_row(sync: dict[str, object], *, return_to: str) -> dict[str, str]:
    connected = bool(sync.get("google_connected"))
    token_status = str(sync.get("google_token_status") or "missing").strip()
    freshness = str(sync.get("google_sync_freshness_state") or "watch").strip()
    if not connected:
        return _row(
            "Connected",
            "No",
            "Sync",
            href="/app/settings/google",
            action_href=f"/app/actions/google/connect?return_to={return_to}",
            action_label="Connect now",
            action_method="get",
        )
    if token_status not in {"active", "unknown"}:
        return _row(
            "Connected",
            "Yes",
            "Sync",
            href="/app/settings/google",
            action_href=f"/app/actions/google/connect?return_to={return_to}",
            action_label="Reconnect now",
            action_method="get",
        )
    if freshness != "clear":
        return _row(
            "Connected",
            "Yes",
            "Sync",
            href="/app/settings/google",
            action_href=f"/app/actions/signals/google/sync?return_to={return_to}",
            action_label="Run now",
            action_method="get",
        )
    return _row("Connected", "Yes", "Sync", href="/app/settings/google")


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _sorted_open_commitments(values: tuple[CommitmentItem, ...]) -> tuple[CommitmentItem, ...]:
    rows = [value for value in values if status_open(value.status)]
    rows.sort(
        key=lambda value: (
            due_bonus(value.due_at),
            priority_weight(value.risk_level),
            str(value.last_activity_at or ""),
            value.statement.lower(),
        ),
        reverse=True,
    )
    return tuple(rows)


def _commitments_due_now(values: tuple[CommitmentItem, ...]) -> tuple[CommitmentItem, ...]:
    rows = [value for value in _sorted_open_commitments(values) if due_bonus(value.due_at) >= 28]
    return tuple(rows)


def _stale_commitments(values: tuple[CommitmentItem, ...]) -> tuple[CommitmentItem, ...]:
    now = _now_utc()
    rows: list[CommitmentItem] = []
    for value in _sorted_open_commitments(values):
        due_at = parse_when(value.due_at)
        last_activity_at = parse_when(value.last_activity_at)
        overdue = due_at is not None and due_at <= now
        stale_activity = last_activity_at is None or (now - last_activity_at) >= timedelta(days=2)
        if overdue or stale_activity:
            rows.append(value)
    return tuple(rows)


def _commitments_by_status(values: tuple[CommitmentItem, ...], *statuses: str) -> tuple[CommitmentItem, ...]:
    wanted = {str(value).strip().lower() for value in statuses if str(value).strip()}
    return tuple(value for value in _sorted_open_commitments(values) if str(value.status or "").strip().lower() in wanted)


def _sorted_people(values: tuple[PersonProfile, ...]) -> tuple[PersonProfile, ...]:
    rows = list(values)
    rows.sort(
        key=lambda value: (
            value.open_loops_count,
            value.importance_score,
            str(value.latest_touchpoint_at or ""),
            value.display_name.lower(),
        ),
        reverse=True,
    )
    return tuple(rows)


def _draft_queue_rows(values: tuple[DraftCandidate, ...]) -> list[dict[str, str]]:
    return _draft_rows(values) or [_row("No drafts ready", "The review queue is currently clear.", "Clear")]


def _calendar_pressure_rows(values: tuple[DecisionQueueItem, ...]) -> list[dict[str, str]]:
    rows = [
        value
        for value in values
        if str(value.id or "").startswith(("decision:", "deadline:")) or due_bonus(value.deadline) >= 18
    ]
    rows.sort(
        key=lambda value: (
            due_bonus(value.deadline),
            priority_weight(value.priority),
            value.title.lower(),
        ),
        reverse=True,
    )
    return _queue_rows(tuple(rows[:8])) or [_row("No calendar pressure", "No near-term decision or deadline windows are open.", "Clear")]


def _suggested_sequence_rows(
    *,
    decisions: tuple[DecisionItem, ...],
    drafts: tuple[DraftCandidate, ...],
    commitments: tuple[CommitmentItem, ...],
    people: tuple[PersonProfile, ...],
) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    if decisions:
        decision = decisions[0]
        rows.append(
            _row(
                decision.title,
                decision.next_action or decision.impact_summary or decision.summary,
                "Decision",
                href=f"/app/decisions/{decision.id}",
                action_href=f"/app/actions/queue/{decision.id}/resolve",
                action_label="Resolve",
                action_value="resolve",
                return_to="/app/briefing",
            )
        )
    if drafts:
        draft = drafts[0]
        thread_ref = str(draft.thread_ref or draft.id).strip() or draft.id
        thread_id = thread_ref if thread_ref.startswith("thread:") else f"thread:{thread_ref}"
        rows.append(
            _row(
                draft.recipient_summary or "Next reply",
                "Open the draft with its thread context before the queue fragments.",
                "Draft",
                href=f"/app/threads/{thread_id}",
                action_href=f"/app/actions/drafts/{draft.id}/approve",
                action_label="Approve",
                return_to="/app/briefing",
                secondary_action_href=f"/app/threads/{thread_id}",
                secondary_action_label="Open thread",
                secondary_action_method="get",
            )
        )
    if commitments:
        commitment = commitments[0]
        rows.append(
            _row(
                commitment.statement,
                " · ".join(
                    part
                    for part in (
                        commitment.counterparty,
                        f"Due {commitment.due_at[:10]}" if commitment.due_at else "",
                        commitment.risk_level.replace("_", " ").title(),
                    )
                    if part
                )
                or "Protect this commitment before it slips.",
                "Commitment",
                href=f"/app/commitment-items/{commitment.id}",
                action_href=f"/app/actions/queue/{commitment.id}/resolve",
                action_label="Defer" if due_bonus(commitment.due_at) >= 28 else "Close",
                action_value="defer" if due_bonus(commitment.due_at) >= 28 else "close",
                return_to="/app/briefing",
            )
        )
    if people:
        person = people[0]
        rows.append(
            _row(
                person.display_name,
                "Correct or confirm relationship context before the next outbound move.",
                "People",
                href=f"/app/people/{person.id}",
            )
        )
    return rows or [_row("No suggested sequence", "The workspace currently has no ranked sequence to clear.", "Clear")]


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
        href = ""
        if value.id.startswith("approval:"):
            action_href = f"/app/actions/drafts/{value.id}/approve"
            action_label = "Approve"
        elif value.id.startswith(("commitment:", "follow_up:")):
            href = f"/app/commitment-items/{value.id}"
            action_href = f"/app/actions/queue/{value.id}/resolve"
            action_label = "Close"
            action_value = "close"
        elif value.id.startswith("decision:"):
            href = f"/app/decisions/{value.id}"
            action_href = f"/app/actions/queue/{value.id}/resolve"
            action_label = "Resolve"
            action_value = "resolve"
        elif value.id.startswith("deadline:"):
            href = f"/app/deadlines/{value.id}"
            action_href = f"/app/actions/queue/{value.id}/resolve"
            action_label = "Resolve"
            action_value = "resolve"
        elif value.id.startswith("human_task:"):
            href = f"/app/handoffs/{value.id}"
        rows.append(
            _row(
                value.title,
                f"{value.summary}{due}".strip(),
                value.priority.capitalize(),
                href=href,
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
                secondary_action_href=f"/app/decisions/{value.id}",
                secondary_action_label="Review",
                secondary_action_method="get",
            )
        )
    return rows


def _commitment_rows(values: tuple[CommitmentItem, ...], *, return_to: str = "/app/inbox") -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for value in values:
        status_label = str(value.status or "open").strip().replace("_", " ").title()
        normalized_status = str(value.status or "").strip().lower()
        detail = " · ".join(
            part
            for part in (
                status_label if status_label.lower() not in {"open", "completed"} else "",
                value.counterparty,
                f"Due {value.due_at[:10]}" if value.due_at else "",
                value.proof_refs[0].note if value.proof_refs else "",
            )
            if part
        )
        is_resolved = normalized_status in {"completed", "dropped"}
        rows.append(
            _row(
                value.statement,
                detail or "Commitment is still open.",
                value.risk_level.capitalize(),
                href=f"/app/commitment-items/{value.id}",
                action_href=f"/app/actions/queue/{value.id}/resolve",
                action_label="Reopen" if is_resolved else "Close",
                action_value="reopen" if is_resolved else "close",
                return_to=return_to,
                secondary_action_href=f"/app/actions/queue/{value.id}/resolve",
                secondary_action_label="" if is_resolved else "Defer",
                secondary_action_value="" if is_resolved else "defer",
                secondary_action_method="post",
                secondary_return_to=return_to,
                tertiary_action_href="" if is_resolved else f"/app/actions/queue/{value.id}/resolve",
                tertiary_action_label="" if is_resolved else "Drop",
                tertiary_action_value="" if is_resolved else "drop",
                tertiary_action_method="post",
                tertiary_return_to=return_to,
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
        thread_ref = str(value.thread_ref or value.id).strip() or value.id
        thread_id = thread_ref if thread_ref.startswith("thread:") else f"thread:{thread_ref}"
        detail = " · ".join(
            part
            for part in (
                value.intent.title(),
                value.send_channel,
                value.approval_status,
                value.provenance_refs[0].note if value.provenance_refs else "",
                value.draft_text[:96] if value.draft_text else "",
            )
            if part
        )
        rows.append(
            _row(
                value.recipient_summary or value.intent.title(),
                detail or "Draft awaiting review.",
                "Draft",
                href=f"/app/threads/{thread_id}",
                action_href=f"/app/actions/drafts/{value.id}/approve",
                action_label="Approve",
                return_to="/app/inbox",
                secondary_action_href=f"/app/actions/drafts/{value.id}/reject",
                secondary_action_label="Reject",
                secondary_action_method="post",
                secondary_return_to="/app/inbox",
                tertiary_action_href=f"/app/threads/{thread_id}",
                tertiary_action_label="Open thread",
                tertiary_action_method="get",
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


def _handoff_rows(values: tuple[HandoffNote, ...], *, operator_id: str = "", actionable: bool = True, return_to: str = "/app/follow-ups") -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for value in values:
        action_options = handoff_action_options(value, operator_id=operator_id, return_to=return_to) if actionable else ()
        detail = " · ".join(
            part
            for part in (
                value.owner,
                f"Due {value.due_time[:10]}" if value.due_time else "",
                value.recipient_email if value.task_type == "delivery_followup" and value.recipient_email else "",
                (
                    "Needs reauth"
                    if value.task_type == "delivery_followup" and str(value.delivery_reason or "").strip().startswith("google_")
                    else "Unable to send"
                    if value.task_type == "delivery_followup" and str(value.delivery_reason or "").strip()
                    else ""
                ),
                value.evidence_refs[0].note if value.evidence_refs else "",
            )
            if part
        )
        action_href = ""
        action_label = ""
        action_value = ""
        action_method = ""
        secondary_action_href = ""
        secondary_action_label = ""
        secondary_action_value = ""
        secondary_action_method = ""
        tertiary_action_href = ""
        tertiary_action_label = ""
        tertiary_action_value = ""
        tertiary_action_method = ""
        quaternary_action_href = ""
        quaternary_action_label = ""
        quaternary_action_value = ""
        quaternary_action_method = ""
        for index, option in enumerate(action_options[:4]):
            route = str(option.get("route") or "").strip()
            href = str(option.get("href") or "").strip()
            resolved_href = href or (
                f"/app/actions/handoffs/{value.id}/{route}"
                if route
                else ""
            )
            resolved_method = str(option.get("method") or ("get" if href else "post")).strip().lower()
            resolved_label = str(option.get("label") or "").strip()
            resolved_value = str(option.get("value") or "").strip()
            if index == 0:
                action_href = resolved_href
                action_label = resolved_label
                action_value = resolved_value
                action_method = resolved_method
            elif index == 1:
                secondary_action_href = resolved_href
                secondary_action_label = resolved_label
                secondary_action_value = resolved_value
                secondary_action_method = resolved_method
            elif index == 2:
                tertiary_action_href = resolved_href
                tertiary_action_label = resolved_label
                tertiary_action_value = resolved_value
                tertiary_action_method = resolved_method
            else:
                quaternary_action_href = resolved_href
                quaternary_action_label = resolved_label
                quaternary_action_value = resolved_value
                quaternary_action_method = resolved_method
        rows.append(
            _row(
                value.summary,
                detail or "Handoff remains open.",
                value.escalation_status.capitalize(),
                href=f"/app/handoffs/{value.id}",
                action_href=action_href if actionable else "",
                action_label=action_label if actionable else "",
                action_value=action_value if actionable else "",
                action_method=action_method if actionable else "",
                return_to=return_to if actionable and action_href else "",
                secondary_action_href=secondary_action_href if actionable else "",
                secondary_action_label=secondary_action_label if actionable else "",
                secondary_action_value=secondary_action_value if actionable else "",
                secondary_action_method=secondary_action_method if actionable else "",
                secondary_return_to=return_to if actionable and secondary_action_href else "",
                tertiary_action_href=tertiary_action_href if actionable else "",
                tertiary_action_label=tertiary_action_label if actionable else "",
                tertiary_action_value=tertiary_action_value if actionable else "",
                tertiary_action_method=tertiary_action_method if actionable else "",
                tertiary_return_to=return_to if actionable and tertiary_action_href else "",
                quaternary_action_href=quaternary_action_href if actionable else "",
                quaternary_action_label=quaternary_action_label if actionable else "",
                quaternary_action_value=quaternary_action_value if actionable else "",
                quaternary_action_method=quaternary_action_method if actionable else "",
                quaternary_return_to=return_to if actionable and quaternary_action_href else "",
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
    product_control = dict(diagnostics.get("product_control") or {})
    analytics = dict(diagnostics.get("analytics") or {})
    analytics_counts = dict(analytics.get("counts") or {})
    analytics_delivery = dict(analytics.get("delivery") or {})
    analytics_sync = dict(analytics.get("sync") or {})
    journey_gate = dict(product_control.get("journey_gate_health") or {})
    support_fallout = dict(product_control.get("support_fallout") or {})
    public_guide_freshness = dict(product_control.get("public_guide_freshness") or {})
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
        _row("Active product wave", str(product_control.get("active_wave") or "No active wave mirrored."), "Product", href="/app/settings/support"),
        _row("Journey gate health", str(journey_gate.get("state") or "missing").replace("_", " "), "Product", href="/app/settings/support"),
        _row("Support fallout", str(support_fallout.get("detail") or "No support fallout mirrored."), "Support", href="/app/settings/support"),
        _row("Launch readiness", str(product_control.get("launch_readiness") or "No launch note mirrored."), "Product", href="/app/settings/support"),
        _row("Public guide freshness", str(public_guide_freshness.get("detail") or "No public-guide freshness mirrored."), "Guide", href="/app/settings/support"),
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
        _row("Draft approvals granted", str(analytics_counts.get("draft_approved") or 0), "Analytics", href="/app/settings/usage"),
        _row(
            "Blocked send follow-ups",
            str(analytics.get("delivery_followup_blocked_count") or 0),
            "Analytics",
            href="/app/settings/outcomes",
        ),
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
    outcomes: dict[str, object] | None = None,
    *,
    operator_id: str = "",
) -> dict[str, object]:
    diagnostics = diagnostics or {}
    outcomes = outcomes or {}
    operator_key = str(operator_id or "").strip()
    queue_health = dict(diagnostics.get("queue_health") or {})
    provider_posture = dict(diagnostics.get("providers") or {})
    commercial = dict(diagnostics.get("commercial") or {})
    readiness = dict(diagnostics.get("readiness") or {})
    product_control = dict(diagnostics.get("product_control") or {})
    analytics = dict(diagnostics.get("analytics") or {})
    analytics_delivery = dict(analytics.get("delivery") or {})
    analytics_access = dict(analytics.get("access") or {})
    analytics_sync = dict(analytics.get("sync") or {})
    journey_gate = dict(product_control.get("journey_gate_health") or {})
    journey_freshness = dict(product_control.get("journey_gate_freshness") or {})
    support_fallout = dict(product_control.get("support_fallout") or {})
    public_guide_freshness = dict(product_control.get("public_guide_freshness") or {})
    route_stewardship = dict(product_control.get("provider_route_stewardship") or {})
    memo_loop = dict(outcomes.get("memo_loop") or analytics.get("memo_loop") or {})
    office_loop_proof = dict(outcomes.get("office_loop_proof") or {})
    proof_checks = [dict(value) for value in list(office_loop_proof.get("checks") or [])]
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
    active_memo_delivery_blocker = 1 if str(memo_loop.get("last_issue_reason") or "").strip() else 0
    active_delivery_issue_total = int(queue_health.get("delivery_errors") or 0) + active_memo_delivery_blocker
    exception_rows = [
        _row(
            "Delivery issues",
            (
                f"{int(queue_health.get('delivery_errors') or 0)} queue delivery errors · "
                f"{active_memo_delivery_blocker} active memo blockers"
            ),
            "Support",
            href="/app/settings/support",
        )
        for _ in [0]
        if active_delivery_issue_total
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
    open_commitments = _sorted_open_commitments(snapshot.commitments)
    due_now_commitments = _commitments_due_now(snapshot.commitments)
    stale_commitments = _stale_commitments(snapshot.commitments)
    waiting_commitments = _commitments_by_status(snapshot.commitments, "waiting_on_external", "scheduled")
    sorted_people = _sorted_people(snapshot.people)
    open_decisions = tuple(value for value in snapshot.decisions if status_open(value.status))
    principal_queue = tuple(value for value in snapshot.queue_items if value.requires_principal)
    mapping: dict[str, dict[str, object]] = {
        "today": {
            "title": "Morning Memo",
            "summary": "What changed, what is blocked, and what deserves attention before the day drifts.",
            "cards": [
                {
                    "eyebrow": "Top priorities",
                    "title": "What deserves attention first",
                    "body": "Start on the ranked work that already has evidence, risk, and a visible next move.",
                    "items": _brief_rows(snapshot.brief_items[:6], tag="Priority")
                    or [_row("No top priorities", "The memo has not surfaced any ranked work yet.", "Clear")],
                },
                {
                    "eyebrow": "Blocked decisions",
                    "title": "What needs an explicit call",
                    "body": "Decisions are first-class product objects, not just queue summaries.",
                    "items": _decision_rows(open_decisions[:6], return_to="/app/today")
                    or [_row("No blocked decisions", "Nothing currently needs a decision call from this workspace.", "Clear")],
                },
                {
                    "eyebrow": "At-risk commitments",
                    "title": "What is most likely to slip today",
                    "body": "Promises, deadlines, and follow-ups stay visible before they silently roll into tomorrow.",
                    "items": _commitment_rows((due_now_commitments or open_commitments)[:6], return_to="/app/today")
                    or [_row("No commitments at risk", "Nothing open is currently due now or overdue.", "Clear")],
                },
                {
                    "eyebrow": "Pending approvals",
                    "title": "What is waiting for review",
                    "body": "Draft approvals remain visible product work instead of leaking into hidden runtime state.",
                    "items": _draft_queue_rows(snapshot.drafts[:6]),
                },
                {
                    "eyebrow": "Stakeholder changes",
                    "title": "Who moved overnight",
                    "body": "People pressure is part of the office loop, not an afterthought.",
                    "items": _people_rows(sorted_people[:6])
                    or [_row("No stakeholder movement", "No people changes are shaping the current workspace view.", "Clear")],
                },
            ],
        },
        "briefing": {
            "title": "Decision Queue",
            "summary": "Clear the day by resolving what is blocked, what needs approval, and which commitments are running out of runway.",
            "cards": [
                {
                    "eyebrow": "Overnight changes",
                    "title": "What changed since the last memo",
                    "body": "Start the brief on surfaced changes rather than a generic queue summary.",
                    "items": _brief_rows(snapshot.brief_items[:8], tag="Brief")
                    or [_row("No overnight changes", "The brief has not surfaced any new movement yet.", "Clear")],
                },
                {
                    "eyebrow": "Calendar pressure",
                    "title": "What gets tight first",
                    "body": "Decision and deadline windows should be readable as day pressure, not just metadata.",
                    "items": _calendar_pressure_rows(snapshot.queue_items),
                },
                {
                    "eyebrow": "People to respond to",
                    "title": "Who needs a reply or correction",
                    "body": "Threads and people stay attached to the brief so the next reply is obvious.",
                    "items": _thread_rows(snapshot.threads[:6]) or _people_rows(sorted_people[:6]),
                },
                {
                    "eyebrow": "Commitments at risk",
                    "title": "What the brief is protecting",
                    "body": "The brief matters because it keeps active commitments from slipping.",
                    "items": _commitment_rows((due_now_commitments or open_commitments)[:6], return_to="/app/briefing")
                    or [_row("No commitments at risk", "No current commitments are pressing on the day.", "Clear")],
                },
                {
                    "eyebrow": "Blocked decisions",
                    "title": "What still needs a call",
                    "body": "Blocked choices stay visible with their next action and impact.",
                    "items": _decision_rows(open_decisions[:8], return_to="/app/briefing")
                    or [_row("No blocked decisions", "No unresolved decisions are currently shaping the brief.", "Clear")],
                },
                {
                    "eyebrow": "Suggested sequence",
                    "title": "What to clear in order",
                    "body": "Use one explicit sequence for the next moves instead of reconstructing it by hand.",
                    "items": _suggested_sequence_rows(
                        decisions=open_decisions,
                        drafts=snapshot.drafts,
                        commitments=due_now_commitments or open_commitments,
                        people=sorted_people,
                    ),
                },
            ],
        },
        "inbox": {
            "title": "Draft Queue",
            "summary": "Reviewable drafts stay first, with open commitments and conversation context still attached to the same queue.",
            "cards": [
                {
                    "eyebrow": "Ready for review",
                    "title": "What can be approved right now",
                    "body": "Keep ready drafts at the front of the inbox instead of hiding them behind generic commitment cards.",
                    "items": _draft_queue_rows(snapshot.drafts[:8]),
                },
                {
                    "eyebrow": "Open commitments",
                    "title": "Open commitments",
                    "body": "The response queue stays honest when open commitments remain visible beside the draft work.",
                    "items": _commitment_rows(open_commitments[:8])
                    or [_row("No open commitments", "There are no active commitments tied to the inbox right now.", "Clear")],
                },
                {
                    "eyebrow": "Conversation threads",
                    "title": "What live conversations are shaping the queue",
                    "body": "Threads are now a first-class product object tied to drafts, commitments, and decisions.",
                    "items": _thread_rows(snapshot.threads[:6])
                    or [_row("No live threads", "No thread context is currently shaping the inbox queue.", "Clear")],
                },
                {
                    "eyebrow": "Pending captures",
                    "title": "What still needs commitment review",
                    "body": "Extracted commitments stay reviewable before they enter the live ledger.",
                    "items": _candidate_rows(snapshot.commitment_candidates[:6])
                    or [_row("No pending captures", "Nothing is waiting to be reviewed into the commitment ledger.", "Clear")],
                },
                {
                    "eyebrow": "Decision pressure",
                    "title": "What will force movement next",
                    "body": "The commitment loop stays honest when decisions and deadlines remain visible.",
                    "items": _queue_rows(snapshot.queue_items[:6])
                    or [_row("No decision pressure", "No queue items are currently forcing inbox movement.", "Clear")],
                },
            ],
        },
        "follow-ups": {
            "title": "Follow-up Ledger",
            "summary": "Keep due work, handoffs, unresolved promises, and recently closed movement visible in one lane.",
            "cards": [
                {
                    "eyebrow": "Due now",
                    "title": "What is due today or already overdue",
                    "body": "The follow-up ledger should open on the work most likely to miss today.",
                    "items": _commitment_rows((due_now_commitments or open_commitments)[:8], return_to="/app/follow-ups")
                    or [_row("No due follow-ups", "Nothing open is due now or overdue.", "Clear")],
                },
                {
                    "eyebrow": "Waiting on others",
                    "title": "What is blocked outside the office loop",
                    "body": "Use explicit waiting and scheduled states instead of leaving external dependencies hidden inside open promises.",
                    "items": (
                        _commitment_rows(waiting_commitments[:8], return_to="/app/follow-ups")
                        + _handoff_rows(snapshot.handoffs[:8], operator_id=operator_key, return_to="/app/follow-ups")
                    )[:8]
                    or [_row("No external waits", "Nothing is currently waiting on another party or operator handoff.", "Clear")],
                },
                {
                    "eyebrow": "Unresolved promises",
                    "title": "What still needs a close or defer",
                    "body": "Open promises should stay clear even when the queue is noisy.",
                    "items": _commitment_rows(open_commitments[:8], return_to="/app/follow-ups")
                    or [_row("No unresolved promises", "The follow-up ledger does not currently have open promises.", "Clear")],
                },
                {
                    "eyebrow": "Stale work",
                    "title": "What has drifted too long",
                    "body": "Overdue or untouched follow-ups should be obvious instead of hiding in the ledger.",
                    "items": _commitment_rows(stale_commitments[:8], return_to="/app/follow-ups")
                    or [_row("No stale commitments", "Open follow-ups are still moving inside an acceptable window.", "Clear")],
                },
                {
                    "eyebrow": "Recently closed",
                    "title": "What just moved through the loop",
                    "body": "Recently completed commitments and handoffs stay visible long enough to confirm the loop actually closed.",
                    "items": (
                        _commitment_rows(snapshot.recently_closed_commitments[:6], return_to="/app/follow-ups")
                        + _handoff_rows(snapshot.completed_handoffs[:6], actionable=False, return_to="/app/follow-ups")
                    )[:6]
                    or [_row("Nothing recently closed", "Completed handoffs will appear here once the loop closes.", "Clear")],
                },
                {
                    "eyebrow": "Stakeholders",
                    "title": "Who the follow-up lane affects",
                    "body": "The office loop stays legible when people stay attached to the work.",
                    "items": _people_rows(sorted_people[:6])
                    or [_row("No stakeholder pressure", "No people records are currently attached to this follow-up lane.", "Clear")],
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
                    "items": _handoff_rows(assigned_handoffs[:8], operator_id=operator_key, return_to="/app/activity"),
                },
                {
                    "eyebrow": "Unclaimed handoffs",
                    "title": "What can be claimed next",
                    "body": "Operator work should be explicit, claimable, and closable from the same queue.",
                    "items": _handoff_rows(remaining_unclaimed_handoffs[:8], operator_id=operator_key, return_to="/app/activity")
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
                    "body": "Returned handoffs and recently closed commitments should stay visible long enough to confirm the office loop actually closed.",
                    "items": (
                        _commitment_rows(snapshot.recently_closed_commitments[:6], return_to="/app/activity")
                        + _handoff_rows(snapshot.completed_handoffs[:6], actionable=False)
                    )[:6],
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
            "summary": "Keep the memo loop, capture rules, and proof of value visible without dragging the operator control plane into the principal workspace.",
            "console_form": {
                "action": "/app/actions/settings/morning-memo",
                "method": "post",
                "eyebrow": "Workspace rules",
                "title": "Update workspace and morning memo rules",
                "copy": "Keep the office profile and the memo schedule editable after onboarding so the live loop can stay aligned with the real workspace.",
                "submit_label": "Save workspace rules",
                "fields": [
                    {
                        "label": "Workspace name",
                        "name": "workspace_name",
                        "type": "text",
                        "value": str(dict(diagnostics.get("workspace") or {}).get("name") or ""),
                        "placeholder": "Executive Workspace",
                    },
                    {
                        "label": "Language",
                        "name": "language",
                        "type": "text",
                        "value": str(dict(diagnostics.get("workspace") or {}).get("language") or "en"),
                        "placeholder": "en",
                    },
                    {
                        "label": "Timezone",
                        "name": "timezone",
                        "type": "text",
                        "value": str(dict(diagnostics.get("workspace") or {}).get("timezone") or "Europe/Vienna"),
                        "placeholder": "Europe/Vienna",
                    },
                    {
                        "label": "Enable scheduled memo",
                        "name": "enabled",
                        "type": "checkbox",
                        "value": "true",
                        "checked": bool(memo_loop.get("enabled")),
                    },
                    {
                        "label": "Cadence",
                        "name": "cadence",
                        "type": "select",
                        "value": str(memo_loop.get("cadence") or "daily_morning"),
                        "options": [
                            {"label": "Every day", "value": "daily_morning"},
                            {"label": "Weekdays", "value": "weekdays_morning"},
                        ],
                    },
                    {
                        "label": "Recipient email",
                        "name": "recipient_email",
                        "type": "email",
                        "value": str(memo_loop.get("recipient_email") or ""),
                        "placeholder": "Uses the connected Google email when left blank",
                    },
                    {
                        "label": "Delivery time",
                        "name": "delivery_time_local",
                        "type": "time",
                        "value": str(memo_loop.get("delivery_time_local") or "08:00"),
                    },
                    {
                        "label": "Quiet hours start",
                        "name": "quiet_hours_start",
                        "type": "time",
                        "value": str(memo_loop.get("quiet_hours_start") or "20:00"),
                    },
                    {
                        "label": "Quiet hours end",
                        "name": "quiet_hours_end",
                        "type": "time",
                        "value": str(memo_loop.get("quiet_hours_end") or "07:00"),
                    },
                ],
            },
            "cards": [
                {
                    "eyebrow": "Morning memo",
                    "title": "Morning memo delivery",
                    "body": "The scheduled memo should stay legible: when it lands, who it lands to, and whether it is producing a useful daily loop.",
                    "items": [
                        _row("Memo state", str(memo_loop.get("state") or "watch").replace("_", " ").title(), "Memo", href="/app/settings/outcomes"),
                        _row("Enabled", "Yes" if memo_loop.get("enabled") else "No", "Memo", href="/app/settings/outcomes"),
                        _row("Cadence", str(memo_loop.get("cadence") or "daily_morning").replace("_", " "), "Memo", href="/app/settings/outcomes"),
                        _row(
                            "Delivery time",
                            f"{memo_loop.get('delivery_time_local') or '08:00'} {memo_loop.get('timezone') or dict(diagnostics.get('workspace') or {}).get('timezone') or 'UTC'}",
                            "Memo",
                            href="/app/settings/outcomes",
                        ),
                        _row("Recipient", str(memo_loop.get("recipient_email") or "waiting for recipient"), "Memo", href="/app/settings/outcomes"),
                        _row("Useful loop days", str(memo_loop.get("days_with_useful_loop") or 0), "Memo", href="/app/settings/outcomes"),
                        _row("Last scheduled send", str(memo_loop.get("last_scheduled_sent_at") or "not yet sent"), "Memo", href="/app/settings/outcomes"),
                        _row("Blocked sends", str(memo_loop.get("scheduled_blocked") or 0), "Memo", href="/app/settings/outcomes"),
                        _row("Failed sends", str(memo_loop.get("scheduled_failed") or 0), "Memo", href="/app/settings/outcomes"),
                        _row(
                            "Last memo issue",
                            str(memo_loop.get("last_issue_reason") or "No current memo blocker"),
                            "Memo",
                            href="/app/settings/outcomes",
                        ),
                    ],
                },
                {
                    "eyebrow": "Google signal loop",
                    "title": "What is feeding the office loop",
                    "body": "Gmail and Calendar should explain whether fresh signals are entering the queue and whether staged work is ready for review.",
                    "items": [
                        _google_settings_action_row(analytics_sync, return_to="/app/settings/google"),
                        _row("Google account", str(analytics_sync.get("google_account_email") or "Not connected"), "Sync", href="/app/settings/google"),
                        _row(
                            "Freshness",
                            str(analytics_sync.get("google_sync_freshness_state") or "watch").replace("_", " ").title(),
                            "Sync",
                            href="/app/settings/google",
                            action_href="/app/actions/signals/google/sync?return_to=/app/settings/google" if analytics_sync.get("google_connected") else "",
                            action_label="Run now" if analytics_sync.get("google_connected") else "",
                            action_method="get" if analytics_sync.get("google_connected") else "",
                        ),
                        _row("Token status", str(analytics_sync.get("google_token_status") or "missing").replace("_", " ").title(), "Sync", href="/app/settings/google"),
                        _row("Sync runs", str(analytics_sync.get("google_sync_completed") or 0), "Sync", href="/app/settings/google"),
                        _row("Last Google sync", str(analytics_sync.get("google_sync_last_completed_at") or "Not yet run"), "Sync", href="/app/settings/google"),
                        _row("Office signals ingested", str(analytics_sync.get("office_signal_ingested") or 0), "Sync", href="/app/settings/google"),
                        _row("Suppressed sync noise", str(analytics_sync.get("google_sync_last_suppressed_total") or 0), "Sync", href="/app/settings/google"),
                        _row("Pending sync candidates", str(analytics_sync.get("pending_commitment_candidates") or 0), "Sync", href="/app/inbox"),
                    ],
                },
                {
                    "eyebrow": "Workspace rules",
                    "title": "What this office currently allows",
                    "body": "Rules should explain the review-first posture, channel boundary, and durable controls behind the current loop.",
                    "items": _rule_rows(snapshot.rules[:8]),
                },
                {
                    "eyebrow": "Product control",
                    "title": "What the release proof says right now",
                    "body": "This surface should mirror the weekly product pulse and published journey-gate truth without turning the assistant into a second roadmap owner.",
                    "items": [
                        _row("Active product wave", str(product_control.get("active_wave") or "No active wave mirrored."), "Wave", href="/app/settings/outcomes"),
                        _row("Journey gate health", str(journey_gate.get("state") or "missing").replace("_", " ").title(), "Gate", href="/app/settings/outcomes"),
                        _row("Journey gate action", str(journey_gate.get("recommended_action") or journey_gate.get("reason") or "No published action."), "Gate", href="/app/settings/outcomes"),
                        _row("Support fallout", str(support_fallout.get("detail") or "No support fallout mirrored."), "Support", href="/app/settings/outcomes"),
                        _row("Launch readiness", str(product_control.get("launch_readiness") or "No launch note mirrored."), "Launch", href="/app/settings/outcomes"),
                        _row("Route default", str(route_stewardship.get("default_status") or "No route default note published."), "Route", href="/app/settings/outcomes"),
                        _row("Canary posture", str(route_stewardship.get("canary_status") or "No canary note published."), "Route", href="/app/settings/outcomes"),
                        _row("Route review due", str(route_stewardship.get("review_due") or "No route review due published."), "Route", href="/app/settings/outcomes"),
                        _row("Journey proof freshness", str(journey_freshness.get("detail") or "No journey-gate freshness mirrored."), "Proof", href="/app/settings/outcomes"),
                        _row("Public guide freshness", str(public_guide_freshness.get("detail") or "No public-guide freshness mirrored."), "Guide", href="/app/settings/outcomes"),
                    ],
                },
                {
                    "eyebrow": "Office-loop proof",
                    "title": "How the daily office loop is proving itself",
                    "body": "The principal surface should say plainly whether the memo is being opened, approvals are moving, and commitments are closing at a believable rate.",
                    "items": [
                        _row("Gate state", str(office_loop_proof.get("state") or "watch").replace("_", " ").title(), "Gate", href="/app/settings/outcomes"),
                        _row(
                            "Passed checks",
                            f"{int(office_loop_proof.get('passed_checks') or 0)}/{int(office_loop_proof.get('check_total') or 0)}",
                            "Gate",
                            href="/app/settings/outcomes",
                        ),
                        _row("Summary", str(office_loop_proof.get("summary") or "No proof summary yet."), "Gate", href="/app/settings/outcomes"),
                        _row("Memo open rate", str(outcomes.get("memo_open_rate") or analytics.get("memo_open_rate") or 0), "Memo", href="/app/settings/outcomes"),
                        _row("Approval coverage rate", str(outcomes.get("approval_coverage_rate") or analytics.get("approval_coverage_rate") or 0), "Approvals", href="/app/settings/outcomes"),
                        _row("Approval send rate", str(outcomes.get("approval_action_rate") or analytics.get("approval_action_rate") or 0), "Approvals", href="/app/settings/outcomes"),
                        _row(
                            "Follow-up closeout rate",
                            str(
                                outcomes.get("delivery_followup_resolution_rate")
                                if outcomes.get("delivery_followup_resolution_rate") is not None
                                else analytics.get("delivery_followup_resolution_rate")
                                if analytics.get("delivery_followup_resolution_rate") is not None
                                else "n/a"
                            ),
                            "Operators",
                            href="/app/settings/outcomes",
                        ),
                        _row(
                            "Blocked follow-up rate",
                            str(
                                outcomes.get("delivery_followup_blocked_rate")
                                if outcomes.get("delivery_followup_blocked_rate") is not None
                                else analytics.get("delivery_followup_blocked_rate")
                                if analytics.get("delivery_followup_blocked_rate") is not None
                                else "n/a"
                            ),
                            "Operators",
                            href="/app/settings/outcomes",
                        ),
                        _row("Commitment close rate", str(outcomes.get("commitment_close_rate") or analytics.get("commitment_close_rate") or 0), "Commitments", href="/app/settings/outcomes"),
                        *[
                            _row(
                                str(item.get("label") or "Check"),
                                (
                                    f"{item.get('actual')} / <= {item.get('target_max')}"
                                    if item.get("target_max") is not None
                                    else f"{item.get('actual')} / {item.get('target')}"
                                ),
                                str(item.get("state") or "watch").replace("_", " ").title(),
                                href="/app/settings/outcomes",
                            )
                            for item in proof_checks[:4]
                        ],
                    ],
                },
            ],
        },
    }
    return {"stats": stats, **mapping[section]}
