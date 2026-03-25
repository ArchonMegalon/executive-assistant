from __future__ import annotations

from typing import Any

from app.container import AppContainer
from app.product.service import build_product_service


def _row(
    title: str,
    detail: str,
    tag: str,
    *,
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


def build_admin_section_payload(section: str, *, container: AppContainer, principal_id: str) -> dict[str, object]:
    readiness_ok, readiness_label = container.readiness.check()
    readiness_state = "ready" if readiness_ok else "attention"
    status = container.onboarding.status(principal_id=principal_id)
    privacy = dict(status.get("privacy") or {})
    diagnostics = build_product_service(container).workspace_diagnostics(principal_id=principal_id)
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
    task_rows = [
        _row(
            str(getattr(row, "brief", "") or "Human task"),
            " · ".join(
                part
                for part in (
                    _humanize(getattr(row, "role_required", "")),
                    f"priority {getattr(row, 'priority', '')}",
                    f"due {str(getattr(row, 'sla_due_at', '') or '')[:10]}" if getattr(row, "sla_due_at", None) else "",
                )
                if str(part or "").strip()
            )
            or "Human task remains open.",
            "Task",
            action_href=f"/app/actions/handoffs/human_task:{getattr(row, 'human_task_id', '')}/assign",
            action_label="Claim",
            action_value="assign",
            return_to="/admin/operators",
            secondary_action_href=f"/app/actions/handoffs/human_task:{getattr(row, 'human_task_id', '')}/complete",
            secondary_action_label="Complete",
            secondary_action_value="completed",
            secondary_return_to="/admin/operators",
        )
        for row in human_tasks
    ]
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

    mapping: dict[str, dict[str, object]] = {
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
    return {
        "stats": [
            {"label": "Providers", "value": str(registry.get("provider_count") or 0)},
            {"label": "Approvals", "value": str(len(approvals))},
            {"label": "Human tasks", "value": str(task_summary.get("total") or len(human_tasks))},
            {"label": "Delivery", "value": str(len(pending_delivery))},
        ],
        **payload,
    }
