from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.api.dependencies import RequestContext, get_container, get_request_context, resolve_principal_id
from app.container import AppContainer

router = APIRouter(tags=["memory"])


class CommitmentIn(BaseModel):
    principal_id: str | None = Field(default=None, min_length=1, max_length=200)
    title: str = Field(min_length=1, max_length=400)
    details: str = Field(default="", max_length=5000)
    status: str = Field(default="open", max_length=80)
    priority: str = Field(default="medium", max_length=80)
    due_at: str | None = Field(default=None, max_length=80)
    source_json: dict[str, object] = Field(default_factory=dict)
    commitment_id: str | None = Field(default=None, max_length=200)


class MemoryCommitmentOut(BaseModel):
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


def _commitment_out(row) -> MemoryCommitmentOut:  # type: ignore[no-untyped-def]
    return MemoryCommitmentOut(
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


@router.post("/commitments")
def upsert_memory_commitment(
    body: CommitmentIn,
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> MemoryCommitmentOut:
    row = container.memory_runtime.upsert_commitment(
        principal_id=resolve_principal_id(body.principal_id, context),
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
    principal_id: str | None = Query(default=None, min_length=1, max_length=200),
    limit: int = Query(default=100, ge=1, le=500),
    status: str | None = Query(default=None),
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> list[MemoryCommitmentOut]:
    rows = container.memory_runtime.list_commitments(
        principal_id=resolve_principal_id(principal_id, context),
        limit=limit,
        status=status,
    )
    return [_commitment_out(row) for row in rows]


@router.get("/commitments/{commitment_id}")
def get_memory_commitment(
    commitment_id: str,
    principal_id: str | None = Query(default=None, min_length=1, max_length=200),
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> MemoryCommitmentOut:
    row = container.memory_runtime.get_commitment(
        commitment_id,
        principal_id=resolve_principal_id(principal_id, context),
    )
    if not row:
        raise HTTPException(status_code=404, detail="commitment_not_found")
    return _commitment_out(row)
