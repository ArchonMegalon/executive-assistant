from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.dependencies import RequestContext, get_container, get_request_context
from app.api.routes.product_api_contracts import (
    BriefResponse,
    CommitmentCandidateOut,
    CommitmentCandidateReviewIn,
    CommitmentCandidateStageIn,
    CommitmentCreateIn,
    CommitmentExtractIn,
    CommitmentOut,
    DecisionItemOut,
    DecisionQueueItemOut,
    DecisionResponse,
    DraftApproveIn,
    DraftCandidateOut,
    EvidenceItemOut,
    EvidenceResponse,
    HandoffAssignIn,
    HandoffCompleteIn,
    HandoffNoteOut,
    HistoryEntryOut,
    PersonCorrectionIn,
    PersonDetailOut,
    PersonProfileOut,
    QueueResolveIn,
    QueueResponse,
    RuleItemOut,
    RuleResponse,
    RuleSimulateIn,
    ThreadItemOut,
    ThreadResponse,
    WorkspaceDiagnosticsOut,
    WorkspacePlanDetailOut,
    WorkspaceSupportBundleOut,
    WorkspaceUsageDetailOut,
    brief_out,
    commitment_candidate_out,
    commitment_out,
    decision_out,
    draft_out,
    evidence_item_out,
    handoff_out,
    history_out,
    now_iso,
    person_detail_out,
    person_out,
    queue_out,
    rule_out,
    thread_out,
)
from app.container import AppContainer
from app.product.service import build_product_service

router = APIRouter(prefix="/app/api", tags=["product"])

@router.get("/brief", response_model=BriefResponse)
def get_brief(
    limit: int = Query(default=20, ge=1, le=100),
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> BriefResponse:
    service = build_product_service(container)
    items = service.list_brief_items(
        principal_id=context.principal_id,
        limit=limit,
        operator_id=str(context.operator_id or "").strip(),
    )
    return BriefResponse(generated_at=now_iso(), items=[brief_out(item) for item in items], total=len(items))


@router.get("/queue", response_model=QueueResponse)
def get_queue(
    limit: int = Query(default=30, ge=1, le=100),
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> QueueResponse:
    service = build_product_service(container)
    items = service.list_queue(
        principal_id=context.principal_id,
        limit=limit,
        operator_id=str(context.operator_id or "").strip(),
    )
    return QueueResponse(generated_at=now_iso(), items=[queue_out(item) for item in items], total=len(items))


@router.get("/decisions", response_model=DecisionResponse)
def list_decisions(
    limit: int = Query(default=20, ge=1, le=100),
    include_closed: bool = Query(default=False),
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> DecisionResponse:
    service = build_product_service(container)
    items = service.list_decisions(principal_id=context.principal_id, limit=limit, include_closed=include_closed)
    return DecisionResponse(generated_at=now_iso(), items=[decision_out(item) for item in items], total=len(items))


@router.get("/decisions/{decision_ref:path}", response_model=DecisionItemOut)
def get_decision(
    decision_ref: str,
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> DecisionItemOut:
    service = build_product_service(container)
    found = service.get_decision(principal_id=context.principal_id, decision_ref=decision_ref)
    if found is None:
        raise HTTPException(status_code=404, detail="decision_not_found")
    return decision_out(found)


@router.post("/decisions/{decision_ref:path}/resolve", response_model=DecisionItemOut)
def resolve_decision(
    decision_ref: str,
    body: QueueResolveIn,
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> DecisionItemOut:
    service = build_product_service(container)
    actor = str(context.operator_id or context.access_email or context.principal_id or "product").strip()
    updated = service.resolve_decision(
        principal_id=context.principal_id,
        decision_ref=decision_ref,
        actor=actor,
        action=body.action,
        reason=body.reason,
        due_at=body.due_at,
    )
    if updated is None:
        raise HTTPException(status_code=404, detail="decision_not_found")
    return decision_out(updated)


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
        reason_code=body.reason_code,
        due_at=body.due_at,
    )
    if updated is None:
        raise HTTPException(status_code=404, detail="queue_item_not_found")
    return queue_out(updated)


@router.get("/threads", response_model=ThreadResponse)
def list_threads(
    limit: int = Query(default=20, ge=1, le=100),
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> ThreadResponse:
    service = build_product_service(container)
    items = service.list_threads(principal_id=context.principal_id, limit=limit)
    return ThreadResponse(generated_at=now_iso(), items=[thread_out(item) for item in items], total=len(items))


@router.get("/threads/{thread_ref:path}", response_model=ThreadItemOut)
def get_thread(
    thread_ref: str,
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> ThreadItemOut:
    service = build_product_service(container)
    found = service.get_thread(principal_id=context.principal_id, thread_ref=thread_ref)
    if found is None:
        raise HTTPException(status_code=404, detail="thread_not_found")
    return thread_out(found)


@router.get("/commitments", response_model=list[CommitmentOut])
def list_commitments(
    limit: int = Query(default=50, ge=1, le=200),
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> list[CommitmentOut]:
    service = build_product_service(container)
    return [commitment_out(item) for item in service.list_commitments(principal_id=context.principal_id, limit=limit)]


@router.post("/commitments", response_model=CommitmentOut)
def create_commitment(
    body: CommitmentCreateIn,
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> CommitmentOut:
    service = build_product_service(container)
    created = service.create_commitment(
        principal_id=context.principal_id,
        title=body.title,
        details=body.details,
        due_at=body.due_at,
        priority=body.priority,
        counterparty=body.counterparty,
        owner=body.owner,
        kind=body.kind,
        stakeholder_id=body.stakeholder_id,
        channel_hint=body.channel_hint,
    )
    return commitment_out(created)


@router.post("/commitments/extract", response_model=list[CommitmentCandidateOut])
def extract_commitments(
    body: CommitmentExtractIn,
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> list[CommitmentCandidateOut]:
    service = build_product_service(container)
    rows = service.extract_commitments(
        text=body.text,
        counterparty=body.counterparty,
        due_at=body.due_at,
    )
    return [commitment_candidate_out(row) for row in rows]


@router.get("/commitments/candidates", response_model=list[CommitmentCandidateOut])
def list_commitment_candidates(
    limit: int = Query(default=20, ge=1, le=100),
    status: str | None = Query(default=None),
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> list[CommitmentCandidateOut]:
    service = build_product_service(container)
    return [
        commitment_candidate_out(row)
        for row in service.list_commitment_candidates(principal_id=context.principal_id, limit=limit, status=status)
    ]


@router.post("/commitments/candidates/stage", response_model=list[CommitmentCandidateOut])
def stage_commitment_candidates(
    body: CommitmentCandidateStageIn,
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> list[CommitmentCandidateOut]:
    service = build_product_service(container)
    rows = service.stage_extracted_commitments(
        principal_id=context.principal_id,
        text=body.text,
        counterparty=body.counterparty,
        due_at=body.due_at,
        kind=body.kind,
        stakeholder_id=body.stakeholder_id,
    )
    return [commitment_candidate_out(row) for row in rows]


@router.post("/commitments/candidates/{candidate_id}/accept", response_model=CommitmentOut)
def accept_commitment_candidate(
    candidate_id: str,
    body: CommitmentCandidateReviewIn,
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> CommitmentOut:
    service = build_product_service(container)
    created = service.accept_commitment_candidate(
        principal_id=context.principal_id,
        candidate_id=candidate_id,
        reviewer=body.reviewer,
        title=body.title,
        details=body.details,
        due_at=body.due_at,
        counterparty=body.counterparty,
        kind=body.kind,
        stakeholder_id=body.stakeholder_id,
    )
    if created is None:
        raise HTTPException(status_code=404, detail="commitment_candidate_not_found")
    return commitment_out(created)


@router.post("/commitments/candidates/{candidate_id}/reject", response_model=CommitmentCandidateOut)
def reject_commitment_candidate(
    candidate_id: str,
    body: CommitmentCandidateReviewIn,
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> CommitmentCandidateOut:
    service = build_product_service(container)
    rejected = service.reject_commitment_candidate(principal_id=context.principal_id, candidate_id=candidate_id, reviewer=body.reviewer)
    if rejected is None:
        raise HTTPException(status_code=404, detail="commitment_candidate_not_found")
    return commitment_candidate_out(rejected)


@router.get("/commitments/{commitment_ref:path}/history", response_model=list[HistoryEntryOut])
def get_commitment_history(
    commitment_ref: str,
    limit: int = Query(default=20, ge=1, le=100),
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> list[HistoryEntryOut]:
    service = build_product_service(container)
    found = service.get_commitment(principal_id=context.principal_id, commitment_ref=commitment_ref)
    if found is None:
        raise HTTPException(status_code=404, detail="commitment_not_found")
    return [history_out(item) for item in service.get_commitment_history(principal_id=context.principal_id, commitment_ref=commitment_ref, limit=limit)]


@router.post("/commitments/{commitment_ref:path}/resolve", response_model=CommitmentOut)
def resolve_commitment(
    commitment_ref: str,
    body: QueueResolveIn,
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> CommitmentOut:
    service = build_product_service(container)
    actor = str(context.operator_id or context.access_email or context.principal_id or "product").strip()
    updated = service.resolve_commitment(
        principal_id=context.principal_id,
        commitment_ref=commitment_ref,
        action=body.action,
        actor=actor,
        reason=body.reason,
        reason_code=body.reason_code,
        due_at=body.due_at,
    )
    if updated is None:
        raise HTTPException(status_code=404, detail="commitment_not_found")
    return commitment_out(updated)


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
    return commitment_out(found)


@router.get("/drafts", response_model=list[DraftCandidateOut])
def list_drafts(
    limit: int = Query(default=20, ge=1, le=100),
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> list[DraftCandidateOut]:
    service = build_product_service(container)
    return [draft_out(item) for item in service.list_drafts(principal_id=context.principal_id, limit=limit)]


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
    return draft_out(approved)


@router.post("/drafts/{draft_ref:path}/reject", response_model=DraftCandidateOut)
def reject_draft(
    draft_ref: str,
    body: DraftApproveIn,
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> DraftCandidateOut:
    service = build_product_service(container)
    actor = str(context.operator_id or context.access_email or context.principal_id or "product").strip()
    rejected = service.reject_draft(
        principal_id=context.principal_id,
        draft_ref=draft_ref,
        decided_by=actor,
        reason=body.reason,
    )
    if rejected is None:
        raise HTTPException(status_code=404, detail="draft_not_found")
    return draft_out(rejected)


@router.get("/people", response_model=list[PersonProfileOut])
def list_people(
    limit: int = Query(default=25, ge=1, le=200),
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> list[PersonProfileOut]:
    service = build_product_service(container)
    return [person_out(item) for item in service.list_people(principal_id=context.principal_id, limit=limit)]


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
    return person_out(found)


@router.get("/people/{person_id}/detail", response_model=PersonDetailOut)
def get_person_detail(
    person_id: str,
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> PersonDetailOut:
    service = build_product_service(container)
    found = service.get_person_detail(
        principal_id=context.principal_id,
        person_id=person_id,
        operator_id=str(context.operator_id or "").strip(),
    )
    if found is None:
        raise HTTPException(status_code=404, detail="person_not_found")
    return person_detail_out(found)


@router.post("/people/{person_id}/correct", response_model=PersonDetailOut)
def correct_person(
    person_id: str,
    body: PersonCorrectionIn,
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> PersonDetailOut:
    service = build_product_service(container)
    found = service.correct_person_profile(
        principal_id=context.principal_id,
        person_id=person_id,
        preferred_tone=body.preferred_tone,
        add_theme=body.add_theme,
        remove_theme=body.remove_theme,
        add_risk=body.add_risk,
        remove_risk=body.remove_risk,
    )
    if found is None:
        raise HTTPException(status_code=404, detail="person_not_found")
    return person_detail_out(found)


@router.get("/people/{person_id}/history", response_model=list[HistoryEntryOut])
def get_person_history(
    person_id: str,
    limit: int = Query(default=20, ge=1, le=100),
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> list[HistoryEntryOut]:
    service = build_product_service(container)
    found = service.get_person(principal_id=context.principal_id, person_id=person_id)
    if found is None:
        raise HTTPException(status_code=404, detail="person_not_found")
    return [history_out(item) for item in service.get_person_history(principal_id=context.principal_id, person_id=person_id, limit=limit)]


@router.get("/handoffs", response_model=list[HandoffNoteOut])
def list_handoffs(
    status: str | None = Query(default="pending"),
    limit: int = Query(default=20, ge=1, le=100),
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> list[HandoffNoteOut]:
    service = build_product_service(container)
    return [
        handoff_out(item)
        for item in service.list_handoffs(
            principal_id=context.principal_id,
            limit=limit,
            operator_id=str(context.operator_id or "").strip(),
            status=status,
        )
    ]


@router.get("/handoffs/{handoff_ref:path}", response_model=HandoffNoteOut)
def get_handoff(
    handoff_ref: str,
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> HandoffNoteOut:
    service = build_product_service(container)
    found = service.get_handoff(principal_id=context.principal_id, handoff_ref=handoff_ref)
    if found is None:
        raise HTTPException(status_code=404, detail="handoff_not_found")
    return handoff_out(found)


@router.post("/handoffs/{handoff_ref:path}/assign", response_model=HandoffNoteOut)
def assign_handoff(
    handoff_ref: str,
    body: HandoffAssignIn,
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> HandoffNoteOut:
    service = build_product_service(container)
    actor = str(context.operator_id or context.access_email or context.principal_id or body.operator_id).strip()
    updated = service.assign_handoff(
        principal_id=context.principal_id,
        handoff_ref=handoff_ref,
        operator_id=body.operator_id,
        actor=actor,
    )
    if updated is None:
        raise HTTPException(status_code=404, detail="handoff_not_assignable")
    return handoff_out(updated)


@router.post("/handoffs/{handoff_ref:path}/complete", response_model=HandoffNoteOut)
def complete_handoff(
    handoff_ref: str,
    body: HandoffCompleteIn,
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> HandoffNoteOut:
    service = build_product_service(container)
    actor = str(context.operator_id or context.access_email or context.principal_id or body.operator_id).strip()
    updated = service.complete_handoff(
        principal_id=context.principal_id,
        handoff_ref=handoff_ref,
        operator_id=body.operator_id,
        actor=actor,
        resolution=body.resolution,
    )
    if updated is None:
        raise HTTPException(status_code=404, detail="handoff_not_completable")
    return handoff_out(updated)


@router.get("/diagnostics", response_model=WorkspaceDiagnosticsOut)
def get_workspace_diagnostics(
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> WorkspaceDiagnosticsOut:
    service = build_product_service(container)
    return WorkspaceDiagnosticsOut(**service.workspace_diagnostics(principal_id=context.principal_id))


@router.get("/plan", response_model=WorkspacePlanDetailOut)
def get_workspace_plan_detail(
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> WorkspacePlanDetailOut:
    service = build_product_service(container)
    diagnostics = service.workspace_diagnostics(principal_id=context.principal_id)
    service.record_surface_event(
        principal_id=context.principal_id,
        event_type="plan_opened",
        surface="plan_api",
        actor=str(context.operator_id or context.access_email or context.principal_id or "browser").strip(),
    )
    return WorkspacePlanDetailOut(
        workspace=dict(diagnostics.get("workspace") or {}),
        selected_channels=[str(value) for value in (diagnostics.get("selected_channels") or []) if str(value).strip()],
        plan=dict(diagnostics.get("plan") or {}),
        billing=dict(diagnostics.get("billing") or {}),
        entitlements=dict(diagnostics.get("entitlements") or {}),
        commercial=dict(diagnostics.get("commercial") or {}),
        operators=dict(diagnostics.get("operators") or {}),
    )


@router.get("/usage", response_model=WorkspaceUsageDetailOut)
def get_workspace_usage_detail(
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> WorkspaceUsageDetailOut:
    service = build_product_service(container)
    service.record_surface_event(
        principal_id=context.principal_id,
        event_type="usage_opened",
        surface="usage_api",
        actor=str(context.operator_id or context.access_email or context.principal_id or "browser").strip(),
    )
    diagnostics = service.workspace_diagnostics(principal_id=context.principal_id)
    return WorkspaceUsageDetailOut(
        workspace=dict(diagnostics.get("workspace") or {}),
        selected_channels=[str(value) for value in (diagnostics.get("selected_channels") or []) if str(value).strip()],
        usage={str(key): int(value or 0) for key, value in dict(diagnostics.get("usage") or {}).items()},
        analytics=dict(diagnostics.get("analytics") or {}),
        readiness=dict(diagnostics.get("readiness") or {}),
        operators=dict(diagnostics.get("operators") or {}),
    )


@router.get("/evidence", response_model=EvidenceResponse)
def list_evidence(
    limit: int = Query(default=40, ge=1, le=200),
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> EvidenceResponse:
    service = build_product_service(container)
    items = service.list_evidence(
        principal_id=context.principal_id,
        limit=limit,
        operator_id=str(context.operator_id or "").strip(),
    )
    return EvidenceResponse(generated_at=now_iso(), items=[evidence_item_out(item) for item in items], total=len(items))


@router.get("/evidence/{evidence_ref:path}", response_model=EvidenceItemOut)
def get_evidence(
    evidence_ref: str,
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> EvidenceItemOut:
    service = build_product_service(container)
    found = service.get_evidence(
        principal_id=context.principal_id,
        evidence_ref=evidence_ref,
        operator_id=str(context.operator_id or "").strip(),
    )
    if found is None:
        raise HTTPException(status_code=404, detail="evidence_not_found")
    return evidence_item_out(found)


@router.get("/rules", response_model=RuleResponse)
def list_rules(
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> RuleResponse:
    service = build_product_service(container)
    items = service.list_rules(principal_id=context.principal_id)
    return RuleResponse(generated_at=now_iso(), items=[rule_out(item) for item in items], total=len(items))


@router.get("/rules/{rule_id:path}", response_model=RuleItemOut)
def get_rule(
    rule_id: str,
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> RuleItemOut:
    service = build_product_service(container)
    found = service.get_rule(principal_id=context.principal_id, rule_id=rule_id)
    if found is None:
        raise HTTPException(status_code=404, detail="rule_not_found")
    return rule_out(found)


@router.post("/rules/{rule_id:path}/simulate", response_model=RuleItemOut)
def simulate_rule(
    rule_id: str,
    body: RuleSimulateIn,
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> RuleItemOut:
    service = build_product_service(container)
    found = service.simulate_rule(principal_id=context.principal_id, rule_id=rule_id, proposed_value=body.proposed_value)
    if found is None:
        raise HTTPException(status_code=404, detail="rule_not_found")
    return rule_out(found)


@router.get("/diagnostics/export", response_model=WorkspaceSupportBundleOut)
def export_workspace_support_bundle(
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> WorkspaceSupportBundleOut:
    service = build_product_service(container)
    service.record_surface_event(
        principal_id=context.principal_id,
        event_type="support_bundle_opened",
        surface="diagnostics_export",
        actor=str(context.operator_id or context.access_email or context.principal_id or "browser").strip(),
    )
    return WorkspaceSupportBundleOut(**service.workspace_support_bundle(principal_id=context.principal_id))


@router.get("/support", response_model=WorkspaceSupportBundleOut)
def get_workspace_support_detail(
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> WorkspaceSupportBundleOut:
    service = build_product_service(container)
    service.record_surface_event(
        principal_id=context.principal_id,
        event_type="support_opened",
        surface="support_api",
        actor=str(context.operator_id or context.access_email or context.principal_id or "browser").strip(),
    )
    return WorkspaceSupportBundleOut(**service.workspace_support_bundle(principal_id=context.principal_id))

@router.get("/people/{person_id}/detail/history", response_model=list[HistoryEntryOut])
def get_person_detail_history(
    person_id: str,
    *,
    context: RequestContext = Depends(get_request_context),
    container: AppContainer = Depends(get_container),
    limit: int = Query(default=20, ge=1, le=100),
) -> list[HistoryEntryOut]:
    service = build_product_service(container)
    person = service.get_person(principal_id=context.principal_id, person_id=person_id)
    if person is None:
        raise HTTPException(status_code=404, detail="person_not_found")
    return [HistoryEntryOut(**value.__dict__) for value in service.get_person_history(principal_id=context.principal_id, person_id=person_id, limit=limit)]

@router.get("/commitment-candidates/{candidate_id}", response_model=CommitmentCandidateOut)
def get_commitment_candidate(
    candidate_id: str,
    *,
    context: RequestContext = Depends(get_request_context),
    container: AppContainer = Depends(get_container),
) -> CommitmentCandidateOut:
    service = build_product_service(container)
    found = service.get_commitment_candidate(principal_id=context.principal_id, candidate_id=candidate_id)
    if found is None:
        raise HTTPException(status_code=404, detail="commitment_candidate_not_found")
    return commitment_candidate_out(found)
