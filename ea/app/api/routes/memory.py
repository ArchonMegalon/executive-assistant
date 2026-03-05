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
