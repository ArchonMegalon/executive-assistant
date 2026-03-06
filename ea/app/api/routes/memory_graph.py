from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.api.dependencies import RequestContext, get_container, get_request_context, resolve_principal_id
from app.container import AppContainer

router = APIRouter(tags=["memory"])


class EntityIn(BaseModel):
    principal_id: str | None = Field(default=None, min_length=1, max_length=200)
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
    principal_id: str | None = Field(default=None, min_length=1, max_length=200)
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


def _entity_out(row) -> EntityOut:  # type: ignore[no-untyped-def]
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


def _relationship_out(row) -> RelationshipOut:  # type: ignore[no-untyped-def]
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


@router.post("/entities")
def upsert_memory_entity(
    body: EntityIn,
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> EntityOut:
    row = container.memory_runtime.upsert_entity(
        principal_id=resolve_principal_id(body.principal_id, context),
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
    context: RequestContext = Depends(get_request_context),
) -> list[EntityOut]:
    rows = container.memory_runtime.list_entities(
        limit=limit,
        principal_id=resolve_principal_id(principal_id, context),
        entity_type=entity_type,
    )
    return [_entity_out(row) for row in rows]


@router.get("/entities/{entity_id}")
def get_memory_entity(
    entity_id: str,
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> EntityOut:
    row = container.memory_runtime.get_entity(entity_id, principal_id=context.principal_id)
    if not row:
        raise HTTPException(status_code=404, detail="entity_not_found")
    return _entity_out(row)


@router.post("/relationships")
def upsert_memory_relationship(
    body: RelationshipIn,
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> RelationshipOut:
    row = container.memory_runtime.upsert_relationship(
        principal_id=resolve_principal_id(body.principal_id, context),
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
    context: RequestContext = Depends(get_request_context),
) -> list[RelationshipOut]:
    rows = container.memory_runtime.list_relationships(
        limit=limit,
        principal_id=resolve_principal_id(principal_id, context),
        from_entity_id=from_entity_id,
        to_entity_id=to_entity_id,
        relationship_type=relationship_type,
    )
    return [_relationship_out(row) for row in rows]


@router.get("/relationships/{relationship_id}")
def get_memory_relationship(
    relationship_id: str,
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> RelationshipOut:
    row = container.memory_runtime.get_relationship(relationship_id, principal_id=context.principal_id)
    if not row:
        raise HTTPException(status_code=404, detail="relationship_not_found")
    return _relationship_out(row)
