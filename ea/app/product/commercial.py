from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class PlanEntitlements:
    principal_seats: int
    operator_seats: int
    messaging_channels_enabled: bool
    audit_retention: str
    feature_flags: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class WorkspacePlan:
    plan_key: str
    display_name: str
    unit_of_sale: str
    entitlements: PlanEntitlements
    support_tier: str
    billing_state: str
    renewal_owner_role: str
    contract_note: str


_PLANS = {
    "personal": WorkspacePlan(
        plan_key="pilot",
        display_name="Pilot",
        unit_of_sale="workspace",
        entitlements=PlanEntitlements(
            principal_seats=1,
            operator_seats=1,
            messaging_channels_enabled=False,
            audit_retention="30d",
            feature_flags=("morning_memo", "decision_queue", "commitment_ledger", "draft_queue"),
        ),
        support_tier="guided",
        billing_state="trial",
        renewal_owner_role="principal",
        contract_note="Google-first pilot with one executive and one operator.",
    ),
    "team": WorkspacePlan(
        plan_key="core",
        display_name="Core",
        unit_of_sale="workspace",
        entitlements=PlanEntitlements(
            principal_seats=1,
            operator_seats=2,
            messaging_channels_enabled=True,
            audit_retention="90d",
            feature_flags=("morning_memo", "decision_queue", "commitment_ledger", "draft_queue", "people_graph", "handoffs"),
        ),
        support_tier="standard",
        billing_state="active",
        renewal_owner_role="office_admin",
        contract_note="Shared office deployment with collaborative operator coverage.",
    ),
    "executive_ops": WorkspacePlan(
        plan_key="executive",
        display_name="Executive Ops",
        unit_of_sale="workspace",
        entitlements=PlanEntitlements(
            principal_seats=1,
            operator_seats=1000,
            messaging_channels_enabled=True,
            audit_retention="180d",
            feature_flags=(
                "morning_memo",
                "decision_queue",
                "commitment_ledger",
                "draft_queue",
                "people_graph",
                "handoffs",
                "admin_audit",
            ),
        ),
        support_tier="priority",
        billing_state="active",
        renewal_owner_role="operator_lead",
        contract_note="Managed executive-office deployment with priority support and audit depth.",
    ),
}


def workspace_plan_for_mode(workspace_mode: str) -> WorkspacePlan:
    normalized = str(workspace_mode or "").strip().lower() or "personal"
    if normalized == "shared":
        normalized = "team"
    return _PLANS.get(normalized, _PLANS["personal"])
