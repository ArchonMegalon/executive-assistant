from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.api.dependencies import RequestContext, get_container, get_request_context, resolve_principal_id
from app.container import AppContainer

router = APIRouter(prefix="/v1/evidence", tags=["evidence"])


class EvidenceObjectOut(BaseModel):
    evidence_id: str
    principal_id: str
    artifact_id: str
    execution_session_id: str
    artifact_kind: str
    summary: str
    claims: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)
    confidence: float
    citation_handle: str
    created_at: str
    updated_at: str


class EvidenceMergeIn(BaseModel):
    principal_id: str | None = Field(default=None, min_length=1, max_length=200)
    evidence_ids: list[str] = Field(min_length=1, max_length=100)


class EvidenceMergeOut(BaseModel):
    format: str = "evidence_pack"
    summary: str
    claims: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)
    confidence: float
    source_evidence_ids: list[str] = Field(default_factory=list)
    source_artifact_ids: list[str] = Field(default_factory=list)
    citation_handles: list[str] = Field(default_factory=list)


def _evidence_out(row) -> EvidenceObjectOut:  # type: ignore[no-untyped-def]
    return EvidenceObjectOut(
        evidence_id=row.evidence_id,
        principal_id=row.principal_id,
        artifact_id=row.artifact_id,
        execution_session_id=row.execution_session_id,
        artifact_kind=row.artifact_kind,
        summary=row.summary,
        claims=list(row.claims),
        evidence_refs=list(row.evidence_refs),
        open_questions=list(row.open_questions),
        confidence=row.confidence,
        citation_handle=row.citation_handle,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


@router.get("/objects")
def list_evidence_objects(
    limit: int = Query(default=100, ge=1, le=500),
    principal_id: str | None = Query(default=None),
    artifact_id: str | None = Query(default=None),
    session_id: str | None = Query(default=None),
    evidence_ref: str | None = Query(default=None),
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> list[EvidenceObjectOut]:
    rows = container.evidence_runtime.list_objects(
        limit=limit,
        principal_id=resolve_principal_id(principal_id, context),
        artifact_id=artifact_id,
        session_id=session_id,
        evidence_ref=evidence_ref,
    )
    return [_evidence_out(row) for row in rows]


@router.get("/objects/{evidence_id}")
def get_evidence_object(
    evidence_id: str,
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> EvidenceObjectOut:
    row = container.evidence_runtime.get_object(evidence_id, principal_id=context.principal_id)
    if row is None:
        raise HTTPException(status_code=404, detail="evidence_object_not_found")
    return _evidence_out(row)


@router.post("/merge")
def merge_evidence_objects(
    body: EvidenceMergeIn,
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> EvidenceMergeOut:
    principal_id = resolve_principal_id(body.principal_id, context)
    try:
        merged = container.evidence_runtime.merge_objects(body.evidence_ids, principal_id=principal_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=f"evidence_object_not_found:{exc}") from exc
    return EvidenceMergeOut(
        summary=merged.summary,
        claims=list(merged.claims),
        evidence_refs=list(merged.evidence_refs),
        open_questions=list(merged.open_questions),
        confidence=merged.confidence,
        source_evidence_ids=list(merged.source_evidence_ids),
        source_artifact_ids=list(merged.source_artifact_ids),
        citation_handles=list(merged.citation_handles),
    )
