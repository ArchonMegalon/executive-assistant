from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.api.dependencies import RequestContext, get_container, get_request_context, resolve_principal_id
from app.container import AppContainer

router = APIRouter(tags=["memory"])


class CommunicationPolicyIn(BaseModel):
    principal_id: str | None = Field(default=None, min_length=1, max_length=200)
    scope: str = Field(min_length=1, max_length=200)
    preferred_channel: str = Field(default="", max_length=120)
    tone: str = Field(default="neutral", max_length=120)
    max_length: int = Field(default=1200, ge=1, le=20000)
    quiet_hours_json: dict[str, object] = Field(default_factory=dict)
    escalation_json: dict[str, object] = Field(default_factory=dict)
    status: str = Field(default="active", max_length=80)
    notes: str = Field(default="", max_length=5000)
    policy_id: str | None = Field(default=None, max_length=200)


class CommunicationPolicyOut(BaseModel):
    policy_id: str
    principal_id: str
    scope: str
    preferred_channel: str
    tone: str
    max_length: int
    quiet_hours_json: dict[str, object]
    escalation_json: dict[str, object]
    status: str
    notes: str
    created_at: str
    updated_at: str


class StakeholderIn(BaseModel):
    principal_id: str | None = Field(default=None, min_length=1, max_length=200)
    display_name: str = Field(min_length=1, max_length=300)
    channel_ref: str = Field(default="", max_length=200)
    authority_level: str = Field(default="manager", max_length=100)
    importance: str = Field(default="medium", max_length=100)
    response_cadence: str = Field(default="normal", max_length=100)
    tone_pref: str = Field(default="neutral", max_length=100)
    sensitivity: str = Field(default="internal", max_length=100)
    escalation_policy: str = Field(default="none", max_length=200)
    open_loops_json: dict[str, object] = Field(default_factory=dict)
    friction_points_json: dict[str, object] = Field(default_factory=dict)
    last_interaction_at: str | None = Field(default=None, max_length=80)
    status: str = Field(default="active", max_length=80)
    notes: str = Field(default="", max_length=5000)
    stakeholder_id: str | None = Field(default=None, max_length=200)


class StakeholderOut(BaseModel):
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
    open_loops_json: dict[str, object]
    friction_points_json: dict[str, object]
    last_interaction_at: str | None
    status: str
    notes: str
    created_at: str
    updated_at: str


class AuthorityBindingIn(BaseModel):
    principal_id: str | None = Field(default=None, min_length=1, max_length=200)
    subject_ref: str = Field(min_length=1, max_length=200)
    action_scope: str = Field(min_length=1, max_length=200)
    approval_level: str = Field(default="manager", max_length=100)
    channel_scope: list[str] = Field(default_factory=list)
    policy_json: dict[str, object] = Field(default_factory=dict)
    status: str = Field(default="active", max_length=80)
    binding_id: str | None = Field(default=None, max_length=200)


class AuthorityBindingOut(BaseModel):
    binding_id: str
    principal_id: str
    subject_ref: str
    action_scope: str
    approval_level: str
    channel_scope: list[str]
    policy_json: dict[str, object]
    status: str
    created_at: str
    updated_at: str


class DeliveryPreferenceIn(BaseModel):
    principal_id: str | None = Field(default=None, min_length=1, max_length=200)
    channel: str = Field(min_length=1, max_length=120)
    recipient_ref: str = Field(min_length=1, max_length=200)
    cadence: str = Field(default="normal", max_length=100)
    quiet_hours_json: dict[str, object] = Field(default_factory=dict)
    format_json: dict[str, object] = Field(default_factory=dict)
    status: str = Field(default="active", max_length=80)
    preference_id: str | None = Field(default=None, max_length=200)


class DeliveryPreferenceOut(BaseModel):
    preference_id: str
    principal_id: str
    channel: str
    recipient_ref: str
    cadence: str
    quiet_hours_json: dict[str, object]
    format_json: dict[str, object]
    status: str
    created_at: str
    updated_at: str


class InterruptionBudgetIn(BaseModel):
    principal_id: str | None = Field(default=None, min_length=1, max_length=200)
    scope: str = Field(min_length=1, max_length=200)
    window_kind: str = Field(default="daily", max_length=80)
    budget_minutes: int = Field(default=120, ge=0, le=10080)
    used_minutes: int = Field(default=0, ge=0, le=10080)
    reset_at: str | None = Field(default=None, max_length=80)
    quiet_hours_json: dict[str, object] = Field(default_factory=dict)
    status: str = Field(default="active", max_length=80)
    notes: str = Field(default="", max_length=5000)
    budget_id: str | None = Field(default=None, max_length=200)


class InterruptionBudgetOut(BaseModel):
    budget_id: str
    principal_id: str
    scope: str
    window_kind: str
    budget_minutes: int
    used_minutes: int
    reset_at: str | None
    quiet_hours_json: dict[str, object]
    status: str
    notes: str
    created_at: str
    updated_at: str


def _communication_policy_out(row) -> CommunicationPolicyOut:  # type: ignore[no-untyped-def]
    return CommunicationPolicyOut(
        policy_id=row.policy_id,
        principal_id=row.principal_id,
        scope=row.scope,
        preferred_channel=row.preferred_channel,
        tone=row.tone,
        max_length=row.max_length,
        quiet_hours_json=row.quiet_hours_json,
        escalation_json=row.escalation_json,
        status=row.status,
        notes=row.notes,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _stakeholder_out(row) -> StakeholderOut:  # type: ignore[no-untyped-def]
    return StakeholderOut(
        stakeholder_id=row.stakeholder_id,
        principal_id=row.principal_id,
        display_name=row.display_name,
        channel_ref=row.channel_ref,
        authority_level=row.authority_level,
        importance=row.importance,
        response_cadence=row.response_cadence,
        tone_pref=row.tone_pref,
        sensitivity=row.sensitivity,
        escalation_policy=row.escalation_policy,
        open_loops_json=row.open_loops_json,
        friction_points_json=row.friction_points_json,
        last_interaction_at=row.last_interaction_at,
        status=row.status,
        notes=row.notes,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _authority_binding_out(row) -> AuthorityBindingOut:  # type: ignore[no-untyped-def]
    return AuthorityBindingOut(
        binding_id=row.binding_id,
        principal_id=row.principal_id,
        subject_ref=row.subject_ref,
        action_scope=row.action_scope,
        approval_level=row.approval_level,
        channel_scope=list(row.channel_scope),
        policy_json=row.policy_json,
        status=row.status,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _delivery_preference_out(row) -> DeliveryPreferenceOut:  # type: ignore[no-untyped-def]
    return DeliveryPreferenceOut(
        preference_id=row.preference_id,
        principal_id=row.principal_id,
        channel=row.channel,
        recipient_ref=row.recipient_ref,
        cadence=row.cadence,
        quiet_hours_json=row.quiet_hours_json,
        format_json=row.format_json,
        status=row.status,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _interruption_budget_out(row) -> InterruptionBudgetOut:  # type: ignore[no-untyped-def]
    return InterruptionBudgetOut(
        budget_id=row.budget_id,
        principal_id=row.principal_id,
        scope=row.scope,
        window_kind=row.window_kind,
        budget_minutes=row.budget_minutes,
        used_minutes=row.used_minutes,
        reset_at=row.reset_at,
        quiet_hours_json=row.quiet_hours_json,
        status=row.status,
        notes=row.notes,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


@router.post("/communication-policies")
def upsert_memory_communication_policy(
    body: CommunicationPolicyIn,
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> CommunicationPolicyOut:
    row = container.memory_runtime.upsert_communication_policy(
        principal_id=resolve_principal_id(body.principal_id, context),
        scope=body.scope,
        preferred_channel=body.preferred_channel,
        tone=body.tone,
        max_length=body.max_length,
        quiet_hours_json=body.quiet_hours_json,
        escalation_json=body.escalation_json,
        status=body.status,
        notes=body.notes,
        policy_id=body.policy_id,
    )
    return _communication_policy_out(row)


@router.get("/communication-policies")
def list_memory_communication_policies(
    principal_id: str | None = Query(default=None, min_length=1, max_length=200),
    limit: int = Query(default=100, ge=1, le=500),
    status: str | None = Query(default=None),
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> list[CommunicationPolicyOut]:
    rows = container.memory_runtime.list_communication_policies(
        principal_id=resolve_principal_id(principal_id, context),
        limit=limit,
        status=status,
    )
    return [_communication_policy_out(row) for row in rows]


@router.get("/communication-policies/{policy_id}")
def get_memory_communication_policy(
    policy_id: str,
    principal_id: str | None = Query(default=None, min_length=1, max_length=200),
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> CommunicationPolicyOut:
    row = container.memory_runtime.get_communication_policy(
        policy_id,
        principal_id=resolve_principal_id(principal_id, context),
    )
    if not row:
        raise HTTPException(status_code=404, detail="communication_policy_not_found")
    return _communication_policy_out(row)


@router.post("/stakeholders")
def upsert_memory_stakeholder(
    body: StakeholderIn,
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> StakeholderOut:
    row = container.memory_runtime.upsert_stakeholder(
        principal_id=resolve_principal_id(body.principal_id, context),
        display_name=body.display_name,
        channel_ref=body.channel_ref,
        authority_level=body.authority_level,
        importance=body.importance,
        response_cadence=body.response_cadence,
        tone_pref=body.tone_pref,
        sensitivity=body.sensitivity,
        escalation_policy=body.escalation_policy,
        open_loops_json=body.open_loops_json,
        friction_points_json=body.friction_points_json,
        last_interaction_at=body.last_interaction_at,
        status=body.status,
        notes=body.notes,
        stakeholder_id=body.stakeholder_id,
    )
    return _stakeholder_out(row)


@router.get("/stakeholders")
def list_memory_stakeholders(
    principal_id: str | None = Query(default=None, min_length=1, max_length=200),
    limit: int = Query(default=100, ge=1, le=500),
    status: str | None = Query(default=None),
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> list[StakeholderOut]:
    rows = container.memory_runtime.list_stakeholders(
        principal_id=resolve_principal_id(principal_id, context),
        limit=limit,
        status=status,
    )
    return [_stakeholder_out(row) for row in rows]


@router.get("/stakeholders/{stakeholder_id}")
def get_memory_stakeholder(
    stakeholder_id: str,
    principal_id: str | None = Query(default=None, min_length=1, max_length=200),
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> StakeholderOut:
    row = container.memory_runtime.get_stakeholder(
        stakeholder_id,
        principal_id=resolve_principal_id(principal_id, context),
    )
    if not row:
        raise HTTPException(status_code=404, detail="stakeholder_not_found")
    return _stakeholder_out(row)


@router.post("/authority-bindings")
def upsert_memory_authority_binding(
    body: AuthorityBindingIn,
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> AuthorityBindingOut:
    row = container.memory_runtime.upsert_authority_binding(
        principal_id=resolve_principal_id(body.principal_id, context),
        subject_ref=body.subject_ref,
        action_scope=body.action_scope,
        approval_level=body.approval_level,
        channel_scope=tuple(body.channel_scope),
        policy_json=body.policy_json,
        status=body.status,
        binding_id=body.binding_id,
    )
    return _authority_binding_out(row)


@router.get("/authority-bindings")
def list_memory_authority_bindings(
    principal_id: str | None = Query(default=None, min_length=1, max_length=200),
    limit: int = Query(default=100, ge=1, le=500),
    status: str | None = Query(default=None),
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> list[AuthorityBindingOut]:
    rows = container.memory_runtime.list_authority_bindings(
        principal_id=resolve_principal_id(principal_id, context),
        limit=limit,
        status=status,
    )
    return [_authority_binding_out(row) for row in rows]


@router.get("/authority-bindings/{binding_id}")
def get_memory_authority_binding(
    binding_id: str,
    principal_id: str | None = Query(default=None, min_length=1, max_length=200),
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> AuthorityBindingOut:
    row = container.memory_runtime.get_authority_binding(
        binding_id,
        principal_id=resolve_principal_id(principal_id, context),
    )
    if not row:
        raise HTTPException(status_code=404, detail="authority_binding_not_found")
    return _authority_binding_out(row)


@router.post("/delivery-preferences")
def upsert_memory_delivery_preference(
    body: DeliveryPreferenceIn,
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> DeliveryPreferenceOut:
    row = container.memory_runtime.upsert_delivery_preference(
        principal_id=resolve_principal_id(body.principal_id, context),
        channel=body.channel,
        recipient_ref=body.recipient_ref,
        cadence=body.cadence,
        quiet_hours_json=body.quiet_hours_json,
        format_json=body.format_json,
        status=body.status,
        preference_id=body.preference_id,
    )
    return _delivery_preference_out(row)


@router.get("/delivery-preferences")
def list_memory_delivery_preferences(
    principal_id: str | None = Query(default=None, min_length=1, max_length=200),
    limit: int = Query(default=100, ge=1, le=500),
    status: str | None = Query(default=None),
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> list[DeliveryPreferenceOut]:
    rows = container.memory_runtime.list_delivery_preferences(
        principal_id=resolve_principal_id(principal_id, context),
        limit=limit,
        status=status,
    )
    return [_delivery_preference_out(row) for row in rows]


@router.get("/delivery-preferences/{preference_id}")
def get_memory_delivery_preference(
    preference_id: str,
    principal_id: str | None = Query(default=None, min_length=1, max_length=200),
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> DeliveryPreferenceOut:
    row = container.memory_runtime.get_delivery_preference(
        preference_id,
        principal_id=resolve_principal_id(principal_id, context),
    )
    if not row:
        raise HTTPException(status_code=404, detail="delivery_preference_not_found")
    return _delivery_preference_out(row)


@router.post("/interruption-budgets")
def upsert_memory_interruption_budget(
    body: InterruptionBudgetIn,
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> InterruptionBudgetOut:
    row = container.memory_runtime.upsert_interruption_budget(
        principal_id=resolve_principal_id(body.principal_id, context),
        scope=body.scope,
        window_kind=body.window_kind,
        budget_minutes=body.budget_minutes,
        used_minutes=body.used_minutes,
        reset_at=body.reset_at,
        quiet_hours_json=body.quiet_hours_json,
        status=body.status,
        notes=body.notes,
        budget_id=body.budget_id,
    )
    return _interruption_budget_out(row)


@router.get("/interruption-budgets")
def list_memory_interruption_budgets(
    principal_id: str | None = Query(default=None, min_length=1, max_length=200),
    limit: int = Query(default=100, ge=1, le=500),
    status: str | None = Query(default=None),
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> list[InterruptionBudgetOut]:
    rows = container.memory_runtime.list_interruption_budgets(
        principal_id=resolve_principal_id(principal_id, context),
        limit=limit,
        status=status,
    )
    return [_interruption_budget_out(row) for row in rows]


@router.get("/interruption-budgets/{budget_id}")
def get_memory_interruption_budget(
    budget_id: str,
    principal_id: str | None = Query(default=None, min_length=1, max_length=200),
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> InterruptionBudgetOut:
    row = container.memory_runtime.get_interruption_budget(
        budget_id,
        principal_id=resolve_principal_id(principal_id, context),
    )
    if not row:
        raise HTTPException(status_code=404, detail="interruption_budget_not_found")
    return _interruption_budget_out(row)
