from __future__ import annotations

from dataclasses import dataclass, field
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
class MemoryCandidate:
    candidate_id: str
    principal_id: str
    category: str
    summary: str
    fact_json: dict[str, Any]
    source_session_id: str
    source_event_id: str
    source_step_id: str
    confidence: float
    sensitivity: str
    status: str
    created_at: str
    reviewed_at: str | None = None
    reviewer: str = ""
    promoted_item_id: str = ""


@dataclass(frozen=True)
class MemoryItem:
    item_id: str
    principal_id: str
    category: str
    summary: str
    fact_json: dict[str, Any]
    provenance_json: dict[str, Any]
    confidence: float
    sensitivity: str
    sharing_policy: str
    last_verified_at: str | None
    reviewer: str
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class Entity:
    entity_id: str
    principal_id: str
    entity_type: str
    canonical_name: str
    attributes_json: dict[str, Any]
    confidence: float
    status: str
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class RelationshipEdge:
    relationship_id: str
    principal_id: str
    from_entity_id: str
    to_entity_id: str
    relationship_type: str
    attributes_json: dict[str, Any]
    confidence: float
    valid_from: str | None
    valid_to: str | None
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class Commitment:
    commitment_id: str
    principal_id: str
    title: str
    details: str
    status: str
    priority: str
    due_at: str | None
    source_json: dict[str, Any]
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class AuthorityBinding:
    binding_id: str
    principal_id: str
    subject_ref: str
    action_scope: str
    approval_level: str
    channel_scope: tuple[str, ...]
    policy_json: dict[str, Any]
    status: str
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class DeliveryPreference:
    preference_id: str
    principal_id: str
    channel: str
    recipient_ref: str
    cadence: str
    quiet_hours_json: dict[str, Any]
    format_json: dict[str, Any]
    status: str
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class FollowUp:
    follow_up_id: str
    principal_id: str
    stakeholder_ref: str
    topic: str
    status: str
    due_at: str | None
    channel_hint: str
    notes: str
    source_json: dict[str, Any]
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class DeadlineWindow:
    window_id: str
    principal_id: str
    title: str
    start_at: str | None
    end_at: str | None
    status: str
    priority: str
    notes: str
    source_json: dict[str, Any]
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class Stakeholder:
    stakeholder_id: str
    principal_id: str
    display_name: str
    channel_ref: str
    authority_level: str
    importance: str
    response_cadence: str
    tone_pref: str
    sensitivity: str
    escalation_policy: str
    open_loops_json: dict[str, Any]
    friction_points_json: dict[str, Any]
    last_interaction_at: str | None
    status: str
    notes: str
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class DecisionWindow:
    decision_window_id: str
    principal_id: str
    title: str
    context: str
    opens_at: str | None
    closes_at: str | None
    urgency: str
    authority_required: str
    status: str
    notes: str
    source_json: dict[str, Any]
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class ToolDefinition:
    tool_name: str
    version: str
    input_schema_json: dict[str, Any]
    output_schema_json: dict[str, Any]
    policy_json: dict[str, Any]
    allowed_channels: tuple[str, ...]
    approval_default: str
    enabled: bool
    updated_at: str


@dataclass(frozen=True)
class ConnectorBinding:
    binding_id: str
    principal_id: str
    connector_name: str
    external_account_ref: str
    scope_json: dict[str, Any]
    auth_metadata_json: dict[str, Any]
    status: str
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class TaskContract:
    task_key: str
    deliverable_type: str
    default_risk_class: str
    default_approval_class: str
    allowed_tools: tuple[str, ...]
    evidence_requirements: tuple[str, ...]
    memory_write_policy: str
    budget_policy_json: dict[str, Any]
    updated_at: str


@dataclass(frozen=True)
class PlanStepSpec:
    step_key: str
    step_kind: str
    tool_name: str
    evidence_required: tuple[str, ...]
    approval_required: bool
    reversible: bool
    expected_artifact: str
    fallback: str


@dataclass(frozen=True)
class PlanSpec:
    plan_id: str
    task_key: str
    principal_id: str
    created_at: str
    steps: tuple[PlanStepSpec, ...]


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
    source_id: str = ""
    external_id: str = ""
    dedupe_key: str = ""
    auth_context_json: dict[str, Any] = field(default_factory=dict)
    raw_payload_uri: str = ""


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
    idempotency_key: str = ""
    attempt_count: int = 0
    next_attempt_at: str | None = None
    last_error: str = ""
    receipt_json: dict[str, Any] = field(default_factory=dict)
    dead_lettered_at: str | None = None


def now_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
