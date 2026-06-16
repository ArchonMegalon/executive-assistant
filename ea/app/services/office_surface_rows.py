from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.product.models import BriefItem, CommitmentCandidate, CommitmentItem, DecisionItem, DecisionQueueItem, DraftCandidate, EvidenceItem, HandoffNote, PersonProfile, RuleItem, ThreadItem
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
                return_to="/app/queue",
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
                return_to="/app/queue",
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
                return_to="/app/queue",
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
                return_to="/app/queue",
                secondary_action_href=f"/app/actions/queue/{value.id}/resolve" if value.id.startswith(("commitment:", "follow_up:")) else "",
                secondary_action_label="Drop" if value.id.startswith(("commitment:", "follow_up:")) else "",
                secondary_action_value="drop" if value.id.startswith(("commitment:", "follow_up:")) else "",
                secondary_action_method="post" if value.id.startswith(("commitment:", "follow_up:")) else "",
                secondary_return_to="/app/queue" if value.id.startswith(("commitment:", "follow_up:")) else "",
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


def _commitment_rows(values: tuple[CommitmentItem, ...], *, return_to: str = "/app/commitments") -> list[dict[str, str]]:
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
                return_to="/app/queue",
                secondary_action_href=f"/app/actions/commitments/candidates/{value.candidate_id}/reject",
                secondary_action_label="Reject",
                secondary_action_method="post",
                secondary_return_to="/app/queue",
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
                return_to="/app/queue",
                secondary_action_href=f"/app/actions/drafts/{value.id}/reject",
                secondary_action_label="Reject",
                secondary_action_method="post",
                secondary_return_to="/app/queue",
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


def _handoff_rows(values: tuple[HandoffNote, ...], *, operator_id: str = "", actionable: bool = True, return_to: str = "/app/commitments") -> list[dict[str, str]]:
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
        _row("Load score", str(queue_health.get("load_score") or 0), "Queue", href="/app/settings/usage"),
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
            "Blocked delivery handoffs",
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
            secondary_action_href="/app/api/diagnostics/export?download=1",
            secondary_action_label="Download JSON",
            secondary_action_method="get",
            secondary_return_to=return_to,
        ),
    ]
