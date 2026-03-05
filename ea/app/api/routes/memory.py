from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.api.dependencies import get_container
from app.container import AppContainer

router = APIRouter(prefix="/v1/memory", tags=["memory"])


class MemoryCandidateIn(BaseModel):
    principal_id: str = Field(min_length=1, max_length=200)
    category: str = Field(default="fact", min_length=1, max_length=120)
    summary: str = Field(min_length=1, max_length=4000)
    fact_json: dict[str, object] = Field(default_factory=dict)
    source_session_id: str = Field(default="", max_length=200)
    source_event_id: str = Field(default="", max_length=200)
    source_step_id: str = Field(default="", max_length=200)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    sensitivity: str = Field(default="internal", max_length=100)


class MemoryCandidateOut(BaseModel):
    candidate_id: str
    principal_id: str
    category: str
    summary: str
    fact_json: dict[str, object]
    source_session_id: str
    source_event_id: str
    source_step_id: str
    confidence: float
    sensitivity: str
    status: str
    created_at: str
    reviewed_at: str | None
    reviewer: str
    promoted_item_id: str


class MemoryItemOut(BaseModel):
    item_id: str
    principal_id: str
    category: str
    summary: str
    fact_json: dict[str, object]
    provenance_json: dict[str, object]
    confidence: float
    sensitivity: str
    sharing_policy: str
    last_verified_at: str | None
    reviewer: str
    created_at: str
    updated_at: str


class EntityIn(BaseModel):
    principal_id: str = Field(min_length=1, max_length=200)
    entity_type: str = Field(min_length=1, max_length=120)
    canonical_name: str = Field(min_length=1, max_length=400)
    attributes_json: dict[str, object] = Field(default_factory=dict)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    status: str = Field(default="active", max_length=60)


class EntityOut(BaseModel):
    entity_id: str
    principal_id: str
    entity_type: str
    canonical_name: str
    attributes_json: dict[str, object]
    confidence: float
    status: str
    created_at: str
    updated_at: str


class RelationshipIn(BaseModel):
    principal_id: str = Field(min_length=1, max_length=200)
    from_entity_id: str = Field(min_length=1, max_length=200)
    to_entity_id: str = Field(min_length=1, max_length=200)
    relationship_type: str = Field(min_length=1, max_length=120)
    attributes_json: dict[str, object] = Field(default_factory=dict)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    valid_from: str | None = Field(default=None, max_length=80)
    valid_to: str | None = Field(default=None, max_length=80)


class RelationshipOut(BaseModel):
    relationship_id: str
    principal_id: str
    from_entity_id: str
    to_entity_id: str
    relationship_type: str
    attributes_json: dict[str, object]
    confidence: float
    valid_from: str | None
    valid_to: str | None
    created_at: str
    updated_at: str


class CommitmentIn(BaseModel):
    principal_id: str = Field(min_length=1, max_length=200)
    title: str = Field(min_length=1, max_length=400)
    details: str = Field(default="", max_length=5000)
    status: str = Field(default="open", max_length=80)
    priority: str = Field(default="medium", max_length=80)
    due_at: str | None = Field(default=None, max_length=80)
    source_json: dict[str, object] = Field(default_factory=dict)
    commitment_id: str | None = Field(default=None, max_length=200)


class CommitmentOut(BaseModel):
    commitment_id: str
    principal_id: str
    title: str
    details: str
    status: str
    priority: str
    due_at: str | None
    source_json: dict[str, object]
    created_at: str
    updated_at: str


class DecisionWindowIn(BaseModel):
    principal_id: str = Field(min_length=1, max_length=200)
    title: str = Field(min_length=1, max_length=400)
    context: str = Field(default="", max_length=5000)
    opens_at: str | None = Field(default=None, max_length=80)
    closes_at: str | None = Field(default=None, max_length=80)
    urgency: str = Field(default="medium", max_length=80)
    authority_required: str = Field(default="manager", max_length=120)
    status: str = Field(default="open", max_length=80)
    notes: str = Field(default="", max_length=5000)
    source_json: dict[str, object] = Field(default_factory=dict)
    decision_window_id: str | None = Field(default=None, max_length=200)


class DecisionWindowOut(BaseModel):
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
    source_json: dict[str, object]
    created_at: str
    updated_at: str


class DeadlineWindowIn(BaseModel):
    principal_id: str = Field(min_length=1, max_length=200)
    title: str = Field(min_length=1, max_length=400)
    start_at: str | None = Field(default=None, max_length=80)
    end_at: str | None = Field(default=None, max_length=80)
    status: str = Field(default="open", max_length=80)
    priority: str = Field(default="medium", max_length=80)
    notes: str = Field(default="", max_length=5000)
    source_json: dict[str, object] = Field(default_factory=dict)
    window_id: str | None = Field(default=None, max_length=200)


class DeadlineWindowOut(BaseModel):
    window_id: str
    principal_id: str
    title: str
    start_at: str | None
    end_at: str | None
    status: str
    priority: str
    notes: str
    source_json: dict[str, object]
    created_at: str
    updated_at: str


class StakeholderIn(BaseModel):
    principal_id: str = Field(min_length=1, max_length=200)
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
    principal_id: str = Field(min_length=1, max_length=200)
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
    principal_id: str = Field(min_length=1, max_length=200)
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


class FollowUpIn(BaseModel):
    principal_id: str = Field(min_length=1, max_length=200)
    stakeholder_ref: str = Field(min_length=1, max_length=200)
    topic: str = Field(min_length=1, max_length=500)
    status: str = Field(default="open", max_length=80)
    due_at: str | None = Field(default=None, max_length=80)
    channel_hint: str = Field(default="", max_length=120)
    notes: str = Field(default="", max_length=5000)
    source_json: dict[str, object] = Field(default_factory=dict)
    follow_up_id: str | None = Field(default=None, max_length=200)


class FollowUpOut(BaseModel):
    follow_up_id: str
    principal_id: str
    stakeholder_ref: str
    topic: str
    status: str
    due_at: str | None
    channel_hint: str
    notes: str
    source_json: dict[str, object]
    created_at: str
    updated_at: str


class PromoteCandidateIn(BaseModel):
    reviewer: str = Field(min_length=1, max_length=200)
    sharing_policy: str = Field(default="private", max_length=100)
    confidence_override: float | None = Field(default=None, ge=0.0, le=1.0)


class PromoteCandidateOut(BaseModel):
    candidate: MemoryCandidateOut
    item: MemoryItemOut


class RejectCandidateIn(BaseModel):
    reviewer: str = Field(min_length=1, max_length=200)



def _candidate_out(row) -> MemoryCandidateOut:
    return MemoryCandidateOut(
        candidate_id=row.candidate_id,
        principal_id=row.principal_id,
        category=row.category,
        summary=row.summary,
        fact_json=row.fact_json,
        source_session_id=row.source_session_id,
        source_event_id=row.source_event_id,
        source_step_id=row.source_step_id,
        confidence=row.confidence,
        sensitivity=row.sensitivity,
        status=row.status,
        created_at=row.created_at,
        reviewed_at=row.reviewed_at,
        reviewer=row.reviewer,
        promoted_item_id=row.promoted_item_id,
    )



def _item_out(row) -> MemoryItemOut:
    return MemoryItemOut(
        item_id=row.item_id,
        principal_id=row.principal_id,
        category=row.category,
        summary=row.summary,
        fact_json=row.fact_json,
        provenance_json=row.provenance_json,
        confidence=row.confidence,
        sensitivity=row.sensitivity,
        sharing_policy=row.sharing_policy,
        last_verified_at=row.last_verified_at,
        reviewer=row.reviewer,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _entity_out(row) -> EntityOut:
    return EntityOut(
        entity_id=row.entity_id,
        principal_id=row.principal_id,
        entity_type=row.entity_type,
        canonical_name=row.canonical_name,
        attributes_json=row.attributes_json,
        confidence=row.confidence,
        status=row.status,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _relationship_out(row) -> RelationshipOut:
    return RelationshipOut(
        relationship_id=row.relationship_id,
        principal_id=row.principal_id,
        from_entity_id=row.from_entity_id,
        to_entity_id=row.to_entity_id,
        relationship_type=row.relationship_type,
        attributes_json=row.attributes_json,
        confidence=row.confidence,
        valid_from=row.valid_from,
        valid_to=row.valid_to,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _commitment_out(row) -> CommitmentOut:
    return CommitmentOut(
        commitment_id=row.commitment_id,
        principal_id=row.principal_id,
        title=row.title,
        details=row.details,
        status=row.status,
        priority=row.priority,
        due_at=row.due_at,
        source_json=row.source_json,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _decision_window_out(row) -> DecisionWindowOut:
    return DecisionWindowOut(
        decision_window_id=row.decision_window_id,
        principal_id=row.principal_id,
        title=row.title,
        context=row.context,
        opens_at=row.opens_at,
        closes_at=row.closes_at,
        urgency=row.urgency,
        authority_required=row.authority_required,
        status=row.status,
        notes=row.notes,
        source_json=row.source_json,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _deadline_window_out(row) -> DeadlineWindowOut:
    return DeadlineWindowOut(
        window_id=row.window_id,
        principal_id=row.principal_id,
        title=row.title,
        start_at=row.start_at,
        end_at=row.end_at,
        status=row.status,
        priority=row.priority,
        notes=row.notes,
        source_json=row.source_json,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _stakeholder_out(row) -> StakeholderOut:
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


def _authority_binding_out(row) -> AuthorityBindingOut:
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


def _delivery_preference_out(row) -> DeliveryPreferenceOut:
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


def _follow_up_out(row) -> FollowUpOut:
    return FollowUpOut(
        follow_up_id=row.follow_up_id,
        principal_id=row.principal_id,
        stakeholder_ref=row.stakeholder_ref,
        topic=row.topic,
        status=row.status,
        due_at=row.due_at,
        channel_hint=row.channel_hint,
        notes=row.notes,
        source_json=row.source_json,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


@router.post("/candidates")
def stage_memory_candidate(
    body: MemoryCandidateIn,
    container: AppContainer = Depends(get_container),
) -> MemoryCandidateOut:
    row = container.memory_runtime.stage_candidate(
        principal_id=body.principal_id,
        category=body.category,
        summary=body.summary,
        fact_json=body.fact_json,
        source_session_id=body.source_session_id,
        source_event_id=body.source_event_id,
        source_step_id=body.source_step_id,
        confidence=body.confidence,
        sensitivity=body.sensitivity,
    )
    return _candidate_out(row)


@router.get("/candidates")
def list_memory_candidates(
    limit: int = Query(default=100, ge=1, le=500),
    status: str | None = Query(default=None),
    principal_id: str | None = Query(default=None),
    container: AppContainer = Depends(get_container),
) -> list[MemoryCandidateOut]:
    rows = container.memory_runtime.list_candidates(limit=limit, status=status, principal_id=principal_id)
    return [_candidate_out(row) for row in rows]


@router.post("/candidates/{candidate_id}/promote")
def promote_memory_candidate(
    candidate_id: str,
    body: PromoteCandidateIn,
    container: AppContainer = Depends(get_container),
) -> PromoteCandidateOut:
    found = container.memory_runtime.promote_candidate(
        candidate_id,
        reviewer=body.reviewer,
        sharing_policy=body.sharing_policy,
        confidence_override=body.confidence_override,
    )
    if not found:
        raise HTTPException(status_code=404, detail="memory_candidate_not_found")
    candidate, item = found
    return PromoteCandidateOut(candidate=_candidate_out(candidate), item=_item_out(item))


@router.post("/candidates/{candidate_id}/reject")
def reject_memory_candidate(
    candidate_id: str,
    body: RejectCandidateIn,
    container: AppContainer = Depends(get_container),
) -> MemoryCandidateOut:
    row = container.memory_runtime.reject_candidate(candidate_id, reviewer=body.reviewer)
    if not row:
        raise HTTPException(status_code=404, detail="memory_candidate_not_found")
    return _candidate_out(row)


@router.get("/items")
def list_memory_items(
    limit: int = Query(default=100, ge=1, le=500),
    principal_id: str | None = Query(default=None),
    container: AppContainer = Depends(get_container),
) -> list[MemoryItemOut]:
    rows = container.memory_runtime.list_items(limit=limit, principal_id=principal_id)
    return [_item_out(row) for row in rows]


@router.get("/items/{item_id}")
def get_memory_item(
    item_id: str,
    container: AppContainer = Depends(get_container),
) -> MemoryItemOut:
    row = container.memory_runtime.get_item(item_id)
    if not row:
        raise HTTPException(status_code=404, detail="memory_item_not_found")
    return _item_out(row)


@router.post("/entities")
def upsert_memory_entity(
    body: EntityIn,
    container: AppContainer = Depends(get_container),
) -> EntityOut:
    row = container.memory_runtime.upsert_entity(
        principal_id=body.principal_id,
        entity_type=body.entity_type,
        canonical_name=body.canonical_name,
        attributes_json=body.attributes_json,
        confidence=body.confidence,
        status=body.status,
    )
    return _entity_out(row)


@router.get("/entities")
def list_memory_entities(
    limit: int = Query(default=100, ge=1, le=500),
    principal_id: str | None = Query(default=None),
    entity_type: str | None = Query(default=None),
    container: AppContainer = Depends(get_container),
) -> list[EntityOut]:
    rows = container.memory_runtime.list_entities(
        limit=limit,
        principal_id=principal_id,
        entity_type=entity_type,
    )
    return [_entity_out(row) for row in rows]


@router.get("/entities/{entity_id}")
def get_memory_entity(
    entity_id: str,
    container: AppContainer = Depends(get_container),
) -> EntityOut:
    row = container.memory_runtime.get_entity(entity_id)
    if not row:
        raise HTTPException(status_code=404, detail="entity_not_found")
    return _entity_out(row)


@router.post("/relationships")
def upsert_memory_relationship(
    body: RelationshipIn,
    container: AppContainer = Depends(get_container),
) -> RelationshipOut:
    row = container.memory_runtime.upsert_relationship(
        principal_id=body.principal_id,
        from_entity_id=body.from_entity_id,
        to_entity_id=body.to_entity_id,
        relationship_type=body.relationship_type,
        attributes_json=body.attributes_json,
        confidence=body.confidence,
        valid_from=body.valid_from,
        valid_to=body.valid_to,
    )
    return _relationship_out(row)


@router.get("/relationships")
def list_memory_relationships(
    limit: int = Query(default=100, ge=1, le=500),
    principal_id: str | None = Query(default=None),
    from_entity_id: str | None = Query(default=None),
    to_entity_id: str | None = Query(default=None),
    relationship_type: str | None = Query(default=None),
    container: AppContainer = Depends(get_container),
) -> list[RelationshipOut]:
    rows = container.memory_runtime.list_relationships(
        limit=limit,
        principal_id=principal_id,
        from_entity_id=from_entity_id,
        to_entity_id=to_entity_id,
        relationship_type=relationship_type,
    )
    return [_relationship_out(row) for row in rows]


@router.get("/relationships/{relationship_id}")
def get_memory_relationship(
    relationship_id: str,
    container: AppContainer = Depends(get_container),
) -> RelationshipOut:
    row = container.memory_runtime.get_relationship(relationship_id)
    if not row:
        raise HTTPException(status_code=404, detail="relationship_not_found")
    return _relationship_out(row)


@router.post("/commitments")
def upsert_memory_commitment(
    body: CommitmentIn,
    container: AppContainer = Depends(get_container),
) -> CommitmentOut:
    row = container.memory_runtime.upsert_commitment(
        principal_id=body.principal_id,
        title=body.title,
        details=body.details,
        status=body.status,
        priority=body.priority,
        due_at=body.due_at,
        source_json=body.source_json,
        commitment_id=body.commitment_id,
    )
    return _commitment_out(row)


@router.get("/commitments")
def list_memory_commitments(
    principal_id: str = Query(min_length=1, max_length=200),
    limit: int = Query(default=100, ge=1, le=500),
    status: str | None = Query(default=None),
    container: AppContainer = Depends(get_container),
) -> list[CommitmentOut]:
    rows = container.memory_runtime.list_commitments(
        principal_id=principal_id,
        limit=limit,
        status=status,
    )
    return [_commitment_out(row) for row in rows]


@router.get("/commitments/{commitment_id}")
def get_memory_commitment(
    commitment_id: str,
    principal_id: str = Query(min_length=1, max_length=200),
    container: AppContainer = Depends(get_container),
) -> CommitmentOut:
    row = container.memory_runtime.get_commitment(commitment_id, principal_id=principal_id)
    if not row:
        raise HTTPException(status_code=404, detail="commitment_not_found")
    return _commitment_out(row)


@router.post("/decision-windows")
def upsert_memory_decision_window(
    body: DecisionWindowIn,
    container: AppContainer = Depends(get_container),
) -> DecisionWindowOut:
    row = container.memory_runtime.upsert_decision_window(
        principal_id=body.principal_id,
        title=body.title,
        context=body.context,
        opens_at=body.opens_at,
        closes_at=body.closes_at,
        urgency=body.urgency,
        authority_required=body.authority_required,
        status=body.status,
        notes=body.notes,
        source_json=body.source_json,
        decision_window_id=body.decision_window_id,
    )
    return _decision_window_out(row)


@router.get("/decision-windows")
def list_memory_decision_windows(
    principal_id: str = Query(min_length=1, max_length=200),
    limit: int = Query(default=100, ge=1, le=500),
    status: str | None = Query(default=None),
    container: AppContainer = Depends(get_container),
) -> list[DecisionWindowOut]:
    rows = container.memory_runtime.list_decision_windows(
        principal_id=principal_id,
        limit=limit,
        status=status,
    )
    return [_decision_window_out(row) for row in rows]


@router.get("/decision-windows/{decision_window_id}")
def get_memory_decision_window(
    decision_window_id: str,
    principal_id: str = Query(min_length=1, max_length=200),
    container: AppContainer = Depends(get_container),
) -> DecisionWindowOut:
    row = container.memory_runtime.get_decision_window(decision_window_id, principal_id=principal_id)
    if not row:
        raise HTTPException(status_code=404, detail="decision_window_not_found")
    return _decision_window_out(row)


@router.post("/deadline-windows")
def upsert_memory_deadline_window(
    body: DeadlineWindowIn,
    container: AppContainer = Depends(get_container),
) -> DeadlineWindowOut:
    row = container.memory_runtime.upsert_deadline_window(
        principal_id=body.principal_id,
        title=body.title,
        start_at=body.start_at,
        end_at=body.end_at,
        status=body.status,
        priority=body.priority,
        notes=body.notes,
        source_json=body.source_json,
        window_id=body.window_id,
    )
    return _deadline_window_out(row)


@router.get("/deadline-windows")
def list_memory_deadline_windows(
    principal_id: str = Query(min_length=1, max_length=200),
    limit: int = Query(default=100, ge=1, le=500),
    status: str | None = Query(default=None),
    container: AppContainer = Depends(get_container),
) -> list[DeadlineWindowOut]:
    rows = container.memory_runtime.list_deadline_windows(
        principal_id=principal_id,
        limit=limit,
        status=status,
    )
    return [_deadline_window_out(row) for row in rows]


@router.get("/deadline-windows/{window_id}")
def get_memory_deadline_window(
    window_id: str,
    principal_id: str = Query(min_length=1, max_length=200),
    container: AppContainer = Depends(get_container),
) -> DeadlineWindowOut:
    row = container.memory_runtime.get_deadline_window(window_id, principal_id=principal_id)
    if not row:
        raise HTTPException(status_code=404, detail="deadline_window_not_found")
    return _deadline_window_out(row)


@router.post("/stakeholders")
def upsert_memory_stakeholder(
    body: StakeholderIn,
    container: AppContainer = Depends(get_container),
) -> StakeholderOut:
    row = container.memory_runtime.upsert_stakeholder(
        principal_id=body.principal_id,
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
    principal_id: str = Query(min_length=1, max_length=200),
    limit: int = Query(default=100, ge=1, le=500),
    status: str | None = Query(default=None),
    container: AppContainer = Depends(get_container),
) -> list[StakeholderOut]:
    rows = container.memory_runtime.list_stakeholders(
        principal_id=principal_id,
        limit=limit,
        status=status,
    )
    return [_stakeholder_out(row) for row in rows]


@router.get("/stakeholders/{stakeholder_id}")
def get_memory_stakeholder(
    stakeholder_id: str,
    principal_id: str = Query(min_length=1, max_length=200),
    container: AppContainer = Depends(get_container),
) -> StakeholderOut:
    row = container.memory_runtime.get_stakeholder(stakeholder_id, principal_id=principal_id)
    if not row:
        raise HTTPException(status_code=404, detail="stakeholder_not_found")
    return _stakeholder_out(row)


@router.post("/authority-bindings")
def upsert_memory_authority_binding(
    body: AuthorityBindingIn,
    container: AppContainer = Depends(get_container),
) -> AuthorityBindingOut:
    row = container.memory_runtime.upsert_authority_binding(
        principal_id=body.principal_id,
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
    principal_id: str = Query(min_length=1, max_length=200),
    limit: int = Query(default=100, ge=1, le=500),
    status: str | None = Query(default=None),
    container: AppContainer = Depends(get_container),
) -> list[AuthorityBindingOut]:
    rows = container.memory_runtime.list_authority_bindings(
        principal_id=principal_id,
        limit=limit,
        status=status,
    )
    return [_authority_binding_out(row) for row in rows]


@router.get("/authority-bindings/{binding_id}")
def get_memory_authority_binding(
    binding_id: str,
    principal_id: str = Query(min_length=1, max_length=200),
    container: AppContainer = Depends(get_container),
) -> AuthorityBindingOut:
    row = container.memory_runtime.get_authority_binding(binding_id, principal_id=principal_id)
    if not row:
        raise HTTPException(status_code=404, detail="authority_binding_not_found")
    return _authority_binding_out(row)


@router.post("/delivery-preferences")
def upsert_memory_delivery_preference(
    body: DeliveryPreferenceIn,
    container: AppContainer = Depends(get_container),
) -> DeliveryPreferenceOut:
    row = container.memory_runtime.upsert_delivery_preference(
        principal_id=body.principal_id,
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
    principal_id: str = Query(min_length=1, max_length=200),
    limit: int = Query(default=100, ge=1, le=500),
    status: str | None = Query(default=None),
    container: AppContainer = Depends(get_container),
) -> list[DeliveryPreferenceOut]:
    rows = container.memory_runtime.list_delivery_preferences(
        principal_id=principal_id,
        limit=limit,
        status=status,
    )
    return [_delivery_preference_out(row) for row in rows]


@router.get("/delivery-preferences/{preference_id}")
def get_memory_delivery_preference(
    preference_id: str,
    principal_id: str = Query(min_length=1, max_length=200),
    container: AppContainer = Depends(get_container),
) -> DeliveryPreferenceOut:
    row = container.memory_runtime.get_delivery_preference(preference_id, principal_id=principal_id)
    if not row:
        raise HTTPException(status_code=404, detail="delivery_preference_not_found")
    return _delivery_preference_out(row)


@router.post("/follow-ups")
def upsert_memory_follow_up(
    body: FollowUpIn,
    container: AppContainer = Depends(get_container),
) -> FollowUpOut:
    row = container.memory_runtime.upsert_follow_up(
        principal_id=body.principal_id,
        stakeholder_ref=body.stakeholder_ref,
        topic=body.topic,
        status=body.status,
        due_at=body.due_at,
        channel_hint=body.channel_hint,
        notes=body.notes,
        source_json=body.source_json,
        follow_up_id=body.follow_up_id,
    )
    return _follow_up_out(row)


@router.get("/follow-ups")
def list_memory_follow_ups(
    principal_id: str = Query(min_length=1, max_length=200),
    limit: int = Query(default=100, ge=1, le=500),
    status: str | None = Query(default=None),
    container: AppContainer = Depends(get_container),
) -> list[FollowUpOut]:
    rows = container.memory_runtime.list_follow_ups(
        principal_id=principal_id,
        limit=limit,
        status=status,
    )
    return [_follow_up_out(row) for row in rows]


@router.get("/follow-ups/{follow_up_id}")
def get_memory_follow_up(
    follow_up_id: str,
    principal_id: str = Query(min_length=1, max_length=200),
    container: AppContainer = Depends(get_container),
) -> FollowUpOut:
    row = container.memory_runtime.get_follow_up(follow_up_id, principal_id=principal_id)
    if not row:
        raise HTTPException(status_code=404, detail="follow_up_not_found")
    return _follow_up_out(row)
