from __future__ import annotations

from typing import Any

from app.container import AppContainer


def _row(title: str, detail: str, tag: str) -> dict[str, str]:
    return {"title": title, "detail": detail, "tag": tag}


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
    approvals = container.orchestrator.list_pending_approvals_for_principal(principal_id=principal_id, limit=8)
    approval_history = container.orchestrator.list_approval_history_for_principal(principal_id=principal_id, limit=8)
    human_tasks = container.orchestrator.list_human_tasks(principal_id=principal_id, status="pending", limit=8)
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
        )
        for row in human_tasks
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
                {"eyebrow": "Readiness", "title": "Deployment posture", "items": [_row("Runtime readiness", readiness_label, readiness_state.title())]},
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
            "title": "API",
            "summary": "Product-facing and runtime-facing endpoints that are active in this deployment.",
            "cards": [
                {"eyebrow": "Product API", "title": "Workspace objects", "items": [_row("/app/api/brief", "Morning memo projection", "Route"), _row("/app/api/queue", "Decision queue projection", "Route"), _row("/app/api/commitments", "Commitment ledger projection", "Route")]},
                {"eyebrow": "Runtime API", "title": "Control plane", "items": [_row("/v1/providers/states", "Provider health and bindings", "Route"), _row("/v1/human/tasks", "Human task runtime", "Route"), _row("/v1/delivery/outbox/pending", "Pending delivery queue", "Route")]},
                {"eyebrow": "Readiness", "title": "Deployment state", "items": [_row("Runtime readiness", readiness_label, readiness_state.title())]},
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
