from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel, Field

from app.product.models import BriefItem, CommitmentCandidate, CommitmentItem, DecisionItem, DecisionQueueItem, DraftCandidate, EvidenceItem, EvidenceRef, HandoffNote, HistoryEntry, PersonDetail, PersonProfile, RuleItem, ThreadItem


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
    confidence: float = 0.0
    object_ref: str = ""
    evidence_count: int = 0


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


class DecisionItemOut(BaseModel):
    id: str
    title: str
    summary: str
    priority: str
    owner_role: str
    due_at: str | None = None
    status: str
    decision_type: str = ""
    recommendation: str = ""
    next_action: str = ""
    rationale: str = ""
    options: list[str]
    evidence_refs: list[EvidenceRefOut]
    related_commitment_ids: list[str]
    linked_thread_ids: list[str]
    related_people: list[str]
    impact_summary: str = ""
    sla_status: str = ""
    resolution_reason: str = ""


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
    confidence: float = 0.5
    channel_hint: str = ""
    resolution_code: str = ""
    resolution_reason: str = ""
    duplicate_of_ref: str = ""
    merged_into_ref: str = ""
    merged_from_refs: list[str] = []


class CommitmentCandidateOut(BaseModel):
    candidate_id: str = ""
    title: str
    details: str
    source_text: str
    confidence: float
    suggested_due_at: str | None = None
    counterparty: str = ""
    channel_hint: str = ""
    source_ref: str = ""
    signal_type: str = ""
    status: str = "pending"
    kind: str = "commitment"
    stakeholder_id: str = ""
    duplicate_of_ref: str = ""
    merge_strategy: str = "create"


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


class HandoffNoteOut(BaseModel):
    id: str
    queue_item_ref: str
    summary: str
    owner: str
    due_time: str | None = None
    escalation_status: str
    status: str
    task_type: str = ""
    resolution: str = ""
    draft_ref: str = ""
    recipient_email: str = ""
    subject: str = ""
    delivery_reason: str = ""
    evidence_refs: list[EvidenceRefOut]


class HistoryEntryOut(BaseModel):
    event_type: str
    created_at: str | None = None
    source_id: str = ""
    actor: str = ""
    detail: str = ""


class PersonDetailOut(BaseModel):
    profile: PersonProfileOut
    commitments: list[CommitmentOut]
    drafts: list[DraftCandidateOut]
    queue_items: list[DecisionQueueItemOut]
    handoffs: list[HandoffNoteOut]
    evidence_refs: list[EvidenceRefOut]
    history: list[HistoryEntryOut]


class ThreadItemOut(BaseModel):
    id: str
    title: str
    channel: str
    status: str
    last_activity_at: str | None = None
    summary: str
    counterparties: list[str]
    draft_ids: list[str]
    related_commitment_ids: list[str]
    related_decision_ids: list[str]
    evidence_refs: list[EvidenceRefOut]


class EvidenceItemOut(BaseModel):
    id: str
    label: str
    source_type: str
    summary: str
    href: str = ""
    related_object_refs: list[str]


class RuleItemOut(BaseModel):
    id: str
    label: str
    scope: str
    status: str
    summary: str
    current_value: str
    impact: str
    requires_approval: bool = False
    simulated_effect: str = ""


class OfficeEventOut(BaseModel):
    observation_id: str
    channel: str
    event_type: str
    created_at: str
    source_id: str = ""
    external_id: str = ""
    summary: str = ""
    object_refs: list[str] = Field(default_factory=list)
    payload: dict[str, object] = Field(default_factory=dict)


class WorkspaceDiagnosticsOut(BaseModel):
    workspace: dict[str, object]
    selected_channels: list[str]
    plan: dict[str, object]
    billing: dict[str, object]
    entitlements: dict[str, object]
    commercial: dict[str, object]
    readiness: dict[str, object]
    operators: dict[str, object]
    providers: dict[str, object]
    queue_health: dict[str, object]
    usage: dict[str, int]
    analytics: dict[str, object]


class WorkspacePlanDetailOut(BaseModel):
    workspace: dict[str, object]
    selected_channels: list[str]
    plan: dict[str, object]
    billing: dict[str, object]
    entitlements: dict[str, object]
    commercial: dict[str, object]
    operators: dict[str, object]


class WorkspaceUsageDetailOut(BaseModel):
    workspace: dict[str, object]
    selected_channels: list[str]
    usage: dict[str, int]
    analytics: dict[str, object]
    readiness: dict[str, object]
    operators: dict[str, object]


class WorkspaceOutcomesOut(BaseModel):
    generated_at: str
    time_to_first_value_seconds: int | None = None
    first_value_event: str = ""
    memo_open_rate: float = 0.0
    approval_coverage_rate: float = 0.0
    approval_action_rate: float = 0.0
    delivery_followup_resolution_rate: float | None = None
    commitment_close_rate: float = 0.0
    correction_rate: float = 0.0
    churn_risk: str = "watch"
    success_summary: str = ""
    memo_loop: dict[str, object] = Field(default_factory=dict)
    office_loop_proof: dict[str, object] = Field(default_factory=dict)
    counts: dict[str, int] = Field(default_factory=dict)


class WorkspaceTrustOut(BaseModel):
    generated_at: str
    health_score: int = 0
    workspace_summary: str = ""
    readiness: dict[str, str] = Field(default_factory=dict)
    provider_posture: dict[str, object] = Field(default_factory=dict)
    reliability: dict[str, str] = Field(default_factory=dict)
    audit_retention: str = "standard"
    evidence_count: int = 0
    rule_count: int = 0
    recent_events: list[OfficeEventOut] = Field(default_factory=list)


class WorkspaceSupportBundleOut(BaseModel):
    workspace: dict[str, object]
    selected_channels: list[str]
    plan: dict[str, object]
    billing: dict[str, object]
    entitlements: dict[str, object]
    commercial: dict[str, object]
    readiness: dict[str, object]
    usage: dict[str, object]
    analytics: dict[str, object]
    approvals: dict[str, object]
    human_tasks: list[dict[str, object]]
    providers: dict[str, object]
    queue_health: dict[str, object]
    assignment_suggestions: list[dict[str, object]]
    pending_delivery: list[dict[str, object]]
    recent_events: list[OfficeEventOut] = Field(default_factory=list)


class OperatorCenterLaneOut(BaseModel):
    key: str
    label: str
    state: str = "clear"
    count: int = 0
    detail: str = ""
    href: str = ""


class OperatorCenterActionOut(BaseModel):
    label: str
    detail: str = ""
    href: str = ""
    action_href: str = ""
    action_label: str = ""
    action_value: str = ""
    action_method: str = ""
    return_to: str = ""


class OperatorCenterOut(BaseModel):
    generated_at: str
    workspace: dict[str, object]
    operators: dict[str, object]
    queue_health: dict[str, object]
    providers: dict[str, object]
    readiness: dict[str, object]
    delivery: dict[str, object]
    access: dict[str, object]
    sync: dict[str, object]
    usage: dict[str, int]
    lanes: list[OperatorCenterLaneOut] = Field(default_factory=list)
    next_actions: list[OperatorCenterActionOut] = Field(default_factory=list)
    recent_runtime: list[dict[str, object]] = Field(default_factory=list)
    snapshot: dict[str, int] = Field(default_factory=dict)


class WorkspaceInvitationOut(BaseModel):
    invitation_id: str
    email: str
    role: str = "operator"
    display_name: str = ""
    note: str = ""
    status: str = "pending"
    invited_by: str = ""
    invited_at: str = ""
    expires_at: str = ""
    accepted_at: str = ""
    accepted_by: str = ""
    revoked_at: str = ""
    invite_url: str = ""
    invite_token: str = ""
    operator_id: str = ""
    access_token: str = ""
    access_url: str = ""
    access_expires_at: str = ""
    email_delivery_status: str = ""
    email_delivery_error: str = ""
    email_message_id: str = ""
    email_provider: str = ""


class WorkspaceInvitationResponse(BaseModel):
    generated_at: str
    items: list[WorkspaceInvitationOut]
    total: int


class ChannelLoopItemOut(BaseModel):
    title: str
    detail: str
    tag: str
    href: str = ""
    action_href: str = ""
    action_label: str = ""
    action_method: str = "get"
    secondary_action_href: str = ""
    secondary_action_label: str = ""
    secondary_action_method: str = "get"


class ChannelDigestOut(BaseModel):
    key: str
    headline: str
    summary: str
    preview_text: str
    items: list[ChannelLoopItemOut]
    stats: dict[str, int]


class ChannelLoopOut(BaseModel):
    headline: str
    summary: str
    items: list[ChannelLoopItemOut]
    stats: dict[str, int]
    digests: list[ChannelDigestOut] = []


class BriefResponse(BaseModel):
    generated_at: str
    items: list[BriefItemOut]
    total: int


class QueueResponse(BaseModel):
    generated_at: str
    items: list[DecisionQueueItemOut]
    total: int


class DecisionResponse(BaseModel):
    generated_at: str
    items: list[DecisionItemOut]
    total: int


class ThreadResponse(BaseModel):
    generated_at: str
    items: list[ThreadItemOut]
    total: int


class EvidenceResponse(BaseModel):
    generated_at: str
    items: list[EvidenceItemOut]
    total: int


class RuleResponse(BaseModel):
    generated_at: str
    items: list[RuleItemOut]
    total: int


class OfficeEventResponse(BaseModel):
    generated_at: str
    items: list[OfficeEventOut]
    total: int


class SearchResultOut(BaseModel):
    id: str
    kind: str
    title: str
    summary: str = ""
    href: str = ""
    score: float = 0.0
    secondary_label: str = ""
    related_object_refs: list[str] = Field(default_factory=list)
    action_href: str = ""
    action_label: str = ""
    action_method: str = ""
    action_value: str = ""


class SearchResponse(BaseModel):
    generated_at: str
    items: list[SearchResultOut]
    total: int


class WebhookOut(BaseModel):
    webhook_id: str
    label: str
    target_url: str
    status: str = "active"
    event_types: list[str] = Field(default_factory=list)
    created_at: str = ""
    last_delivery_at: str = ""
    delivery_count: int = 0


class WebhookDeliveryOut(BaseModel):
    delivery_id: str
    webhook_id: str
    label: str = ""
    target_url: str = ""
    matched_event_type: str = ""
    delivery_kind: str = "event"
    status: str = "queued"
    created_at: str = ""
    source_id: str = ""
    summary: str = ""
    payload: dict[str, object] = Field(default_factory=dict)


class WebhookResponse(BaseModel):
    generated_at: str
    items: list[WebhookOut]
    total: int


class WebhookDeliveryResponse(BaseModel):
    generated_at: str
    items: list[WebhookDeliveryOut]
    total: int


class WorkspaceInvitationCreateIn(BaseModel):
    email: str = Field(min_length=3)
    role: str = "operator"
    display_name: str = ""
    note: str = ""
    expires_in_days: int = 14


class WorkspaceInvitationAcceptIn(BaseModel):
    token: str = Field(min_length=8)
    display_name: str = ""
    operator_id: str = ""


class WorkspaceAccessSessionCreateIn(BaseModel):
    email: str = Field(min_length=3)
    role: str = "principal"
    display_name: str = ""
    operator_id: str = ""
    expires_in_hours: int = 72


class WorkspaceAccessSessionOut(BaseModel):
    session_id: str
    principal_id: str
    email: str = ""
    role: str = "principal"
    display_name: str = ""
    operator_id: str = ""
    source_kind: str = ""
    issued_at: str = ""
    status: str = "active"
    revoked_at: str = ""
    revoked_by: str = ""
    expires_at: str = ""
    access_token: str = ""
    access_url: str = ""
    default_target: str = "/app/today"


class WorkspaceAccessSessionResponse(BaseModel):
    generated_at: str
    items: list[WorkspaceAccessSessionOut]
    total: int


class ChannelDigestDeliveryCreateIn(BaseModel):
    recipient_email: str = Field(min_length=3)
    role: str = "principal"
    display_name: str = ""
    operator_id: str = ""
    delivery_channel: str = "email"
    expires_in_hours: int = 72


class ChannelDigestDeliveryOut(BaseModel):
    delivery_id: str
    digest_key: str
    principal_id: str
    recipient_email: str
    role: str = "principal"
    display_name: str = ""
    operator_id: str = ""
    delivery_channel: str = "email"
    expires_at: str = ""
    delivery_token: str = ""
    delivery_url: str = ""
    open_url: str = ""
    access_token: str = ""
    access_url: str = ""
    default_target: str = "/app/today"
    headline: str = ""
    preview_text: str = ""
    plain_text: str = ""
    email_delivery_status: str = ""
    email_delivery_error: str = ""
    email_message_id: str = ""
    email_provider: str = ""


class DraftApproveIn(BaseModel):
    reason: str = "Approved from product draft queue."


class QueueResolveIn(BaseModel):
    action: str = Field(min_length=1)
    reason: str = ""
    reason_code: str = ""
    due_at: str | None = None


class CommitmentCreateIn(BaseModel):
    title: str = Field(min_length=1)
    details: str = ""
    due_at: str | None = None
    priority: str = "medium"
    counterparty: str = ""
    owner: str = "office"
    kind: str = "commitment"
    stakeholder_id: str = ""
    channel_hint: str = "email"


class CommitmentExtractIn(BaseModel):
    text: str = Field(min_length=1)
    counterparty: str = ""
    due_at: str | None = None


class CommitmentCandidateStageIn(BaseModel):
    text: str = Field(min_length=1)
    counterparty: str = ""
    due_at: str | None = None
    kind: str = "commitment"
    stakeholder_id: str = ""


class CommitmentCandidateReviewIn(BaseModel):
    reviewer: str = Field(min_length=1)
    title: str = ""
    details: str = ""
    due_at: str | None = None
    counterparty: str = ""
    kind: str = ""
    stakeholder_id: str = ""


class HandoffAssignIn(BaseModel):
    operator_id: str = Field(min_length=1)


class HandoffCompleteIn(BaseModel):
    operator_id: str = Field(min_length=1)
    resolution: str = "completed"


class PersonCorrectionIn(BaseModel):
    preferred_tone: str = ""
    add_theme: str = ""
    remove_theme: str = ""
    add_risk: str = ""
    remove_risk: str = ""


class RuleSimulateIn(BaseModel):
    proposed_value: str = Field(min_length=1)


class OfficeSignalIn(BaseModel):
    signal_type: str = Field(min_length=1)
    channel: str = "office_api"
    title: str = ""
    summary: str = ""
    text: str = ""
    source_ref: str = ""
    external_id: str = ""
    counterparty: str = ""
    stakeholder_id: str = ""
    due_at: str | None = None
    payload: dict[str, object] = Field(default_factory=dict)


class OfficeSignalResultOut(BaseModel):
    observation_id: str
    channel: str
    event_type: str
    source_id: str = ""
    external_id: str = ""
    created_at: str
    staged_candidates: list[CommitmentCandidateOut] = Field(default_factory=list)
    staged_drafts: list[DraftCandidateOut] = Field(default_factory=list)
    staged_count: int = 0
    draft_count: int = 0
    deduplicated: bool = False


class GoogleSignalSyncOut(BaseModel):
    generated_at: str
    account_email: str = ""
    granted_scopes: list[str] = Field(default_factory=list)
    items: list[OfficeSignalResultOut] = Field(default_factory=list)
    total: int = 0
    synced_total: int = 0
    deduplicated_total: int = 0


class GoogleSignalSyncStatusOut(BaseModel):
    generated_at: str
    connected: bool = False
    account_email: str = ""
    token_status: str = "missing"
    last_refresh_at: str = ""
    reauth_required_reason: str = ""
    sync_completed: int = 0
    office_signal_ingested: int = 0
    last_completed_at: str = ""
    last_synced_total: int = 0
    last_deduplicated_total: int = 0
    last_gmail_total: int = 0
    last_calendar_total: int = 0
    age_seconds: int | None = None
    freshness_state: str = "watch"
    pending_commitment_candidates: int = 0
    covered_signal_candidates: int = 0


class WebhookRegisterIn(BaseModel):
    label: str = Field(min_length=1)
    target_url: str = Field(min_length=1)
    event_types: list[str] = Field(default_factory=list)
    status: str = "active"


class WebhookTestResultOut(BaseModel):
    webhook: WebhookOut
    delivery: WebhookDeliveryOut


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def evidence_out(values: tuple[EvidenceRef, ...]) -> list[EvidenceRefOut]:
    return [EvidenceRefOut(**value.__dict__) for value in values]


def brief_out(value: BriefItem) -> BriefItemOut:
    return BriefItemOut(
        id=value.id,
        workspace_id=value.workspace_id,
        kind=value.kind,
        title=value.title,
        summary=value.summary,
        score=value.score,
        why_now=value.why_now,
        evidence_refs=evidence_out(value.evidence_refs),
        related_people=list(value.related_people),
        related_commitment_ids=list(value.related_commitment_ids),
        recommended_action=value.recommended_action,
        status=value.status,
        confidence=value.confidence,
        object_ref=value.object_ref,
        evidence_count=value.evidence_count,
    )


def queue_out(value: DecisionQueueItem) -> DecisionQueueItemOut:
    return DecisionQueueItemOut(
        id=value.id,
        queue_kind=value.queue_kind,
        title=value.title,
        summary=value.summary,
        priority=value.priority,
        deadline=value.deadline,
        owner_role=value.owner_role,
        requires_principal=value.requires_principal,
        evidence_refs=evidence_out(value.evidence_refs),
        resolution_state=value.resolution_state,
    )


def decision_out(value: DecisionItem) -> DecisionItemOut:
    return DecisionItemOut(
        id=value.id,
        title=value.title,
        summary=value.summary,
        priority=value.priority,
        owner_role=value.owner_role,
        due_at=value.due_at,
        status=value.status,
        decision_type=value.decision_type,
        recommendation=value.recommendation,
        next_action=value.next_action,
        rationale=value.rationale,
        options=list(value.options),
        evidence_refs=evidence_out(value.evidence_refs),
        related_commitment_ids=list(value.related_commitment_ids),
        linked_thread_ids=list(value.linked_thread_ids),
        related_people=list(value.related_people),
        impact_summary=value.impact_summary,
        sla_status=value.sla_status,
        resolution_reason=value.resolution_reason,
    )


def commitment_out(value: CommitmentItem) -> CommitmentOut:
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
        proof_refs=evidence_out(value.proof_refs),
        confidence=value.confidence,
        channel_hint=value.channel_hint,
        resolution_code=value.resolution_code,
        resolution_reason=value.resolution_reason,
        duplicate_of_ref=value.duplicate_of_ref,
        merged_into_ref=value.merged_into_ref,
        merged_from_refs=list(value.merged_from_refs),
    )


def commitment_candidate_out(value: CommitmentCandidate) -> CommitmentCandidateOut:
    return CommitmentCandidateOut(
        candidate_id=value.candidate_id,
        title=value.title,
        details=value.details,
        source_text=value.source_text,
        confidence=value.confidence,
        suggested_due_at=value.suggested_due_at,
        counterparty=value.counterparty,
        channel_hint=value.channel_hint,
        source_ref=value.source_ref,
        signal_type=value.signal_type,
        status=value.status,
        kind=value.kind,
        stakeholder_id=value.stakeholder_id,
        duplicate_of_ref=value.duplicate_of_ref,
        merge_strategy=value.merge_strategy,
    )


def draft_out(value: DraftCandidate) -> DraftCandidateOut:
    return DraftCandidateOut(
        id=value.id,
        thread_ref=value.thread_ref,
        recipient_summary=value.recipient_summary,
        intent=value.intent,
        draft_text=value.draft_text,
        tone=value.tone,
        requires_approval=value.requires_approval,
        approval_status=value.approval_status,
        provenance_refs=evidence_out(value.provenance_refs),
        send_channel=value.send_channel,
    )


def person_out(value: PersonProfile) -> PersonProfileOut:
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


def handoff_out(value: HandoffNote) -> HandoffNoteOut:
    return HandoffNoteOut(
        id=value.id,
        queue_item_ref=value.queue_item_ref,
        summary=value.summary,
        owner=value.owner,
        due_time=value.due_time,
        escalation_status=value.escalation_status,
        status=value.status,
        task_type=value.task_type,
        resolution=value.resolution,
        draft_ref=value.draft_ref,
        recipient_email=value.recipient_email,
        subject=value.subject,
        delivery_reason=value.delivery_reason,
        evidence_refs=evidence_out(value.evidence_refs),
    )


def thread_out(value: ThreadItem) -> ThreadItemOut:
    return ThreadItemOut(
        id=value.id,
        title=value.title,
        channel=value.channel,
        status=value.status,
        last_activity_at=value.last_activity_at,
        summary=value.summary,
        counterparties=list(value.counterparties),
        draft_ids=list(value.draft_ids),
        related_commitment_ids=list(value.related_commitment_ids),
        related_decision_ids=list(value.related_decision_ids),
        evidence_refs=evidence_out(value.evidence_refs),
    )


def evidence_item_out(value: EvidenceItem) -> EvidenceItemOut:
    return EvidenceItemOut(
        id=value.id,
        label=value.label,
        source_type=value.source_type,
        summary=value.summary,
        href=value.href,
        related_object_refs=list(value.related_object_refs),
    )


def rule_out(value: RuleItem) -> RuleItemOut:
    return RuleItemOut(
        id=value.id,
        label=value.label,
        scope=value.scope,
        status=value.status,
        summary=value.summary,
        current_value=value.current_value,
        impact=value.impact,
        requires_approval=value.requires_approval,
        simulated_effect=value.simulated_effect,
    )


def history_out(value: HistoryEntry) -> HistoryEntryOut:
    return HistoryEntryOut(
        event_type=value.event_type,
        created_at=value.created_at,
        source_id=value.source_id,
        actor=value.actor,
        detail=value.detail,
    )


def person_detail_out(value: PersonDetail) -> PersonDetailOut:
    return PersonDetailOut(
        profile=person_out(value.profile),
        commitments=[commitment_out(item) for item in value.commitments],
        drafts=[draft_out(item) for item in value.drafts],
        queue_items=[queue_out(item) for item in value.queue_items],
        handoffs=[handoff_out(item) for item in value.handoffs],
        evidence_refs=evidence_out(value.evidence_refs),
        history=[history_out(item) for item in value.history],
    )
