from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class EvidenceRef:
    ref_id: str
    label: str
    href: str = ""
    source_type: str = ""
    note: str = ""


@dataclass(frozen=True)
class PolicyGate:
    gate_id: str
    label: str
    status: str
    detail: str = ""


@dataclass(frozen=True)
class HistoryEntry:
    event_type: str
    created_at: str | None = None
    source_id: str = ""
    actor: str = ""
    detail: str = ""


@dataclass(frozen=True)
class BriefItem:
    id: str
    workspace_id: str
    kind: str
    title: str
    summary: str
    score: float
    why_now: str
    evidence_refs: tuple[EvidenceRef, ...] = ()
    related_people: tuple[str, ...] = ()
    related_commitment_ids: tuple[str, ...] = ()
    recommended_action: str = ""
    status: str = "open"


@dataclass(frozen=True)
class DecisionQueueItem:
    id: str
    queue_kind: str
    title: str
    summary: str
    priority: str
    deadline: str | None = None
    owner_role: str = ""
    requires_principal: bool = False
    evidence_refs: tuple[EvidenceRef, ...] = ()
    resolution_state: str = "open"


@dataclass(frozen=True)
class CommitmentItem:
    id: str
    source_type: str
    source_ref: str
    statement: str
    owner: str
    counterparty: str
    due_at: str | None
    status: str
    last_activity_at: str | None
    risk_level: str
    proof_refs: tuple[EvidenceRef, ...] = ()
    confidence: float = 0.5
    channel_hint: str = ""
    resolution_code: str = ""
    resolution_reason: str = ""
    duplicate_of_ref: str = ""
    merged_into_ref: str = ""
    merged_from_refs: tuple[str, ...] = ()


@dataclass(frozen=True)
class DraftCandidate:
    id: str
    thread_ref: str
    recipient_summary: str
    intent: str
    draft_text: str
    tone: str
    requires_approval: bool
    approval_status: str
    provenance_refs: tuple[EvidenceRef, ...] = ()
    send_channel: str = ""


@dataclass(frozen=True)
class DecisionItem:
    id: str
    title: str
    summary: str
    priority: str
    owner_role: str
    due_at: str | None
    status: str
    recommendation: str = ""
    rationale: str = ""
    options: tuple[str, ...] = ()
    evidence_refs: tuple[EvidenceRef, ...] = ()
    related_commitment_ids: tuple[str, ...] = ()
    related_people: tuple[str, ...] = ()


@dataclass(frozen=True)
class ThreadItem:
    id: str
    title: str
    channel: str
    status: str
    last_activity_at: str | None
    summary: str
    counterparties: tuple[str, ...] = ()
    draft_ids: tuple[str, ...] = ()
    related_commitment_ids: tuple[str, ...] = ()
    related_decision_ids: tuple[str, ...] = ()
    evidence_refs: tuple[EvidenceRef, ...] = ()


@dataclass(frozen=True)
class CommitmentCandidate:
    title: str
    details: str
    source_text: str
    confidence: float
    suggested_due_at: str | None = None
    counterparty: str = ""
    status: str = "pending"
    candidate_id: str = ""
    kind: str = "commitment"
    stakeholder_id: str = ""
    duplicate_of_ref: str = ""
    merge_strategy: str = "create"


@dataclass(frozen=True)
class PersonProfile:
    id: str
    display_name: str
    role_or_company: str
    importance_score: int
    relationship_temperature: str
    open_loops_count: int
    latest_touchpoint_at: str | None
    preferred_tone: str
    themes: tuple[str, ...] = ()
    risks: tuple[str, ...] = ()


@dataclass(frozen=True)
class PersonDetail:
    profile: PersonProfile
    commitments: tuple[CommitmentItem, ...] = ()
    drafts: tuple[DraftCandidate, ...] = ()
    queue_items: tuple[DecisionQueueItem, ...] = ()
    handoffs: tuple[HandoffNote, ...] = ()
    evidence_refs: tuple[EvidenceRef, ...] = ()
    history: tuple[HistoryEntry, ...] = ()


@dataclass(frozen=True)
class HandoffNote:
    id: str
    queue_item_ref: str
    summary: str
    owner: str
    due_time: str | None
    escalation_status: str
    status: str = "open"
    evidence_refs: tuple[EvidenceRef, ...] = ()


@dataclass(frozen=True)
class EvidenceItem:
    id: str
    label: str
    source_type: str
    summary: str
    href: str = ""
    related_object_refs: tuple[str, ...] = ()


@dataclass(frozen=True)
class RuleItem:
    id: str
    label: str
    scope: str
    status: str
    summary: str
    current_value: str
    impact: str
    requires_approval: bool = False
    simulated_effect: str = ""


@dataclass(frozen=True)
class ProductSnapshot:
    brief_items: tuple[BriefItem, ...] = field(default_factory=tuple)
    queue_items: tuple[DecisionQueueItem, ...] = field(default_factory=tuple)
    commitments: tuple[CommitmentItem, ...] = field(default_factory=tuple)
    commitment_candidates: tuple[CommitmentCandidate, ...] = field(default_factory=tuple)
    drafts: tuple[DraftCandidate, ...] = field(default_factory=tuple)
    decisions: tuple[DecisionItem, ...] = field(default_factory=tuple)
    threads: tuple[ThreadItem, ...] = field(default_factory=tuple)
    people: tuple[PersonProfile, ...] = field(default_factory=tuple)
    handoffs: tuple[HandoffNote, ...] = field(default_factory=tuple)
    completed_handoffs: tuple[HandoffNote, ...] = field(default_factory=tuple)
    evidence: tuple[EvidenceItem, ...] = field(default_factory=tuple)
    rules: tuple[RuleItem, ...] = field(default_factory=tuple)
    stats_json: dict[str, int] = field(default_factory=dict)
