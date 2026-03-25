from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.api.dependencies import RequestContext, get_container, get_request_context
from app.container import AppContainer
from app.product.models import BriefItem, CommitmentItem, DecisionQueueItem, DraftCandidate, EvidenceRef, HandoffNote, PersonDetail, PersonProfile
from app.product.service import build_product_service

router = APIRouter(prefix="/app/api", tags=["product"])


class EvidenceRefOut(BaseModel):
    ref_id: str
    label: str
    href: str = ""
    source_type: str = ""
    note: str = ""


class BriefItemOut(BaseModel):
    id: str
    workspace_id: str
    kind: str
    title: str
    summary: str
    score: float
    why_now: str
    evidence_refs: list[EvidenceRefOut]
    related_people: list[str]
    related_commitment_ids: list[str]
    recommended_action: str
    status: str


class DecisionQueueItemOut(BaseModel):
    id: str
    queue_kind: str
    title: str
    summary: str
    priority: str
    deadline: str | None = None
    owner_role: str = ""
    requires_principal: bool = False
    evidence_refs: list[EvidenceRefOut]
    resolution_state: str


class CommitmentOut(BaseModel):
    id: str
    source_type: str
    source_ref: str
    statement: str
    owner: str
    counterparty: str
    due_at: str | None = None
    status: str
    last_activity_at: str | None = None
    risk_level: str
    proof_refs: list[EvidenceRefOut]


class DraftCandidateOut(BaseModel):
    id: str
    thread_ref: str
    recipient_summary: str
    intent: str
    draft_text: str
    tone: str
    requires_approval: bool
    approval_status: str
    provenance_refs: list[EvidenceRefOut]
    send_channel: str


class PersonProfileOut(BaseModel):
    id: str
    display_name: str
    role_or_company: str
    importance_score: int
    relationship_temperature: str
    open_loops_count: int
    latest_touchpoint_at: str | None = None
    preferred_tone: str
    themes: list[str]
    risks: list[str]


class PersonDetailOut(BaseModel):
    profile: PersonProfileOut
    commitments: list[CommitmentOut]
    drafts: list[DraftCandidateOut]
    queue_items: list[DecisionQueueItemOut]
    handoffs: list[HandoffNoteOut]
    evidence_refs: list[EvidenceRefOut]


class HandoffNoteOut(BaseModel):
    id: str
    queue_item_ref: str
    summary: str
    owner: str
    due_time: str | None = None
    escalation_status: str
    status: str
    evidence_refs: list[EvidenceRefOut]


class WorkspaceDiagnosticsOut(BaseModel):
    workspace: dict[str, object]
    selected_channels: list[str]
    plan: dict[str, object]
    entitlements: dict[str, object]
    readiness: dict[str, object]
    operators: dict[str, object]
    providers: dict[str, object]
    usage: dict[str, int]


class BriefResponse(BaseModel):
    generated_at: str
    items: list[BriefItemOut]
    total: int


class QueueResponse(BaseModel):
    generated_at: str
    items: list[DecisionQueueItemOut]
    total: int


class DraftApproveIn(BaseModel):
    reason: str = "Approved from product draft queue."


class QueueResolveIn(BaseModel):
    action: str = Field(min_length=1)
    reason: str = ""
    due_at: str | None = None


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _evidence_out(values: tuple[EvidenceRef, ...]) -> list[EvidenceRefOut]:
    return [EvidenceRefOut(**value.__dict__) for value in values]


def _brief_out(value: BriefItem) -> BriefItemOut:
    return BriefItemOut(
        id=value.id,
        workspace_id=value.workspace_id,
        kind=value.kind,
        title=value.title,
        summary=value.summary,
        score=value.score,
        why_now=value.why_now,
        evidence_refs=_evidence_out(value.evidence_refs),
        related_people=list(value.related_people),
        related_commitment_ids=list(value.related_commitment_ids),
        recommended_action=value.recommended_action,
        status=value.status,
    )


def _queue_out(value: DecisionQueueItem) -> DecisionQueueItemOut:
    return DecisionQueueItemOut(
        id=value.id,
        queue_kind=value.queue_kind,
        title=value.title,
        summary=value.summary,
        priority=value.priority,
        deadline=value.deadline,
        owner_role=value.owner_role,
        requires_principal=value.requires_principal,
        evidence_refs=_evidence_out(value.evidence_refs),
        resolution_state=value.resolution_state,
    )


def _commitment_out(value: CommitmentItem) -> CommitmentOut:
    return CommitmentOut(
        id=value.id,
        source_type=value.source_type,
        source_ref=value.source_ref,
        statement=value.statement,
        owner=value.owner,
        counterparty=value.counterparty,
        due_at=value.due_at,
        status=value.status,
        last_activity_at=value.last_activity_at,
        risk_level=value.risk_level,
        proof_refs=_evidence_out(value.proof_refs),
    )


def _draft_out(value: DraftCandidate) -> DraftCandidateOut:
    return DraftCandidateOut(
        id=value.id,
        thread_ref=value.thread_ref,
        recipient_summary=value.recipient_summary,
        intent=value.intent,
        draft_text=value.draft_text,
        tone=value.tone,
        requires_approval=value.requires_approval,
        approval_status=value.approval_status,
        provenance_refs=_evidence_out(value.provenance_refs),
        send_channel=value.send_channel,
    )


def _person_out(value: PersonProfile) -> PersonProfileOut:
    return PersonProfileOut(
        id=value.id,
        display_name=value.display_name,
        role_or_company=value.role_or_company,
        importance_score=value.importance_score,
        relationship_temperature=value.relationship_temperature,
        open_loops_count=value.open_loops_count,
        latest_touchpoint_at=value.latest_touchpoint_at,
        preferred_tone=value.preferred_tone,
        themes=list(value.themes),
        risks=list(value.risks),
    )


def _handoff_out(value: HandoffNote) -> HandoffNoteOut:
    return HandoffNoteOut(
        id=value.id,
        queue_item_ref=value.queue_item_ref,
        summary=value.summary,
        owner=value.owner,
        due_time=value.due_time,
        escalation_status=value.escalation_status,
        status=value.status,
        evidence_refs=_evidence_out(value.evidence_refs),
    )


def _person_detail_out(value: PersonDetail) -> PersonDetailOut:
    return PersonDetailOut(
        profile=_person_out(value.profile),
        commitments=[_commitment_out(item) for item in value.commitments],
        drafts=[_draft_out(item) for item in value.drafts],
        queue_items=[_queue_out(item) for item in value.queue_items],
        handoffs=[_handoff_out(item) for item in value.handoffs],
        evidence_refs=_evidence_out(value.evidence_refs),
    )


@router.get("/brief", response_model=BriefResponse)
def get_brief(
    limit: int = Query(default=20, ge=1, le=100),
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> BriefResponse:
    service = build_product_service(container)
    items = service.list_brief_items(principal_id=context.principal_id, limit=limit)
    return BriefResponse(generated_at=_now_iso(), items=[_brief_out(item) for item in items], total=len(items))


@router.get("/queue", response_model=QueueResponse)
def get_queue(
    limit: int = Query(default=30, ge=1, le=100),
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> QueueResponse:
    service = build_product_service(container)
    items = service.list_queue(principal_id=context.principal_id, limit=limit)
    return QueueResponse(generated_at=_now_iso(), items=[_queue_out(item) for item in items], total=len(items))


@router.post("/queue/{item_ref:path}/resolve", response_model=DecisionQueueItemOut)
def resolve_queue_item(
    item_ref: str,
    body: QueueResolveIn,
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> DecisionQueueItemOut:
    service = build_product_service(container)
    actor = str(context.operator_id or context.access_email or context.principal_id or "product").strip()
    updated = service.resolve_queue_item(
        principal_id=context.principal_id,
        item_ref=item_ref,
        action=body.action,
        actor=actor,
        reason=body.reason,
        due_at=body.due_at,
    )
    if updated is None:
        raise HTTPException(status_code=404, detail="queue_item_not_found")
    return _queue_out(updated)


@router.get("/commitments", response_model=list[CommitmentOut])
def list_commitments(
    limit: int = Query(default=50, ge=1, le=200),
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> list[CommitmentOut]:
    service = build_product_service(container)
    return [_commitment_out(item) for item in service.list_commitments(principal_id=context.principal_id, limit=limit)]


@router.get("/commitments/{commitment_ref:path}", response_model=CommitmentOut)
def get_commitment(
    commitment_ref: str,
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> CommitmentOut:
    service = build_product_service(container)
    found = service.get_commitment(principal_id=context.principal_id, commitment_ref=commitment_ref)
    if found is None:
        raise HTTPException(status_code=404, detail="commitment_not_found")
    return _commitment_out(found)


@router.get("/drafts", response_model=list[DraftCandidateOut])
def list_drafts(
    limit: int = Query(default=20, ge=1, le=100),
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> list[DraftCandidateOut]:
    service = build_product_service(container)
    return [_draft_out(item) for item in service.list_drafts(principal_id=context.principal_id, limit=limit)]


@router.post("/drafts/{draft_ref:path}/approve", response_model=DraftCandidateOut)
def approve_draft(
    draft_ref: str,
    body: DraftApproveIn,
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> DraftCandidateOut:
    service = build_product_service(container)
    actor = str(context.operator_id or context.access_email or context.principal_id or "product").strip()
    approved = service.approve_draft(
        principal_id=context.principal_id,
        draft_ref=draft_ref,
        decided_by=actor,
        reason=body.reason,
    )
    if approved is None:
        raise HTTPException(status_code=404, detail="draft_not_found")
    return _draft_out(approved)


@router.get("/people", response_model=list[PersonProfileOut])
def list_people(
    limit: int = Query(default=25, ge=1, le=200),
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> list[PersonProfileOut]:
    service = build_product_service(container)
    return [_person_out(item) for item in service.list_people(principal_id=context.principal_id, limit=limit)]


@router.get("/people/{person_id}", response_model=PersonProfileOut)
def get_person(
    person_id: str,
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> PersonProfileOut:
    service = build_product_service(container)
    found = service.get_person(principal_id=context.principal_id, person_id=person_id)
    if found is None:
        raise HTTPException(status_code=404, detail="person_not_found")
    return _person_out(found)


@router.get("/people/{person_id}/detail", response_model=PersonDetailOut)
def get_person_detail(
    person_id: str,
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> PersonDetailOut:
    service = build_product_service(container)
    found = service.get_person_detail(principal_id=context.principal_id, person_id=person_id)
    if found is None:
        raise HTTPException(status_code=404, detail="person_not_found")
    return _person_detail_out(found)


@router.get("/handoffs", response_model=list[HandoffNoteOut])
def list_handoffs(
    limit: int = Query(default=20, ge=1, le=100),
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> list[HandoffNoteOut]:
    service = build_product_service(container)
    return [_handoff_out(item) for item in service.list_handoffs(principal_id=context.principal_id, limit=limit)]


@router.get("/diagnostics", response_model=WorkspaceDiagnosticsOut)
def get_workspace_diagnostics(
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> WorkspaceDiagnosticsOut:
    service = build_product_service(container)
    return WorkspaceDiagnosticsOut(**service.workspace_diagnostics(principal_id=context.principal_id))
