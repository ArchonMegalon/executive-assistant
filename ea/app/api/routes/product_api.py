from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from app.api.dependencies import RequestContext, get_container, get_request_context
from app.api.routes.product_api_contracts import (
    BriefResponse,
    CommitmentCandidateOut,
    CommitmentCandidateReviewIn,
    CommitmentCandidateStageIn,
    CommitmentCreateIn,
    CommitmentExtractIn,
    CommitmentOut,
    DeadlineOut,
    DeadlineResponse,
    DecisionItemOut,
    DecisionQueueItemOut,
    DecisionResponse,
    DraftApproveIn,
    DraftCandidateOut,
    EvidenceItemOut,
    EvidenceResponse,
    HandoffAssignIn,
    HandoffAssignmentHistoryOut,
    HandoffCompleteIn,
    HandoffNoteOut,
    HistoryEntryOut,
    OperatorCenterActionOut,
    OperatorCenterLaneOut,
    OperatorCenterOut,
    PersonCorrectionIn,
    PreferenceCorrectionApplyIn,
    PreferenceCorrectionApplyOut,
    PreferenceDecisionAssessmentIn,
    PreferenceDecisionAssessmentOut,
    PreferenceEvidenceApplyOut,
    PreferenceEvidenceEventIn,
    PreferenceLearningSummaryOut,
    PreferenceNodeArchiveIn,
    PreferenceNodeOut,
    PreferenceNodeUpsertIn,
    PreferenceProfileBundleOut,
    PreferenceProfileSummaryOut,
    PropertyFeedbackRecordIn,
    PropertyFeedbackRecordOut,
    PropertyFeedbackSuggestionRequestIn,
    PropertyFeedbackSuggestionSetOut,
    PreferenceProfileUpsertIn,
    PersonDetailOut,
    PersonProfileOut,
    QueueResolveIn,
    QueueResponse,
    SearchResponse,
    SearchResultOut,
    WorkspaceInvitationAcceptIn,
    WorkspaceAccessSessionCreateIn,
    WorkspaceAccessSessionOut,
    WorkspaceAccessSessionResponse,
    WorkspaceInvitationCreateIn,
    WorkspaceInvitationOut,
    WorkspaceInvitationResponse,
    RuleItemOut,
    RuleResponse,
    RuleSimulateIn,
    ThreadItemOut,
    ThreadResponse,
    WorkspaceDiagnosticsOut,
    WorkspacePlanDetailOut,
    WorkspaceOutcomesOut,
    WorkspaceSupportBundleOut,
    WorkspaceTrustOut,
    WorkspaceUsageDetailOut,
    brief_out,
    commitment_candidate_out,
    commitment_out,
    deadline_out,
    decision_out,
    draft_out,
    evidence_item_out,
    handoff_assignment_history_out,
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
from app.product.service import _property_feedback_reason_map, build_product_service

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


@router.get("/search", response_model=SearchResponse)
def search_workspace(
    q: str = Query(default="", alias="query"),
    limit: int = Query(default=20, ge=1, le=100),
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> SearchResponse:
    service = build_product_service(container)
    items = service.search_workspace(
        principal_id=context.principal_id,
        query=q,
        limit=limit,
        operator_id=str(context.operator_id or "").strip(),
    )
    if str(q or "").strip():
        service.record_surface_event(
            principal_id=context.principal_id,
            event_type="workspace_search_performed",
            surface="search_api",
            actor=str(context.operator_id or context.access_email or context.principal_id or "browser").strip(),
            metadata={"query": str(q or "").strip()[:80], "result_total": len(items)},
        )
    return SearchResponse(generated_at=now_iso(), items=[SearchResultOut(**item) for item in items], total=len(items))


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


@router.get("/decisions/{decision_ref:path}/history", response_model=list[HistoryEntryOut])
def get_decision_history(
    decision_ref: str,
    limit: int = Query(default=20, ge=1, le=100),
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> list[HistoryEntryOut]:
    service = build_product_service(container)
    found = service.get_decision(principal_id=context.principal_id, decision_ref=decision_ref)
    if found is None:
        raise HTTPException(status_code=404, detail="decision_not_found")
    return [history_out(item) for item in service.get_decision_history(principal_id=context.principal_id, decision_ref=decision_ref, limit=limit)]


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


@router.get("/deadlines", response_model=DeadlineResponse)
def list_deadlines(
    limit: int = Query(default=20, ge=1, le=100),
    include_closed: bool = Query(default=False),
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> DeadlineResponse:
    service = build_product_service(container)
    items = service.list_deadlines(principal_id=context.principal_id, limit=limit, include_closed=include_closed)
    return DeadlineResponse(generated_at=now_iso(), items=[deadline_out(item) for item in items], total=len(items))


@router.get("/deadlines/{deadline_ref:path}/history", response_model=list[HistoryEntryOut])
def get_deadline_history(
    deadline_ref: str,
    limit: int = Query(default=20, ge=1, le=100),
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> list[HistoryEntryOut]:
    service = build_product_service(container)
    found = service.get_deadline(principal_id=context.principal_id, deadline_ref=deadline_ref)
    if found is None:
        raise HTTPException(status_code=404, detail="deadline_not_found")
    return [history_out(item) for item in service.get_deadline_history(principal_id=context.principal_id, deadline_ref=deadline_ref, limit=limit)]


@router.get("/deadlines/{deadline_ref:path}", response_model=DeadlineOut)
def get_deadline(
    deadline_ref: str,
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> DeadlineOut:
    service = build_product_service(container)
    found = service.get_deadline(principal_id=context.principal_id, deadline_ref=deadline_ref)
    if found is None:
        raise HTTPException(status_code=404, detail="deadline_not_found")
    return deadline_out(found)


@router.post("/deadlines/{deadline_ref:path}/resolve", response_model=DeadlineOut)
def resolve_deadline(
    deadline_ref: str,
    body: QueueResolveIn,
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> DeadlineOut:
    service = build_product_service(container)
    actor = str(context.operator_id or context.access_email or context.principal_id or "product").strip()
    updated = service.resolve_deadline(
        principal_id=context.principal_id,
        deadline_ref=deadline_ref,
        actor=actor,
        action=body.action,
        reason=body.reason,
        due_at=body.due_at,
    )
    if updated is None:
        raise HTTPException(status_code=404, detail="deadline_not_found")
    return deadline_out(updated)


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


@router.get("/threads/{thread_ref:path}/history", response_model=list[HistoryEntryOut])
def get_thread_history(
    thread_ref: str,
    limit: int = Query(default=20, ge=1, le=100),
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> list[HistoryEntryOut]:
    service = build_product_service(container)
    if service.get_thread(principal_id=context.principal_id, thread_ref=thread_ref) is None:
        raise HTTPException(status_code=404, detail="thread_not_found")
    return [history_out(item) for item in service.get_thread_history(principal_id=context.principal_id, thread_ref=thread_ref, limit=limit)]


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


@router.post("/threads/{thread_ref:path}/resume-delivery", response_model=HandoffNoteOut)
def resume_thread_delivery(
    thread_ref: str,
    body: HandoffAssignIn,
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> HandoffNoteOut:
    service = build_product_service(container)
    actor = str(context.operator_id or context.access_email or context.principal_id or body.operator_id or "product").strip()
    try:
        reopened = service.resume_thread_delivery_followup(
            principal_id=context.principal_id,
            thread_ref=thread_ref,
            actor=actor,
            operator_id=body.operator_id,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if reopened is None:
        raise HTTPException(status_code=404, detail="thread_not_found")
    return handoff_out(reopened)


@router.get("/commitments", response_model=list[CommitmentOut])
def list_commitments(
    limit: int = Query(default=50, ge=1, le=200),
    include_closed: bool = Query(default=False),
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> list[CommitmentOut]:
    service = build_product_service(container)
    return [
        commitment_out(item)
        for item in service.list_commitments(principal_id=context.principal_id, limit=limit, include_closed=include_closed)
    ]


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


@router.get("/people/{person_id}/preference-profile", response_model=PreferenceProfileBundleOut)
def get_preference_profile(
    person_id: str,
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> PreferenceProfileBundleOut:
    service = build_product_service(container)
    return PreferenceProfileBundleOut(**service.get_preference_profile(principal_id=context.principal_id, person_id=person_id))


@router.post("/people/{person_id}/preference-profile", response_model=PreferenceProfileSummaryOut)
def upsert_preference_profile(
    person_id: str,
    body: PreferenceProfileUpsertIn,
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> PreferenceProfileSummaryOut:
    service = build_product_service(container)
    return PreferenceProfileSummaryOut(
        **service.upsert_preference_profile(
            principal_id=context.principal_id,
            person_id=person_id,
            display_name=body.display_name,
            profile_scope=body.profile_scope,
            consent_mode=body.consent_mode,
            learning_enabled=body.learning_enabled,
            high_stakes_domains_enabled=body.high_stakes_domains_enabled,
        )
    )


@router.post("/people/{person_id}/preference-profile/nodes", response_model=PreferenceNodeOut)
def upsert_preference_node(
    person_id: str,
    body: PreferenceNodeUpsertIn,
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> PreferenceNodeOut:
    service = build_product_service(container)
    return PreferenceNodeOut(
        **service.upsert_preference_node(
            principal_id=context.principal_id,
            person_id=person_id,
            domain=body.domain,
            category=body.category,
            key=body.key,
            value_json=body.value_json,
            strength=body.strength,
            confidence=body.confidence,
            source_mode=body.source_mode,
            status=body.status,
            decay_policy=body.decay_policy,
        )
    )


@router.post("/people/{person_id}/preference-profile/nodes/{node_id}/archive", response_model=PreferenceCorrectionApplyOut)
def archive_preference_node(
    person_id: str,
    node_id: str,
    body: PreferenceNodeArchiveIn | None = None,
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> PreferenceCorrectionApplyOut:
    service = build_product_service(container)
    actor = str(context.operator_id or context.access_email or context.principal_id or "browser").strip()
    try:
        result = service.archive_preference_node(
            principal_id=context.principal_id,
            person_id=person_id,
            node_id=node_id,
            reason=(body.reason if body is not None else ""),
            corrected_by=actor,
        )
    except KeyError:
        raise HTTPException(status_code=404, detail="preference_node_not_found")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return PreferenceCorrectionApplyOut(**result)


@router.post("/people/{person_id}/preference-profile/corrections", response_model=PreferenceCorrectionApplyOut)
def apply_preference_correction(
    person_id: str,
    body: PreferenceCorrectionApplyIn,
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> PreferenceCorrectionApplyOut:
    service = build_product_service(container)
    actor = str(context.operator_id or context.access_email or context.principal_id or "browser").strip()
    return PreferenceCorrectionApplyOut(
        **service.apply_preference_correction(
            principal_id=context.principal_id,
            person_id=person_id,
            domain=body.domain,
            category=body.category,
            key=body.key,
            value_json=body.value_json,
            strength=body.strength,
            reason=body.reason,
            corrected_by=actor,
        )
    )


@router.post("/people/{person_id}/preference-profile/evidence", response_model=PreferenceEvidenceApplyOut)
def record_preference_evidence(
    person_id: str,
    body: PreferenceEvidenceEventIn,
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> PreferenceEvidenceApplyOut:
    service = build_product_service(container)
    return PreferenceEvidenceApplyOut(
        **service.record_preference_evidence(
            principal_id=context.principal_id,
            person_id=person_id,
            domain=body.domain,
            event_type=body.event_type,
            object_type=body.object_type,
            object_id=body.object_id,
            source_ref=body.source_ref,
            raw_signal_json=dict(body.raw_signal_json or {}),
            interpreted_signal_json=dict(body.interpreted_signal_json or {}),
            signal_strength=body.signal_strength,
            reversible=body.reversible,
        )
    )


@router.post("/people/{person_id}/preference-profile/assessments", response_model=PreferenceDecisionAssessmentOut)
def assess_preference_candidate(
    person_id: str,
    body: PreferenceDecisionAssessmentIn,
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> PreferenceDecisionAssessmentOut:
    service = build_product_service(container)
    result = service.assess_preference_candidate(
        principal_id=context.principal_id,
        person_id=person_id,
        domain=body.domain,
        object_type=body.object_type,
        object_id=body.object_id,
        object_payload=dict(body.object_payload or {}),
    )
    if result is None:
        raise HTTPException(status_code=404, detail="preference_profile_not_found")
    return PreferenceDecisionAssessmentOut(**result)


@router.get("/people/{person_id}/preference-profile/learning-summary", response_model=PreferenceLearningSummaryOut)
def get_preference_learning_summary(
    person_id: str,
    domain: str = Query(default="willhaben", min_length=1),
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> PreferenceLearningSummaryOut:
    service = build_product_service(container)
    return PreferenceLearningSummaryOut(
        **service.property_feedback_learning_summary(
            principal_id=context.principal_id,
            person_id=person_id,
            domain=domain,
        )
    )


@router.post("/people/{person_id}/preference-profile/property-feedback/suggestions", response_model=PropertyFeedbackSuggestionSetOut)
def get_property_feedback_suggestions(
    person_id: str,
    body: PropertyFeedbackSuggestionRequestIn,
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> PropertyFeedbackSuggestionSetOut:
    service = build_product_service(container)
    return PropertyFeedbackSuggestionSetOut(
        **service.property_feedback_suggestions(
            property_facts=dict(body.property_facts or {}),
            assessment=dict(body.assessment or {}) if body.assessment else None,
        )
    )


@router.post("/people/{person_id}/preference-profile/property-feedback", response_model=PropertyFeedbackRecordOut)
def record_property_feedback(
    person_id: str,
    body: PropertyFeedbackRecordIn,
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> PropertyFeedbackRecordOut:
    service = build_product_service(container)
    actor = str(body.actor or context.operator_id or context.access_email or context.principal_id or "browser").strip()
    allowed_reason_keys = set(_property_feedback_reason_map().keys())
    normalized_reason_keys = [
        str(item or "").strip().lower()
        for item in list(body.reason_keys or [])
        if str(item or "").strip()
    ]
    invalid_reason_keys = [
        key
        for key in normalized_reason_keys
        if len(key) > 80 or key not in allowed_reason_keys
    ]
    if invalid_reason_keys:
        raise HTTPException(status_code=422, detail="invalid_property_feedback_reason_key")
    result = service.record_property_feedback(
        principal_id=context.principal_id,
        person_id=person_id,
        property_slug=body.property_slug,
        property_url=body.property_url,
        property_title=body.property_title,
        property_facts=dict(body.property_facts or {}),
        reaction=body.reaction,
        reason_keys=normalized_reason_keys,
        note=body.note,
        actor=actor,
    )
    return PropertyFeedbackRecordOut(**result)


@router.get("/people/{person_id}/preference-profile/teable-projection", response_model=dict[str, list[dict[str, object]]])
def get_preference_teable_projection(
    person_id: str,
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> dict[str, list[dict[str, object]]]:
    service = build_product_service(container)
    return service.preference_teable_projection_records(
        principal_id=context.principal_id,
        person_id=person_id,
    )


@router.get("/people/{person_id}/preference-profile/teable-projection-summary", response_model=dict[str, object])
def get_preference_teable_projection_summary(
    person_id: str,
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> dict[str, object]:
    service = build_product_service(container)
    return service.preference_teable_projection_summary(
        principal_id=context.principal_id,
        person_id=person_id,
    )


@router.get("/people/{person_id}/preference-profile/teable-sync-preview", response_model=dict[str, object])
def get_preference_teable_sync_preview(
    person_id: str,
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> dict[str, object]:
    service = build_product_service(container)
    return service.preference_teable_sync_preview(
        principal_id=context.principal_id,
        person_id=person_id,
    )


@router.post("/people/{person_id}/preference-profile/teable-sync", response_model=dict[str, object])
def request_preference_teable_sync(
    person_id: str,
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> dict[str, object]:
    service = build_product_service(container)
    return service.request_preference_teable_sync(
        principal_id=context.principal_id,
        person_id=person_id,
    )


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


@router.get("/handoffs/{handoff_ref:path}/history", response_model=list[HandoffAssignmentHistoryOut])
def get_handoff_history(
    handoff_ref: str,
    limit: int = Query(default=20, ge=1, le=100),
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> list[HandoffAssignmentHistoryOut]:
    service = build_product_service(container)
    found = service.get_handoff(principal_id=context.principal_id, handoff_ref=handoff_ref)
    if found is None:
        raise HTTPException(status_code=404, detail="handoff_not_found")
    human_task_id = found.id.split(":", 1)[1] if found.id.startswith("human_task:") else found.id
    rows = container.orchestrator.list_human_task_assignment_history(
        human_task_id,
        principal_id=context.principal_id,
        limit=limit,
    )
    return [handoff_assignment_history_out(row) for row in rows]


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


@router.post("/handoffs/{handoff_ref:path}/retry-send", response_model=HandoffNoteOut)
def retry_handoff_send(
    handoff_ref: str,
    body: HandoffAssignIn,
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> HandoffNoteOut:
    service = build_product_service(container)
    actor = str(context.operator_id or context.access_email or context.principal_id or body.operator_id).strip()
    try:
        updated = service.retry_delivery_followup_send(
            principal_id=context.principal_id,
            handoff_ref=handoff_ref,
            operator_id=body.operator_id,
            actor=actor,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if updated is None:
        raise HTTPException(status_code=404, detail="handoff_not_retryable")
    return handoff_out(updated)


@router.post("/handoffs/{handoff_ref:path}/recreate", response_model=HandoffNoteOut)
def recreate_handoff(
    handoff_ref: str,
    body: HandoffAssignIn,
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> HandoffNoteOut:
    service = build_product_service(container)
    actor = str(context.operator_id or context.access_email or context.principal_id or body.operator_id).strip()
    try:
        updated = service.recreate_property_tour_followup(
            principal_id=context.principal_id,
            handoff_ref=handoff_ref,
            operator_id=body.operator_id,
            actor=actor,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if updated is None:
        raise HTTPException(status_code=404, detail="handoff_not_recreatable")
    return handoff_out(updated)


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


@router.get("/invitations", response_model=WorkspaceInvitationResponse)
def get_workspace_invitations(
    status: str = Query(default=""),
    limit: int = Query(default=100, ge=1, le=200),
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> WorkspaceInvitationResponse:
    service = build_product_service(container)
    items = service.list_workspace_invitations(principal_id=context.principal_id, status=status, limit=limit)
    return WorkspaceInvitationResponse(
        generated_at=now_iso(),
        items=[WorkspaceInvitationOut(**item) for item in items],
        total=len(items),
    )


@router.post("/invitations", response_model=WorkspaceInvitationOut)
def create_workspace_invitation(
    body: WorkspaceInvitationCreateIn,
    request: Request,
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> WorkspaceInvitationOut:
    service = build_product_service(container)
    actor = str(context.operator_id or context.access_email or context.principal_id or "workspace").strip()
    payload = service.create_workspace_invitation(
        principal_id=context.principal_id,
        email=body.email,
        role=body.role,
        invited_by=actor,
        display_name=body.display_name,
        note=body.note,
        expires_in_days=body.expires_in_days,
        base_url=str(request.base_url),
    )
    return WorkspaceInvitationOut(**payload)


@router.post("/invitations/accept", response_model=WorkspaceInvitationOut)
def accept_workspace_invitation(
    body: WorkspaceInvitationAcceptIn,
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> WorkspaceInvitationOut:
    service = build_product_service(container)
    actor = str(context.operator_id or context.access_email or context.principal_id or "workspace").strip()
    try:
        payload = service.accept_workspace_invitation(
            token=body.token,
            accepted_by=actor,
            display_name=body.display_name,
            operator_id=body.operator_id,
        )
    except ValueError as exc:
        if str(exc or "").strip() == "operator_seat_limit_reached":
            raise HTTPException(status_code=409, detail="operator_seat_limit_reached") from exc
        raise
    if payload is None:
        raise HTTPException(status_code=404, detail="workspace_invitation_not_found")
    return WorkspaceInvitationOut(**payload)


@router.post("/access-sessions", response_model=WorkspaceAccessSessionOut)
def create_workspace_access_session(
    body: WorkspaceAccessSessionCreateIn,
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> WorkspaceAccessSessionOut:
    service = build_product_service(container)
    payload = service.issue_workspace_access_session(
        principal_id=context.principal_id,
        email=body.email,
        role=body.role,
        display_name=body.display_name,
        operator_id=body.operator_id,
        source_kind="workspace_access_api",
        expires_in_hours=body.expires_in_hours,
    )
    return WorkspaceAccessSessionOut(**payload)


def _normalize_workspace_access_legacy_payload(*, body: dict[str, object]) -> tuple[str, str, str, str, int, str]:
    normalized_email = str(body.get("email") or body.get("recipient_email") or "").strip().lower()
    if not normalized_email:
        raise HTTPException(status_code=400, detail="recipient_email_required")
    expires_raw = str(body.get("expires_in_hours") or 72).strip()
    try:
        expires_in_hours = int(expires_raw)
    except ValueError:
        expires_in_hours = 72
    return (
        normalized_email,
        str(body.get("role") or "operator").strip().lower() or "operator",
        str(body.get("display_name") or "").strip(),
        str(body.get("operator_id") or "").strip(),
        max(1, expires_in_hours),
        str(body.get("return_to") or body.get("default_target") or "").strip(),
    )


@router.post("/workspace-access", include_in_schema=False, response_model=WorkspaceAccessSessionOut)
def create_workspace_access_session_legacy(
    body: dict[str, object],
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> WorkspaceAccessSessionOut:
    service = build_product_service(container)
    email, role, display_name, operator_id, expires_in_hours, default_target = _normalize_workspace_access_legacy_payload(
        body=dict(body or {})
    )
    payload = service.issue_workspace_access_session(
        principal_id=context.principal_id,
        email=email,
        role=role,
        display_name=display_name,
        operator_id=operator_id,
        source_kind="workspace_access_api",
        expires_in_hours=expires_in_hours,
        default_target=default_target,
    )
    return WorkspaceAccessSessionOut(**payload)


@router.get("/access-sessions", response_model=WorkspaceAccessSessionResponse)
def list_workspace_access_sessions(
    status: str = Query(default=""),
    limit: int = Query(default=50, ge=1, le=200),
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> WorkspaceAccessSessionResponse:
    service = build_product_service(container)
    items = service.list_workspace_access_sessions(
        principal_id=context.principal_id,
        status=status,
        limit=limit,
    )
    return WorkspaceAccessSessionResponse(
        generated_at=now_iso(),
        items=[WorkspaceAccessSessionOut(**item) for item in items],
        total=len(items),
    )


@router.post("/access-sessions/{session_id}/revoke", response_model=WorkspaceAccessSessionOut)
def revoke_workspace_access_session(
    session_id: str,
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> WorkspaceAccessSessionOut:
    service = build_product_service(container)
    actor = str(context.operator_id or context.access_email or context.principal_id or "workspace").strip()
    payload = service.revoke_workspace_access_session(
        principal_id=context.principal_id,
        session_id=session_id,
        actor=actor,
    )
    if payload is None:
        raise HTTPException(status_code=404, detail="workspace_access_session_not_found")
    return WorkspaceAccessSessionOut(**payload)


@router.post("/invitations/{invitation_id}/revoke", response_model=WorkspaceInvitationOut)
def revoke_workspace_invitation(
    invitation_id: str,
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> WorkspaceInvitationOut:
    service = build_product_service(container)
    actor = str(context.operator_id or context.access_email or context.principal_id or "workspace").strip()
    payload = service.revoke_workspace_invitation(
        principal_id=context.principal_id,
        invitation_id=invitation_id,
        actor=actor,
    )
    if payload is None:
        raise HTTPException(status_code=404, detail="workspace_invitation_not_found")
    return WorkspaceInvitationOut(**payload)


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
