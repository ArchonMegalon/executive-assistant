from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any


@dataclass(frozen=True)
class RewriteRequest:
    text: str


@dataclass(frozen=True)
class Artifact:
    artifact_id: str
    kind: str
    content: str
    execution_session_id: str


@dataclass(frozen=True)
class IntentSpecV3:
    principal_id: str
    goal: str
    task_type: str
    deliverable_type: str
    risk_class: str
    approval_class: str
    budget_class: str
    stakeholders: tuple[str, ...] = ()
    evidence_requirements: tuple[str, ...] = ()
    allowed_tools: tuple[str, ...] = ()
    desired_artifact: str = ""
    time_horizon: str = "immediate"
    interruption_budget: str = "low"
    memory_write_policy: str = "reviewed_only"


@dataclass(frozen=True)
class ExecutionSession:
    session_id: str
    intent: IntentSpecV3
    status: str
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class ExecutionEvent:
    event_id: str
    session_id: str
    name: str
    payload: dict[str, Any]
    created_at: str


@dataclass(frozen=True)
class ExecutionStep:
    step_id: str
    session_id: str
    parent_step_id: str | None
    step_kind: str
    state: str
    attempt_count: int
    input_json: dict[str, Any]
    output_json: dict[str, Any]
    error_json: dict[str, Any]
    correlation_id: str
    causation_id: str
    actor_type: str
    actor_id: str
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class ToolReceipt:
    receipt_id: str
    session_id: str
    step_id: str
    tool_name: str
    action_kind: str
    target_ref: str
    receipt_json: dict[str, Any]
    created_at: str


@dataclass(frozen=True)
class RunCost:
    cost_id: str
    session_id: str
    model_name: str
    tokens_in: int
    tokens_out: int
    cost_usd: float
    created_at: str


@dataclass(frozen=True)
class ApprovalRequest:
    approval_id: str
    session_id: str
    step_id: str
    reason: str
    requested_action_json: dict[str, Any]
    status: str
    expires_at: str | None
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class ApprovalDecision:
    decision_id: str
    approval_id: str
    session_id: str
    step_id: str
    decision: str
    decided_by: str
    reason: str
    created_at: str


@dataclass(frozen=True)
class PolicyDecision:
    allow: bool
    requires_approval: bool
    reason: str
    retention_policy: str
    memory_write_allowed: bool


@dataclass(frozen=True)
class PolicyDecisionRecord:
    decision_id: str
    session_id: str
    allow: bool
    requires_approval: bool
    reason: str
    retention_policy: str
    memory_write_allowed: bool
    created_at: str


@dataclass(frozen=True)
class ObservationEvent:
    observation_id: str
    principal_id: str
    channel: str
    event_type: str
    payload: dict[str, Any]
    created_at: str


@dataclass(frozen=True)
class DeliveryOutboxItem:
    delivery_id: str
    channel: str
    recipient: str
    content: str
    status: str
    metadata: dict[str, Any]
    created_at: str
    sent_at: str | None


def now_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
