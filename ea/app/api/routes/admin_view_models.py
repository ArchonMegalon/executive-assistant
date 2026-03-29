from __future__ import annotations

from typing import Any

from app.container import AppContainer
from app.product.projections.handoffs import handoff_action_options, handoff_action_plan, handoff_from_human_task
from app.product.service import build_product_service


def _row(
    title: str,
    detail: str,
    tag: str,
    *,
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
    return row


def _humanize(value: str) -> str:
    return str(value or "").strip().replace("_", " ") or "unknown"


def _operator_rows(values: object) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for value in values if isinstance(values, (list, tuple)) else []:
        detail = " · ".join(
            part
            for part in (
                ", ".join(getattr(value, "roles", ()) or ()),
                getattr(value, "trust_tier", ""),
                getattr(value, "status", ""),
            )
            if str(part or "").strip()
        )
        rows.append(_row(getattr(value, "display_name", "") or getattr(value, "operator_id", "Operator"), detail or "Active operator.", "Operator"))
    return rows


def _handoff_rows(values: object, *, operator_id: str = "", actionable: bool = True, return_to: str = "/admin/office") -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    operator_key = str(operator_id or "").strip()
    for value in values if isinstance(values, (list, tuple)) else []:
        handoff_id = str(getattr(value, "id", "") or "").strip()
        owner = str(getattr(value, "owner", "") or "").strip()
        action_options = handoff_action_options(value, operator_id=operator_key, return_to=return_to) if actionable else ()
        detail = " · ".join(
            part
            for part in (
                owner or "Unassigned",
                f"due {str(getattr(value, 'due_time', '') or '')[:10]}" if getattr(value, "due_time", None) else "",
                str(getattr(value, "recipient_email", "") or "").strip()
                if str(getattr(value, "task_type", "") or "").strip() == "delivery_followup"
                else "",
                (
                    "Needs reauth"
                    if str(getattr(value, "task_type", "") or "").strip() == "delivery_followup"
                    and str(getattr(value, "delivery_reason", "") or "").strip().startswith("google_")
                    else "Unable to send"
                    if str(getattr(value, "task_type", "") or "").strip() == "delivery_followup"
                    and str(getattr(value, "delivery_reason", "") or "").strip()
                    else ""
                ),
                str(getattr(value, "escalation_status", "") or "").replace("_", " ").title(),
            )
            if str(part or "").strip()
        ) or "Handoff is still open."
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
        if actionable and handoff_id:
            for index, option in enumerate(action_options[:3]):
                route = str(option.get("route") or "").strip()
                href = str(option.get("href") or "").strip()
                resolved_href = href or f"/app/actions/handoffs/{handoff_id}/{route}" if route else href
                resolved_label = str(option.get("label") or "").strip()
                resolved_value = str(option.get("value") or "").strip()
                resolved_method = str(option.get("method") or ("get" if href else "post")).strip().lower()
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
                else:
                    tertiary_action_href = resolved_href
                    tertiary_action_label = resolved_label
                    tertiary_action_value = resolved_value
                    tertiary_action_method = resolved_method
        rows.append(
            _row(
                str(getattr(value, "summary", "") or "Handoff"),
                detail,
                str(getattr(value, "escalation_status", "") or "handoff").replace("_", " ").title(),
                href=f"/app/handoffs/{handoff_id}" if handoff_id else "",
                action_href=action_href,
                action_label=action_label,
                action_value=action_value,
                action_method=action_method,
                return_to=return_to if action_href else "",
                secondary_action_href=secondary_action_href,
                secondary_action_label=secondary_action_label,
                secondary_action_value=secondary_action_value,
                secondary_action_method=secondary_action_method,
                secondary_return_to=return_to if secondary_action_href else "",
                tertiary_action_href=tertiary_action_href,
                tertiary_action_label=tertiary_action_label,
                tertiary_action_value=tertiary_action_value,
                tertiary_action_method=tertiary_action_method,
                tertiary_return_to=return_to if tertiary_action_href else "",
            )
        )
    return rows


def _human_task_row(value: object, *, operator_id: str, return_to: str) -> dict[str, str]:
    handoff = handoff_from_human_task(value)
    action_options = handoff_action_options(handoff, operator_id=operator_id, return_to=return_to)
    primary = action_options[0] if action_options else {}
    secondary = action_options[1] if len(action_options) > 1 else {}
    tertiary = action_options[2] if len(action_options) > 2 else {}
    primary_href = str(primary.get("href") or f"/app/actions/handoffs/human_task:{getattr(value, 'human_task_id', '')}/{str(primary.get('route') or 'assign').strip()}").strip() if primary else ""
    secondary_route = str(secondary.get("route") or "").strip()
    secondary_href = str(secondary.get("href") or (f"/app/actions/handoffs/human_task:{getattr(value, 'human_task_id', '')}/{secondary_route}" if secondary_route else "")).strip()
    tertiary_route = str(tertiary.get("route") or "").strip()
    tertiary_href = str(tertiary.get("href") or (f"/app/actions/handoffs/human_task:{getattr(value, 'human_task_id', '')}/{tertiary_route}" if tertiary_route else "")).strip()
    return _row(
        str(getattr(value, "brief", "") or "Human task"),
        " · ".join(
            part
            for part in (
                _humanize(getattr(value, "role_required", "")),
                f"priority {getattr(value, 'priority', '')}",
                f"due {str(getattr(value, 'sla_due_at', '') or '')[:10]}" if getattr(value, "sla_due_at", None) else "",
                handoff.recipient_email if handoff.task_type == "delivery_followup" and handoff.recipient_email else "",
                (
                    "Needs reauth"
                    if handoff.task_type == "delivery_followup" and str(handoff.delivery_reason or "").strip().startswith("google_")
                    else "Unable to send"
                    if handoff.task_type == "delivery_followup" and str(handoff.delivery_reason or "").strip()
                    else ""
                ),
            )
            if str(part or "").strip()
        )
        or "Human task remains open.",
        "Task",
        action_href=primary_href,
        action_label=str(primary.get("label") or ""),
        action_value=str(primary.get("value") or ""),
        action_method=str(primary.get("method") or ""),
        return_to=return_to,
        secondary_action_href=secondary_href,
        secondary_action_label=str(secondary.get("label") or ""),
        secondary_action_value=str(secondary.get("value") or ""),
        secondary_action_method=str(secondary.get("method") or ""),
        secondary_return_to=return_to if secondary_href else "",
        tertiary_action_href=tertiary_href,
        tertiary_action_label=str(tertiary.get("label") or ""),
        tertiary_action_value=str(tertiary.get("value") or ""),
        tertiary_action_method=str(tertiary.get("method") or ""),
        tertiary_return_to=return_to if tertiary_href else "",
    )

def build_admin_section_payload(section: str, *, container: AppContainer, principal_id: str, operator_id: str = "") -> dict[str, object]:
    readiness_ok, readiness_label = container.readiness.check()
    readiness_state = "ready" if readiness_ok else "attention"
    status = container.onboarding.status(principal_id=principal_id)
    privacy = dict(status.get("privacy") or {})
    delivery_preferences = dict(status.get("delivery_preferences") or {})
    morning_memo = dict(delivery_preferences.get("morning_memo") or {})
    product = build_product_service(container)
    diagnostics = product.workspace_diagnostics(principal_id=principal_id)
    office = product.operator_center(principal_id=principal_id, operator_id=operator_id)
    office_snapshot_state = product.workspace_snapshot(principal_id=principal_id, operator_id=operator_id)
    approvals = container.orchestrator.list_pending_approvals_for_principal(principal_id=principal_id, limit=8)
    approval_history = container.orchestrator.list_approval_history_for_principal(principal_id=principal_id, limit=8)
    human_tasks = container.orchestrator.list_human_tasks(principal_id=principal_id, status="pending", limit=8)
    returned_human_tasks = container.orchestrator.list_human_tasks(principal_id=principal_id, status="returned", limit=8)
    task_summary = container.orchestrator.summarize_human_task_priorities(principal_id=principal_id, status="pending")
    operators = container.orchestrator.list_operator_profiles(principal_id=principal_id, status="active", limit=8)
    pending_delivery = container.channel_runtime.list_pending_delivery(limit=8, principal_id=principal_id)
    registry = container.provider_registry.registry_read_model(principal_id=principal_id)
    providers = list(registry.get("providers") or [])
    lanes = list(registry.get("lanes") or [])

    provider_rows = [
        _row(
            str(provider.get("display_name") or provider.get("provider_key") or "Provider"),
            " · ".join(
                part
                for part in (
                    str(provider.get("detail") or "").strip(),
                    f"health {provider.get('health_state')}" if provider.get("health_state") else "",
                    f"priority {provider.get('priority')}" if provider.get("priority") not in (None, "") else "",
                )
                if part
            )
            or "Provider binding is visible in the control plane.",
            _humanize(str(provider.get("state") or provider.get("health_state") or "unknown")).title(),
        )
        for provider in providers[:8]
    ]
    lane_rows = [
        _row(
            str(lane.get("lane") or lane.get("profile") or "Lane"),
            " · ".join(
                part
                for part in (
                    str(lane.get("primary_provider_key") or "").strip(),
                    str(lane.get("backend") or "").strip(),
                    "review required" if lane.get("review_required") else "",
                )
                if part
            )
            or "Routing lane is available.",
            _humanize(str(lane.get("primary_state") or "unknown")).title(),
        )
        for lane in lanes[:8]
    ]
    approval_rows = [
        _row(
            str(row.reason or "Approval pending"),
            " · ".join(
                part
                for part in (
                    _humanize(str((row.requested_action_json or {}).get("action") or (row.requested_action_json or {}).get("event_type") or "review")),
                    f"expires {str(row.expires_at or '')[:10]}" if row.expires_at else "",
                )
                if part
            )
            or "Approval is waiting.",
            "Approval",
        )
        for row in approvals
    ]
    approval_history_rows = [
        _row(
            f"{_humanize(getattr(row, 'decision', 'decision')).title()} approval",
            " · ".join(
                part
                for part in (
                    getattr(row, "reason", ""),
                    getattr(row, "created_at", "")[:10] if getattr(row, "created_at", None) else "",
                )
                if str(part or "").strip()
            )
            or "Approval decision is recorded.",
            _humanize(getattr(row, "decision", "decision")).title(),
        )
        for row in approval_history
    ]
    task_rows = [_human_task_row(row, operator_id=operator_id, return_to="/admin/operators") for row in human_tasks]
    returned_task_rows = [
        _row(
            str(getattr(row, "brief", "") or "Returned handoff"),
            " · ".join(
                part
                for part in (
                    getattr(row, "assigned_operator_id", "") or getattr(row, "role_required", ""),
                    getattr(row, "resolution", ""),
                    getattr(row, "updated_at", "")[:10] if getattr(row, "updated_at", None) else "",
                )
                if str(part or "").strip()
            )
            or "Returned handoff is recorded.",
            "Returned",
        )
        for row in returned_human_tasks
    ]
    delivery_rows = [
        _row(
            str(getattr(row, "recipient", "") or getattr(row, "channel", "delivery")).strip() or "Delivery",
            " · ".join(
                part
                for part in (
                    _humanize(getattr(row, "channel", "")),
                    f"attempt {int(getattr(row, 'attempt_count', 0) or 0) + 1}",
                    str(getattr(row, "last_error", "") or "").strip()[:80],
                )
                if str(part or "").strip()
            )
            or "Delivery is pending.",
            "Queued",
        )
        for row in pending_delivery
    ]
    policy_rows = [
        _row("Draft approvals", "enabled" if privacy.get("allow_drafts") else "manual only", "Policy"),
        _row("Action suggestions", "enabled" if privacy.get("allow_action_suggestions") else "disabled", "Policy"),
        _row("Automatic briefs", "enabled" if privacy.get("allow_auto_briefs") else "disabled", "Policy"),
        _row("Retention", _humanize(str(privacy.get("retention_mode") or "not set")).title(), "Policy"),
    ]
    if privacy.get("allow_auto_briefs"):
        policy_rows.append(
            _row(
                "Morning memo schedule",
                " · ".join(
                    part
                    for part in (
                        _humanize(str(morning_memo.get("cadence") or "daily_morning")),
                        f"{morning_memo.get('delivery_time_local') or '08:00'} {morning_memo.get('timezone') or 'UTC'}",
                        str(morning_memo.get("resolved_recipient_email") or "waiting for recipient"),
                    )
                    if str(part or "").strip()
                )
                or "Waiting for a delivery target.",
                "Policy",
            )
        )
    operator_rows = _operator_rows(operators)
    diagnostics_workspace = dict(diagnostics.get("workspace") or {})
    diagnostics_plan = dict(diagnostics.get("plan") or {})
    diagnostics_billing = dict(diagnostics.get("billing") or {})
    diagnostics_commercial = dict(diagnostics.get("commercial") or {})
    diagnostics_entitlements = dict(diagnostics.get("entitlements") or {})
    diagnostics_usage = dict(diagnostics.get("usage") or {})
    diagnostics_readiness = dict(diagnostics.get("readiness") or {})
    diagnostics_provider = dict(diagnostics.get("providers") or {})
    diagnostics_queue = dict(diagnostics.get("queue_health") or {})
    diagnostics_operator = dict(diagnostics.get("operators") or {})
    diagnostics_analytics = dict(diagnostics.get("analytics") or {})
    analytics_counts = dict(diagnostics_analytics.get("counts") or {})
    diagnostics_channels = list(diagnostics.get("selected_channels") or [])
    workspace_rows = [
        _row("Workspace", str(diagnostics_workspace.get("name") or "Executive Workspace"), "Workspace"),
        _row("Mode", _humanize(str(diagnostics_workspace.get("mode") or "personal")).title(), "Workspace"),
        _row("Region", str(diagnostics_workspace.get("region") or "Not set"), "Workspace"),
        _row("Timezone", str(diagnostics_workspace.get("timezone") or "Not set"), "Workspace"),
        _row(
            "Channels",
            ", ".join(str(value) for value in diagnostics_channels) if diagnostics_channels else "Google-first path not connected yet.",
            "Workspace",
        ),
    ]
    entitlement_rows = [
        _row("Workspace plan", str(diagnostics_plan.get("display_name") or "Pilot"), "Plan"),
        _row("Unit of sale", str(diagnostics_plan.get("unit_of_sale") or "workspace"), "Plan"),
        _row("Principal seats", str(diagnostics_entitlements.get("principal_seats") or 0), "Entitlement"),
        _row("Operator seats", str(diagnostics_entitlements.get("operator_seats") or 0), "Entitlement"),
        _row("Seats used", str(diagnostics_operator.get("seats_used") or 0), "Entitlement"),
        _row("Seats remaining", str(diagnostics_operator.get("seats_remaining") or 0), "Entitlement"),
        _row(
            "Messaging channels",
            "enabled" if diagnostics_entitlements.get("messaging_channels_enabled") else "not included",
            "Entitlement",
        ),
        _row("Audit retention", str(diagnostics_entitlements.get("audit_retention") or "standard"), "Entitlement"),
        _row(
            "Feature flags",
            ", ".join(str(value).replace("_", " ") for value in (diagnostics_entitlements.get("feature_flags") or [])[:8]) or "No enabled feature flags",
            "Entitlement",
        ),
    ]
    billing_rows = [
        _row("Billing state", str(diagnostics_billing.get("billing_state") or "unknown"), "Billing"),
        _row("Support tier", str(diagnostics_billing.get("support_tier") or "standard"), "Billing"),
        _row("Renewal owner", _humanize(str(diagnostics_billing.get("renewal_owner_role") or "principal")).title(), "Billing"),
        _row("Contract note", str(diagnostics_billing.get("contract_note") or "Workspace contract posture is not set."), "Billing"),
    ]
    support_rows = [
        _row("Workspace readiness", str(diagnostics_readiness.get("detail") or readiness_label), readiness_state.title()),
        _row("Queue state", str(diagnostics_queue.get("state") or "healthy"), "Queue"),
        _row("Queue detail", str(diagnostics_queue.get("detail") or "Queue posture is stable."), "Queue"),
        _row("SLA breaches", str(diagnostics_queue.get("sla_breaches") or 0), "Queue"),
        _row("Unclaimed handoffs", str(diagnostics_queue.get("unclaimed_handoffs") or 0), "Queue"),
        _row("Pending approvals", str(diagnostics_queue.get("pending_approvals") or 0), "Queue"),
        _row("Waiting on principal", str(diagnostics_queue.get("waiting_on_principal") or 0), "Queue"),
        _row("Retrying delivery", str(diagnostics_queue.get("retrying_delivery") or 0), "Queue"),
        _row("Delivery errors", str(diagnostics_queue.get("delivery_errors") or 0), "Queue"),
        _row("Load score", str(diagnostics_queue.get("load_score") or 0), "Queue"),
        _row("Active operators", str(diagnostics_operator.get("active_count") or 0), "Support"),
        _row("Configured providers", str(diagnostics_provider.get("provider_count") or 0), "Support"),
        _row("Routing lanes", str(diagnostics_provider.get("lane_count") or 0), "Support"),
        _row("Provider risk", str(diagnostics_provider.get("risk_state") or "unknown"), "Support"),
        _row("Fallback lanes", str(diagnostics_provider.get("lanes_with_fallback") or 0), "Support"),
        _row("Queued delivery", str(diagnostics_queue.get("pending_delivery") or 0), "Support"),
        _row("Memo items", str(diagnostics_usage.get("brief_items") or 0), "Usage"),
        _row("Queue items", str(diagnostics_usage.get("queue_items") or 0), "Usage"),
        _row("Commitments", str(diagnostics_usage.get("commitments") or 0), "Usage"),
        _row("People", str(diagnostics_usage.get("people") or 0), "Usage"),
        _row(
            "Workspace diagnostics bundle",
            "Export support-ready workspace bundle",
            "Bundle",
            action_href="/app/api/diagnostics/export",
            action_label="Open bundle",
            action_method="get",
        ),
    ]
    analytics_rows = [
        _row("Draft approvals", str(analytics_counts.get("draft_approved") or 0), "Analytics"),
        _row("Drafts sent", str(analytics_counts.get("draft_sent") or 0), "Analytics"),
        _row("Send follow-ups resolved", str(analytics_counts.get("draft_send_followup_resolved") or 0), "Analytics"),
        _row("Memos opened", str(analytics_counts.get("memo_opened") or 0), "Analytics"),
        _row("Commitments created", str(analytics_counts.get("commitment_created") or 0), "Analytics"),
        _row("Commitments closed", str(analytics_counts.get("commitment_closed") or 0), "Analytics"),
        _row("Handoffs completed", str(analytics_counts.get("handoff_completed") or 0), "Analytics"),
        _row("Memory corrections", str(analytics_counts.get("memory_corrected") or 0), "Analytics"),
        _row("First value event", _humanize(str(diagnostics_analytics.get("first_value_event") or "not_reached")).title(), "Analytics"),
        _row("Time to first value", str(diagnostics_analytics.get("time_to_first_value_seconds") or "pending"), "Analytics"),
    ]
    warning_rows = [
        _row(str(value), "Commercial or support warning from the current workspace posture.", "Warning")
        for value in list(diagnostics_commercial.get("warnings") or [])[:8]
        if str(value).strip()
    ]
    recent_event_rows = [
        _row(
            _humanize(str(event.get("event_type") or "event")).title(),
            " · ".join(
                part
                for part in (
                    str(event.get("created_at") or "")[:19],
                    str(event.get("source_id") or "").strip(),
                )
                if str(part or "").strip()
            )
            or "Recent product event.",
            "Event",
        )
        for event in list(diagnostics_analytics.get("recent_events") or [])[:8]
    ]
    office_queue = dict(office.get("queue_health") or {})
    office_delivery = dict(office.get("delivery") or {})
    office_access = dict(office.get("access") or {})
    office_sync = dict(office.get("sync") or {})
    office_snapshot = {str(key): int(value or 0) for key, value in dict(office.get("snapshot") or {}).items()}
    office_operator_key = str(operator_id or "").strip()
    office_assigned_handoffs = [
        row for row in office_snapshot_state.handoffs
        if office_operator_key and str(getattr(row, "owner", "") or "").strip() == office_operator_key
    ]
    office_claimable_handoffs = [
        row for row in office_snapshot_state.handoffs
        if not office_operator_key or str(getattr(row, "owner", "") or "").strip() != office_operator_key
    ]
    office_lane_rows = [
        _row(
            str(item.get("label") or "Lane"),
            str(item.get("detail") or "Operator lane detail"),
            _humanize(str(item.get("state") or "clear")).title(),
            href=str(item.get("href") or "/admin/office"),
        )
        for item in list(office.get("lanes") or [])
    ]
    office_action_rows = [
        _row(
            str(item.get("label") or "Next action"),
            str(item.get("detail") or "Operator action"),
            "Next",
            href=str(item.get("href") or "/admin/office"),
            action_href=str(item.get("action_href") or ""),
            action_label=str(item.get("action_label") or ""),
            action_value=str(item.get("action_value") or ""),
            action_method=str(item.get("action_method") or ""),
            return_to=str(item.get("return_to") or ""),
            secondary_action_href=str(item.get("secondary_action_href") or ""),
            secondary_action_label=str(item.get("secondary_action_label") or ""),
            secondary_action_value=str(item.get("secondary_action_value") or ""),
            secondary_action_method=str(item.get("secondary_action_method") or ""),
            secondary_return_to=str(item.get("secondary_return_to") or ""),
            tertiary_action_href=str(item.get("tertiary_action_href") or ""),
            tertiary_action_label=str(item.get("tertiary_action_label") or ""),
            tertiary_action_value=str(item.get("tertiary_action_value") or ""),
            tertiary_action_method=str(item.get("tertiary_action_method") or ""),
            tertiary_return_to=str(item.get("tertiary_return_to") or ""),
        )
        for item in list(office.get("next_actions") or [])
    ]
    office_delivery_rows = [
        _row("Active sessions", str(office_access.get("active") or 0), "Access", href="/app/settings/access"),
        _row("Access opens", str(office_access.get("opened") or 0), "Access", href="/app/settings/access"),
        _row("Revoked sessions", str(office_access.get("revoked") or 0), "Access", href="/app/settings/access"),
        _row("Registration emails sent", str(office_delivery.get("registration_sent") or 0), "Delivery", href="/app/settings/invitations"),
        _row("Registration email failures", str(office_delivery.get("registration_failed") or 0), "Delivery", href="/app/settings/support"),
        _row("Digest emails sent", str(office_delivery.get("digest_sent") or 0), "Delivery", href="/app/channel-loop"),
        _row("Digest email failures", str(office_delivery.get("digest_failed") or 0), "Delivery", href="/app/settings/support"),
        _row("Google account", str(office_sync.get("google_account_email") or "Not connected"), "Sync", href="/app/settings/google"),
        _row("Google sync freshness", _humanize(str(office_sync.get("google_sync_freshness_state") or "watch")).title(), "Sync", href="/app/settings/google"),
        _row("Pending sync candidates", str(office_sync.get("pending_commitment_candidates") or 0), "Queue", href="/app/inbox"),
        _row("Sync candidates covered by drafts", str(office_sync.get("covered_signal_candidates") or 0), "Queue", href="/app/inbox"),
    ]
    office_snapshot_rows = [
        _row("Assigned handoffs", str(office_snapshot.get("assigned_handoffs") or 0), "Queue", href="/app/follow-ups"),
        _row("Completed handoffs", str(office_snapshot.get("completed_handoffs") or 0), "Queue", href="/app/follow-ups"),
        _row("Clearable queue items", str(office_snapshot.get("clearable_queue_items") or 0), "Queue", href="/app/briefing"),
        _row("Exception count", str(office_snapshot.get("exception_count") or 0), "Queue", href="/admin/office"),
        _row("Open commitments", str(office_snapshot.get("open_commitments") or 0), "Commitments", href="/app/inbox"),
        _row("Pending drafts", str(office_snapshot.get("pending_drafts") or 0), "Drafts", href="/app/inbox"),
        _row("Open decisions", str(office_snapshot.get("open_decisions") or 0), "Decisions", href="/app/briefing"),
        _row("People in play", str(office_snapshot.get("people_in_play") or 0), "People", href="/app/people"),
        _row("Queue state", str(office_queue.get("state") or "healthy"), "Queue", href="/admin/office"),
        _row("Load score", str(office_queue.get("load_score") or 0), "Queue", href="/admin/office"),
    ]
    office_runtime_rows = [
        _row(
            _humanize(str(item.get("event_type") or "event")).title(),
            " · ".join(
                part
                for part in (
                    str(item.get("created_at") or "")[:19],
                    str(item.get("source_id") or "").strip(),
                )
                if str(part or "").strip()
            )
            or "Recent operator/runtime event.",
            "Event",
        )
        for item in list(office.get("recent_runtime") or [])[:10]
    ]

    mapping: dict[str, dict[str, object]] = {
        "office": {
            "title": "Office",
            "summary": "Claim, pre-clear, and protect the office loop before it turns into principal noise.",
            "cards": [
                {
                    "eyebrow": "Operator lanes",
                    "title": "What the office control surface is carrying right now",
                    "items": office_lane_rows or [_row("No active lanes", "The operator center is currently clear.", "Clear")],
                },
                {
                    "eyebrow": "Next actions",
                    "title": "What the operator should do next",
                    "items": office_action_rows or [_row("No next actions", "The current office loop does not need an operator intervention.", "Clear")],
                },
                {
                    "eyebrow": "Assigned to me",
                    "title": "What already belongs to this operator lane",
                    "items": _handoff_rows(office_assigned_handoffs[:8], operator_id=office_operator_key, return_to="/admin/office")
                    or [_row("No assigned handoffs", "Nothing is currently assigned to this operator lane.", "Clear")],
                },
                {
                    "eyebrow": "Claimable handoffs",
                    "title": "What can be claimed next",
                    "items": _handoff_rows(office_claimable_handoffs[:8], operator_id=office_operator_key, return_to="/admin/office")
                    or [_row("No claimable handoffs", "The current handoff lane is already claimed or clear.", "Clear")],
                },
                {
                    "eyebrow": "Delivery and sync",
                    "title": "Access, delivery, and Google posture",
                    "items": office_delivery_rows,
                },
                {
                    "eyebrow": "Recently completed",
                    "title": "What just moved through the operator lane",
                    "items": _handoff_rows(office_snapshot_state.completed_handoffs[:6], actionable=False)
                    or [_row("No recently completed handoffs", "Completed operator work will appear here after it returns cleanly.", "History")],
                },
                {
                    "eyebrow": "Current load",
                    "title": "What the operator lane is protecting",
                    "items": office_snapshot_rows,
                },
                {
                    "eyebrow": "Recent runtime",
                    "title": "Recent operator and runtime events",
                    "items": office_runtime_rows or [_row("No recent runtime events", "Operator and delivery events will appear here as the office loop runs.", "History")],
                },
            ],
        },
        "policies": {
            "title": "Policies",
            "summary": "Approval posture, review rules, and queue pressure for the current office deployment.",
            "cards": [
                {"eyebrow": "Current rules", "title": "What the workspace allows", "items": policy_rows},
                {"eyebrow": "Pending approvals", "title": "What policy is actively gating", "items": approval_rows or [_row("No pending approvals", "The approval lane is currently clear.", "Clear")]},
                {
                    "eyebrow": "Task pressure",
                    "title": "Where humans are still required",
                    "items": task_rows or [_row("No pending human tasks", "The operator lane is currently clear.", "Clear")],
                },
            ],
        },
        "providers": {
            "title": "Providers",
            "summary": "Provider health, capacity, and routing lanes from the live registry view.",
            "cards": [
                {"eyebrow": "Bindings", "title": "Configured providers", "items": provider_rows or [_row("No provider bindings", "No providers are currently bound for this principal.", "Empty")]},
                {"eyebrow": "Routing", "title": "Lane routing state", "items": lane_rows or [_row("No active lanes", "No provider lanes are currently active.", "Empty")]},
                {
                    "eyebrow": "Readiness",
                    "title": "Deployment posture",
                    "items": [
                        _row("Runtime readiness", readiness_label, readiness_state.title()),
                        _row("Provider risk", str(diagnostics_provider.get("risk_state") or "unknown"), "Support"),
                        _row("Fallback lanes", str(diagnostics_provider.get("lanes_with_fallback") or 0), "Support"),
                        _row("Failover-ready lanes", str(diagnostics_provider.get("failover_ready_lanes") or 0), "Support"),
                    ],
                },
            ],
        },
        "audit-trail": {
            "title": "Audit Trail",
            "summary": "Approvals, outbound work, and deployment readiness visible in one control surface.",
            "cards": [
                {"eyebrow": "Approval receipts", "title": "Recent approval decisions", "items": approval_history_rows or [_row("No recent approval decisions", "No approval receipts have been recorded yet.", "Empty")]},
                {"eyebrow": "Outbound work", "title": "Pending delivery", "items": delivery_rows or [_row("No pending delivery", "The outbound queue is currently clear.", "Clear")]},
                {"eyebrow": "System posture", "title": "Current deployment state", "items": [_row("Readiness", readiness_label, readiness_state.title()), _row("Provider count", str(registry.get("provider_count") or 0), "Runtime")]},
            ],
        },
        "operators": {
            "title": "Team / Operators",
            "summary": "Active operators, their queue pressure, and the items still waiting on humans.",
            "cards": [
                {"eyebrow": "Operator roster", "title": "Active operators", "items": operator_rows or [_row("No active operators", "No active operator profiles are configured for this principal.", "Empty")]},
                {"eyebrow": "Queue load", "title": "Pending human work", "items": task_rows or [_row("No pending human tasks", "The operator queue is clear.", "Clear")]},
                {
                    "eyebrow": "Recently completed",
                    "title": "Returned handoffs",
                    "items": returned_task_rows or [_row("No returned handoffs", "No completed operator handoffs have been recorded yet.", "Clear")],
                },
                {
                    "eyebrow": "Work summary",
                    "title": "Priority counts",
                    "items": [
                        _row(str(key).replace("_", " ").title(), str(value), "Count")
                        for key, value in dict(task_summary.get("counts_json") or {}).items()
                    ]
                    or [_row("No priority summary", "No pending task counts are available.", "Empty")],
                },
            ],
        },
        "api": {
            "title": "Diagnostics",
            "summary": "Plan, readiness, usage, and support posture for the current workspace deployment.",
            "cards": [
                {"eyebrow": "Workspace", "title": "Workspace posture", "items": workspace_rows},
                {"eyebrow": "Plan and entitlements", "title": "Commercial boundary", "items": entitlement_rows + billing_rows},
                {"eyebrow": "Support view", "title": "What support can inspect quickly", "items": support_rows + analytics_rows},
                {"eyebrow": "Warnings", "title": "What needs attention before support is surprised", "items": warning_rows or [_row("No current warnings", "Commercial and support posture are aligned with the current workspace.", "Clear")]},
                {"eyebrow": "Recent product events", "title": "What the office loop is actually doing", "items": recent_event_rows or [_row("No recent product events", "The product event stream is still empty.", "Empty")]},
            ],
        },
    }
    payload = mapping[section]
    stats = [
        {"label": "Providers", "value": str(registry.get("provider_count") or 0)},
        {"label": "Approvals", "value": str(len(approvals))},
        {"label": "Human tasks", "value": str(task_summary.get("total") or len(human_tasks))},
        {"label": "Delivery", "value": str(len(pending_delivery))},
    ]
    if section == "office":
        stats = [
            {"label": "Claims", "value": str(office_queue.get("unclaimed_handoffs") or 0)},
            {"label": "Exceptions", "value": str(office_snapshot.get("exception_count") or 0)},
            {"label": "Clearable", "value": str(office_snapshot.get("clearable_queue_items") or 0)},
            {"label": "Decisions", "value": str(office_snapshot.get("open_decisions") or 0)},
        ]
    return {
        "stats": stats,
        **payload,
    }
