from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.api.dependencies import RequestContext, get_container, get_request_context, resolve_principal_id
from app.container import AppContainer
from app.services.memory_reasoning_service import MemoryReasoningService

router = APIRouter(tags=["memory"])


class ContextPackIn(BaseModel):
    principal_id: str | None = Field(default=None, min_length=1, max_length=200)
    task_key: str = Field(default="rewrite_text", max_length=200)
    goal: str = Field(default="", max_length=2000)
    context_refs: list[str] = Field(default_factory=list)
    limit: int = Field(default=5, ge=1, le=20)


class MemoryPromotionSignalOut(BaseModel):
    candidate_id: str
    category: str
    summary: str
    confidence: float
    score: float
    reasons: list[str]
    overlapping_item_ids: list[str]
    conflict_refs: list[str]


class MemoryConflictOut(BaseModel):
    conflict_id: str
    conflict_type: str
    severity: str
    summary: str
    left_ref: str
    right_ref: str
    fields: list[str]


class CommitmentRiskOut(BaseModel):
    risk_id: str
    risk_type: str
    severity: str
    reference_kind: str
    reference_id: str
    title: str
    due_at: str | None
    summary: str
    reasons: list[str]


class ContextPackOut(BaseModel):
    principal_id: str
    task_key: str
    goal: str
    context_refs: list[str]
    summary: str
    memory_items: list[dict[str, object]]
    stakeholders: list[dict[str, object]]
    commitments: list[dict[str, object]]
    deadlines: list[dict[str, object]]
    decision_windows: list[dict[str, object]]
    follow_ups: list[dict[str, object]]
    authority_bindings: list[dict[str, object]]
    delivery_preferences: list[dict[str, object]]
    communication_policies: list[dict[str, object]]
    interruption_budgets: list[dict[str, object]]
    promotion_signals: list[MemoryPromotionSignalOut]
    conflicts: list[MemoryConflictOut]
    commitment_risks: list[CommitmentRiskOut]
    unresolved_refs: list[str]


@router.post("/context-pack")
def build_memory_context_pack(
    body: ContextPackIn,
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> ContextPackOut:
    service = MemoryReasoningService(container.memory_runtime)
    pack = service.build_context_pack(
        principal_id=resolve_principal_id(body.principal_id, context),
        task_key=str(body.task_key or "").strip() or "rewrite_text",
        goal=body.goal,
        context_refs=tuple(str(value or "").strip() for value in (body.context_refs or []) if str(value or "").strip()),
        limit=body.limit,
    ).as_dict()
    return ContextPackOut(**pack)
