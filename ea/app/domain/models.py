from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from typing import Any


@dataclass(frozen=True)
class RewriteRequest:
    text: str
    principal_id: str = ""
    goal: str = ""


@dataclass(frozen=True)
class TaskExecutionRequest:
    task_key: str
    text: str = ""
    principal_id: str = ""
    goal: str = ""
    input_json: dict[str, Any] = field(default_factory=dict)
    context_refs: tuple[str, ...] = ()


@dataclass(frozen=True)
class Artifact:
    artifact_id: str
    kind: str
    content: str
    execution_session_id: str
    principal_id: str
    mime_type: str = "text/plain"
    preview_text: str = ""
    storage_handle: str = ""
    body_ref: str = ""
    structured_output_json: dict[str, Any] = field(default_factory=dict)
    attachments_json: dict[str, Any] = field(default_factory=dict)


def artifact_preview_text(content: str, *, limit: int = 160) -> str:
    normalized = str(content or "")
    if len(normalized) <= limit:
        return normalized
    return f"{normalized[: max(limit - 3, 0)]}..."


def artifact_storage_handle(artifact_id: str) -> str:
    return f"artifact://{artifact_id}"


def artifact_body_ref(artifact: Artifact) -> str:
    return str(artifact.body_ref or "").strip() or str(artifact.storage_handle or "").strip() or artifact_storage_handle(
        artifact.artifact_id
    )


def normalize_artifact(artifact: Artifact) -> Artifact:
    mime_type = str(artifact.mime_type or "").strip() or "text/plain"
    preview_text = str(artifact.preview_text or "").strip() or artifact_preview_text(artifact.content)
    storage_handle = str(artifact.storage_handle or "").strip() or artifact_storage_handle(artifact.artifact_id)
    body_ref = artifact_body_ref(replace(artifact, storage_handle=storage_handle))
    return replace(
        artifact,
        mime_type=mime_type,
        preview_text=preview_text,
        storage_handle=storage_handle,
        body_ref=body_ref,
        structured_output_json=dict(artifact.structured_output_json or {}),
        attachments_json=dict(artifact.attachments_json or {}),
    )


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
class ExecutionQueueItem:
    queue_id: str
    session_id: str
    step_id: str
    state: str
    lease_owner: str
    lease_expires_at: str | None
    attempt_count: int
    next_attempt_at: str | None
    idempotency_key: str
    last_error: str
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
class CommunicationPolicy:
    policy_id: str
    principal_id: str
    scope: str
    preferred_channel: str
    tone: str
    max_length: int
    quiet_hours_json: dict[str, Any]
    escalation_json: dict[str, Any]
    status: str
    notes: str
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class FollowUpRule:
    rule_id: str
    principal_id: str
    name: str
    trigger_kind: str
    channel_scope: tuple[str, ...]
    delay_minutes: int
    max_attempts: int
    escalation_policy: str
    conditions_json: dict[str, Any]
    action_json: dict[str, Any]
    status: str
    notes: str
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class InterruptionBudget:
    budget_id: str
    principal_id: str
    scope: str
    window_kind: str
    budget_minutes: int
    used_minutes: int
    reset_at: str | None
    quiet_hours_json: dict[str, Any]
    status: str
    notes: str
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
class ToolInvocationRequest:
    session_id: str
    step_id: str
    tool_name: str
    action_kind: str
    payload_json: dict[str, Any]
    context_json: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ToolInvocationResult:
    tool_name: str
    action_kind: str
    target_ref: str
    output_json: dict[str, Any]
    receipt_json: dict[str, Any]
    artifacts: tuple[Artifact, ...] = ()
    model_name: str = "none"
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0


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
class SkillContract:
    skill_key: str
    task_key: str
    name: str
    description: str
    deliverable_type: str
    default_risk_class: str
    default_approval_class: str
    workflow_template: str
    allowed_tools: tuple[str, ...]
    evidence_requirements: tuple[str, ...]
    memory_write_policy: str
    memory_reads: tuple[str, ...]
    memory_writes: tuple[str, ...]
    tags: tuple[str, ...]
    input_schema_json: dict[str, Any]
    output_schema_json: dict[str, Any]
    authority_profile_json: dict[str, Any]
    model_policy_json: dict[str, Any]
    provider_hints_json: dict[str, Any]
    tool_policy_json: dict[str, Any]
    human_policy_json: dict[str, Any]
    evaluation_cases_json: tuple[dict[str, Any], ...]
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
    owner: str = "system"
    authority_class: str = "observe"
    review_class: str = "none"
    failure_strategy: str = "fail"
    timeout_budget_seconds: int = 0
    max_attempts: int = 1
    retry_backoff_seconds: int = 0
    depends_on: tuple[str, ...] = ()
    input_keys: tuple[str, ...] = ()
    output_keys: tuple[str, ...] = ()
    task_type: str = ""
    role_required: str = ""
    brief: str = ""
    priority: str = ""
    sla_minutes: int = 0
    auto_assign_if_unique: bool = False
    desired_output_json: dict[str, Any] = field(default_factory=dict)
    authority_required: str = ""
    why_human: str = ""
    quality_rubric_json: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PlanSpec:
    plan_id: str
    task_key: str
    principal_id: str
    created_at: str
    steps: tuple[PlanStepSpec, ...]


class PlanValidationError(ValueError):
    pass


def validate_plan_spec(plan: PlanSpec) -> None:
    steps = tuple(plan.steps or ())
    if not steps:
        return

    lookup: dict[str, PlanStepSpec] = {}
    for step in steps:
        step_key = str(step.step_key or "").strip()
        if not step_key:
            raise PlanValidationError("plan_step_key_required")
        if step_key in lookup:
            raise PlanValidationError(f"duplicate_step_key:{step_key}")
        lookup[step_key] = step

    for step in steps:
        step_key = str(step.step_key or "").strip()
        seen_dependency_keys: set[str] = set()
        for raw_dependency_key in tuple(step.depends_on or ()):
            dependency_key = str(raw_dependency_key or "").strip()
            if not dependency_key:
                raise PlanValidationError(f"empty_dependency_key:{step_key}")
            if dependency_key == step_key:
                raise PlanValidationError(f"self_dependency:{step_key}")
            if dependency_key in seen_dependency_keys:
                raise PlanValidationError(f"duplicate_dependency_key:{step_key}:{dependency_key}")
            seen_dependency_keys.add(dependency_key)
            if dependency_key not in lookup:
                raise PlanValidationError(f"unknown_dependency:{step_key}:{dependency_key}")

    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(step_key: str) -> None:
        if step_key in visited:
            return
        if step_key in visiting:
            raise PlanValidationError(f"dependency_cycle:{step_key}")
        visiting.add(step_key)
        for dependency_key in tuple(lookup[step_key].depends_on or ()):
            visit(str(dependency_key))
        visiting.remove(step_key)
        visited.add(step_key)

    for step_key in tuple(lookup):
        visit(step_key)


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
class HumanTask:
    human_task_id: str
    session_id: str
    step_id: str | None
    principal_id: str
    task_type: str
    role_required: str
    brief: str
    authority_required: str
    why_human: str
    quality_rubric_json: dict[str, Any]
    input_json: dict[str, Any]
    desired_output_json: dict[str, Any]
    priority: str
    sla_due_at: str | None
    status: str
    assignment_state: str
    assigned_operator_id: str
    assignment_source: str
    assigned_at: str | None
    assigned_by_actor_id: str
    resolution: str
    created_at: str
    updated_at: str
    resume_session_on_return: bool = False
    returned_payload_json: dict[str, Any] = field(default_factory=dict)
    provenance_json: dict[str, Any] = field(default_factory=dict)
    routing_hints_json: dict[str, Any] = field(default_factory=dict)
    last_transition_event_name: str = ""
    last_transition_at: str | None = None
    last_transition_assignment_state: str = ""
    last_transition_operator_id: str = ""
    last_transition_assignment_source: str = ""
    last_transition_by_actor_id: str = ""


@dataclass(frozen=True)
class OperatorProfile:
    operator_id: str
    principal_id: str
    display_name: str
    roles: tuple[str, ...]
    skill_tags: tuple[str, ...]
    trust_tier: str
    status: str
    notes: str
    created_at: str
    updated_at: str


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
