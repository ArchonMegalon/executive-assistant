from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.api.dependencies import RequestContext, get_container, get_request_context, resolve_principal_id
from app.container import AppContainer

router = APIRouter(tags=["memory"])


class MemoryCandidateIn(BaseModel):
    principal_id: str | None = Field(default=None, min_length=1, max_length=200)
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


class PromoteCandidateIn(BaseModel):
    reviewer: str = Field(min_length=1, max_length=200)
    sharing_policy: str = Field(default="private", max_length=100)
    confidence_override: float | None = Field(default=None, ge=0.0, le=1.0)


class PromoteCandidateOut(BaseModel):
    candidate: MemoryCandidateOut
    item: MemoryItemOut


class RejectCandidateIn(BaseModel):
    reviewer: str = Field(min_length=1, max_length=200)


def _candidate_out(row) -> MemoryCandidateOut:  # type: ignore[no-untyped-def]
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


def _item_out(row) -> MemoryItemOut:  # type: ignore[no-untyped-def]
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


@router.post("/candidates")
def stage_memory_candidate(
    body: MemoryCandidateIn,
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> MemoryCandidateOut:
    row = container.memory_runtime.stage_candidate(
        principal_id=resolve_principal_id(body.principal_id, context),
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
    context: RequestContext = Depends(get_request_context),
) -> list[MemoryCandidateOut]:
    rows = container.memory_runtime.list_candidates(
        limit=limit,
        status=status,
        principal_id=resolve_principal_id(principal_id, context),
    )
    return [_candidate_out(row) for row in rows]


@router.post("/candidates/{candidate_id}/promote")
def promote_memory_candidate(
    candidate_id: str,
    body: PromoteCandidateIn,
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> PromoteCandidateOut:
    found = container.memory_runtime.promote_candidate(
        candidate_id,
        principal_id=context.principal_id,
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
    context: RequestContext = Depends(get_request_context),
) -> MemoryCandidateOut:
    row = container.memory_runtime.reject_candidate(
        candidate_id,
        principal_id=context.principal_id,
        reviewer=body.reviewer,
    )
    if not row:
        raise HTTPException(status_code=404, detail="memory_candidate_not_found")
    return _candidate_out(row)


@router.get("/items")
def list_memory_items(
    limit: int = Query(default=100, ge=1, le=500),
    principal_id: str | None = Query(default=None),
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> list[MemoryItemOut]:
    rows = container.memory_runtime.list_items(
        limit=limit,
        principal_id=resolve_principal_id(principal_id, context),
    )
    return [_item_out(row) for row in rows]


@router.get("/items/{item_id}")
def get_memory_item(
    item_id: str,
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> MemoryItemOut:
    row = container.memory_runtime.get_item(item_id, principal_id=context.principal_id)
    if not row:
        raise HTTPException(status_code=404, detail="memory_item_not_found")
    return _item_out(row)
