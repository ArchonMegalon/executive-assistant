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
    ),
    "executive_ops": WorkspacePlan(
        plan_key="executive",
        display_name="Executive Ops",
        unit_of_sale="workspace",
        entitlements=PlanEntitlements(
            principal_seats=1,
            operator_seats=3,
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
    ),
}


def workspace_plan_for_mode(workspace_mode: str) -> WorkspacePlan:
    normalized = str(workspace_mode or "").strip().lower() or "personal"
    if normalized == "shared":
        normalized = "team"
    return _PLANS.get(normalized, _PLANS["personal"])
