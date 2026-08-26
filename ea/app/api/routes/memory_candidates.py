from __future__ import annotations

import hashlib
import json
import re
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field

from app.api.dependencies import (
    RequestContext,
    get_container,
    get_memorial_approved_memory_context,
    get_request_context,
    resolve_principal_id,
)
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


class MemorialApprovedMemoryItemOut(BaseModel):
    item_ref_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    kind: Literal["memory_card", "orientation_facet"]
    title: str = Field(min_length=1, max_length=200)
    text: str = Field(min_length=1, max_length=1200)
    source_label: str = Field(min_length=1, max_length=200)


class MemorialApprovedMemoryPackOut(BaseModel):
    contract_name: Literal["ea.memorial-approved-memory-pack/v1"] = (
        "ea.memorial-approved-memory-pack/v1"
    )
    slug: Literal["manfred"]
    items: tuple[MemorialApprovedMemoryItemOut, ...]
    source_set_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    raw_mail_content_included: Literal[False] = False


_MEMORIAL_APPROVED_CATEGORIES = frozenset(
    {"memorial_memory_card", "memorial_grounded_profile"}
)
_EMAIL_ADDRESS = re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b")


def _normalized_public_text(value: object, *, maximum: int) -> str:
    text = " ".join(str(value or "").split())
    if not text or len(text) > maximum or _EMAIL_ADDRESS.search(text):
        return ""
    return text


def build_memorial_approved_pack(
    rows: list[object],
    *,
    slug: str,
) -> MemorialApprovedMemoryPackOut:
    if slug != "manfred":
        raise HTTPException(status_code=404, detail="memorial_memory_pack_not_found")
    approved: dict[str, MemorialApprovedMemoryItemOut] = {}
    for row in rows:
        category = str(getattr(row, "category", "") or "").strip()
        if category not in _MEMORIAL_APPROVED_CATEGORIES:
            continue
        fact = getattr(row, "fact_json", None)
        if not isinstance(fact, dict):
            continue
        if (
            fact.get("memorial_slug") != slug
            or fact.get("public_approved") is not True
            or not _normalized_public_text(fact.get("public_approval_key"), maximum=200)
            or not str(getattr(row, "reviewer", "") or "").strip()
            or getattr(row, "last_verified_at", None) is None
        ):
            continue
        if category == "memorial_memory_card":
            kind = "memory_card"
            title = _normalized_public_text(fact.get("title"), maximum=200)
            text = _normalized_public_text(fact.get("body"), maximum=1200)
            source_label = _normalized_public_text(
                fact.get("source_label"), maximum=200
            )
        else:
            kind = "orientation_facet"
            title = _normalized_public_text(fact.get("trait"), maximum=200)
            text = _normalized_public_text(fact.get("evidence"), maximum=1200)
            source_label = "Freigegebenes Manfred-Profil"
        if not title or not text or not source_label:
            continue
        content_key = json.dumps(
            [kind, title, text, source_label],
            ensure_ascii=False,
            separators=(",", ":"),
        )
        content_sha256 = hashlib.sha256(content_key.encode("utf-8")).hexdigest()
        item_ref = hashlib.sha256(
            str(getattr(row, "item_id", "") or "").encode("utf-8")
        ).hexdigest()
        approved.setdefault(
            content_sha256,
            MemorialApprovedMemoryItemOut(
                item_ref_sha256=item_ref,
                kind=kind,
                title=title,
                text=text,
                source_label=source_label,
            ),
        )
    items = tuple(approved[key] for key in sorted(approved))[:64]
    canonical_items = [item.model_dump(mode="json") for item in items]
    source_set_sha256 = hashlib.sha256(
        json.dumps(
            canonical_items,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("ascii")
    ).hexdigest()
    return MemorialApprovedMemoryPackOut(
        slug="manfred",
        items=items,
        source_set_sha256=source_set_sha256,
    )


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


@router.post("/candidates/stage")
def stage_memory_candidate_legacy(
    body: MemoryCandidateIn,
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> MemoryCandidateOut:
    return stage_memory_candidate(body=body, container=container, context=context)


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


@router.get("/memorial-approved/{slug}")
def get_memorial_approved_memory_pack(
    slug: str,
    response: Response,
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_memorial_approved_memory_context),
) -> MemorialApprovedMemoryPackOut:
    response.headers["Cache-Control"] = "no-store"
    rows = container.memory_runtime.list_items(
        limit=500,
        principal_id=context.principal_id,
    )
    return build_memorial_approved_pack(rows, slug=slug)
