from __future__ import annotations

from dataclasses import replace

from app.product.commercial import workspace_plan_for_mode
from app.product.models import RuleItem


def rule_items_from_workspace(status: dict[str, object], diagnostics: dict[str, object]) -> tuple[RuleItem, ...]:
    workspace = dict(status.get("workspace") or {})
    privacy = dict(status.get("privacy") or {})
    selected_channels = [str(value) for value in (status.get("selected_channels") or []) if str(value).strip()]
    plan = workspace_plan_for_mode(str(workspace.get("mode") or "personal"))
    operators = dict(diagnostics.get("operators") or {})
    commercial = dict(diagnostics.get("commercial") or {})
    billing = dict(diagnostics.get("billing") or {})
    seat_limit = int(plan.entitlements.operator_seats or 0)
    seats_used = int(operators.get("seats_used") or 0)
    selected_messaging = [value for value in selected_channels if value in {"telegram", "whatsapp"}]
    return (
        RuleItem(
            id="rule:google_first",
            label="Google-first activation",
            scope="activation",
            status="active",
            summary="Google remains the first required connection before optional channels and advanced automation.",
            current_value="google",
            impact="Messaging stays deferred until the first memo, first draft review, and first commitment loop are useful.",
        ),
        RuleItem(
            id="rule:draft_approval",
            label="Draft approval",
            scope="delivery",
            status="active",
            summary="Outbound drafts remain reviewable before send so the office loop stays auditable.",
            current_value="principal_review",
            impact="Drafts require an explicit approval or rejection path before they leave the workspace.",
            requires_approval=True,
        ),
        RuleItem(
            id="rule:messaging_scope",
            label="Messaging scope",
            scope="channels",
            status="active" if plan.entitlements.messaging_channels_enabled else "upgrade_required",
            summary="Telegram and WhatsApp widen coverage only when the plan and workflow can support them.",
            current_value="enabled" if selected_messaging and plan.entitlements.messaging_channels_enabled else ("requested" if selected_messaging else "deferred"),
            impact="Upgrade required for messaging channels." if selected_messaging and not plan.entitlements.messaging_channels_enabled else "Google remains the core operating channel.",
        ),
        RuleItem(
            id="rule:memory_retention",
            label="Memory retention",
            scope="memory",
            status="active",
            summary="Retention controls how long trust receipts, audit signals, and workspace memory stay available.",
            current_value=str(privacy.get("retention_mode") or plan.entitlements.audit_retention or "30d"),
            impact="Longer retention improves diagnostics and historical auditability.",
        ),
        RuleItem(
            id="rule:operator_seats",
            label="Operator seat limit",
            scope="commercial",
            status="active" if seats_used <= seat_limit else "over_limit",
            summary="Operator seats control how much handoff work the workspace can legitimately run in one plan.",
            current_value=f"{seats_used}/{seat_limit}",
            impact="Add seats or upgrade the plan when the operator lane outgrows the current boundary.",
            requires_approval=True,
        ),
        RuleItem(
            id="rule:audit_posture",
            label="Audit and support bundle",
            scope="support",
            status="active",
            summary="Support exports include approvals, human work, provider posture, and pending delivery to explain what happened.",
            current_value=str(billing.get("support_tier") or "standard"),
            impact="Commercial warnings surface when selected channels and plan scope drift apart." if commercial.get("warnings") else "Workspace support posture is aligned with the active plan.",
        ),
    )


def simulate_rule(rule: RuleItem, *, proposed_value: str, diagnostics: dict[str, object]) -> RuleItem:
    proposed = str(proposed_value or "").strip() or rule.current_value
    entitlements = dict(diagnostics.get("entitlements") or {})
    operators = dict(diagnostics.get("operators") or {})
    effect = f"Would change {rule.label.lower()} to {proposed}."
    if rule.id == "rule:messaging_scope":
        if proposed.lower() in {"enabled", "telegram", "whatsapp"} and not entitlements.get("messaging_channels_enabled"):
            effect = "Current plan blocks Telegram and WhatsApp. Upgrade is required before messaging can be enabled."
        else:
            effect = "Messaging would remain deferred until after the Google-first proof loop unless explicitly enabled in the workspace."
    elif rule.id == "rule:draft_approval":
        if proposed.lower() in {"off", "disabled", "auto_send"}:
            effect = "Disabling draft approval would allow outbound actions to leave the review queue immediately."
        else:
            effect = "Approval remains a visible gate for sensitive outbound work."
    elif rule.id == "rule:operator_seats":
        try:
            proposed_seats = int(float(proposed))
        except ValueError:
            proposed_seats = int(entitlements.get("operator_seats") or 0)
        seats_used = int(operators.get("seats_used") or 0)
        if proposed_seats < seats_used:
            effect = "The proposed seat count is below current usage and would force operator reassignment."
        else:
            effect = "The proposed seat count can absorb the current operator lane."
    elif rule.id == "rule:memory_retention":
        effect = "Retention changes would alter how long trust receipts and support traces remain exportable."
    return replace(rule, current_value=proposed, simulated_effect=effect)
