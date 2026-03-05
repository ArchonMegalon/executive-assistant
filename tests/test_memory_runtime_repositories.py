from __future__ import annotations

from app.repositories.authority_bindings import InMemoryAuthorityBindingRepository
from app.repositories.commitments import InMemoryCommitmentRepository
from app.repositories.decision_windows import InMemoryDecisionWindowRepository
from app.repositories.delivery_preferences import InMemoryDeliveryPreferenceRepository
from app.repositories.deadline_windows import InMemoryDeadlineWindowRepository
from app.repositories.entities import InMemoryEntityRepository
from app.repositories.follow_ups import InMemoryFollowUpRepository
from app.repositories.memory_candidates import InMemoryMemoryCandidateRepository
from app.repositories.memory_items import InMemoryMemoryItemRepository
from app.repositories.relationships import InMemoryRelationshipRepository
from app.repositories.stakeholders import InMemoryStakeholderRepository
from app.services.memory_runtime import MemoryRuntimeService


def test_inmemory_memory_candidate_review_and_filtering() -> None:
    repo = InMemoryMemoryCandidateRepository()
    first = repo.create_candidate(
        principal_id="exec-1",
        category="stakeholder_pref",
        summary="CEO prefers concise updates",
        fact_json={"tone": "concise"},
        confidence=0.7,
    )
    _second = repo.create_candidate(
        principal_id="exec-2",
        category="commitment",
        summary="Follow-up due Friday",
        fact_json={"deadline": "friday"},
        confidence=0.9,
    )

    reviewed = repo.review(first.candidate_id, status="promoted", reviewer="qa-user", promoted_item_id="item-1")
    assert reviewed is not None
    assert reviewed.status == "promoted"
    assert reviewed.reviewer == "qa-user"
    assert reviewed.promoted_item_id == "item-1"

    promoted = repo.list_candidates(limit=10, status="promoted", principal_id="exec-1")
    assert len(promoted) == 1
    assert promoted[0].candidate_id == first.candidate_id



def test_inmemory_memory_runtime_promote_and_reject_paths() -> None:
    runtime = MemoryRuntimeService(
        candidates=InMemoryMemoryCandidateRepository(),
        items=InMemoryMemoryItemRepository(),
        entities=InMemoryEntityRepository(),
        relationships=InMemoryRelationshipRepository(),
        commitments=InMemoryCommitmentRepository(),
        decision_windows=InMemoryDecisionWindowRepository(),
        authority_bindings=InMemoryAuthorityBindingRepository(),
        delivery_preferences=InMemoryDeliveryPreferenceRepository(),
        deadline_windows=InMemoryDeadlineWindowRepository(),
        stakeholders=InMemoryStakeholderRepository(),
        follow_ups=InMemoryFollowUpRepository(),
    )

    candidate = runtime.stage_candidate(
        principal_id="exec-1",
        category="preference",
        summary="Prefers agenda before meeting",
        fact_json={"lead_time_minutes": 30},
        source_session_id="session-1",
        source_event_id="event-1",
        source_step_id="step-1",
        confidence=0.65,
        sensitivity="internal",
    )

    promoted = runtime.promote_candidate(
        candidate.candidate_id,
        reviewer="operator-1",
        sharing_policy="private",
    )
    assert promoted is not None
    promoted_candidate, item = promoted
    assert promoted_candidate.status == "promoted"
    assert promoted_candidate.promoted_item_id == item.item_id
    assert item.provenance_json["candidate_id"] == candidate.candidate_id

    listed_items = runtime.list_items(limit=10, principal_id="exec-1")
    assert len(listed_items) == 1
    assert listed_items[0].item_id == item.item_id

    rejected_candidate = runtime.stage_candidate(
        principal_id="exec-1",
        category="noise",
        summary="Low-value transcript fragment",
        fact_json={"raw": "..."},
    )
    rejected = runtime.reject_candidate(rejected_candidate.candidate_id, reviewer="operator-1")
    assert rejected is not None
    assert rejected.status == "rejected"

    pending = runtime.list_candidates(limit=10, status="pending", principal_id="exec-1")
    assert all(row.status == "pending" for row in pending)


def test_inmemory_entities_and_relationships_upsert_flow() -> None:
    runtime = MemoryRuntimeService(
        candidates=InMemoryMemoryCandidateRepository(),
        items=InMemoryMemoryItemRepository(),
        entities=InMemoryEntityRepository(),
        relationships=InMemoryRelationshipRepository(),
        commitments=InMemoryCommitmentRepository(),
        decision_windows=InMemoryDecisionWindowRepository(),
        authority_bindings=InMemoryAuthorityBindingRepository(),
        delivery_preferences=InMemoryDeliveryPreferenceRepository(),
        deadline_windows=InMemoryDeadlineWindowRepository(),
        stakeholders=InMemoryStakeholderRepository(),
        follow_ups=InMemoryFollowUpRepository(),
    )

    executive = runtime.upsert_entity(
        principal_id="exec-1",
        entity_type="person",
        canonical_name="Alex Executive",
        attributes_json={"role": "executive"},
        confidence=0.9,
    )
    stakeholder = runtime.upsert_entity(
        principal_id="exec-1",
        entity_type="person",
        canonical_name="Sam Stakeholder",
        attributes_json={"role": "board_member"},
        confidence=0.88,
    )
    assert executive.entity_id
    assert stakeholder.entity_id

    rel = runtime.upsert_relationship(
        principal_id="exec-1",
        from_entity_id=executive.entity_id,
        to_entity_id=stakeholder.entity_id,
        relationship_type="reports_to",
        attributes_json={"strength": "high"},
        confidence=0.75,
    )
    assert rel.relationship_id
    assert rel.relationship_type == "reports_to"

    listed_entities = runtime.list_entities(limit=10, principal_id="exec-1")
    assert len(listed_entities) == 2

    listed_relationships = runtime.list_relationships(limit=10, principal_id="exec-1")
    assert len(listed_relationships) == 1
    assert listed_relationships[0].relationship_id == rel.relationship_id


def test_inmemory_commitments_principal_scope() -> None:
    runtime = MemoryRuntimeService(
        candidates=InMemoryMemoryCandidateRepository(),
        items=InMemoryMemoryItemRepository(),
        entities=InMemoryEntityRepository(),
        relationships=InMemoryRelationshipRepository(),
        commitments=InMemoryCommitmentRepository(),
        decision_windows=InMemoryDecisionWindowRepository(),
        authority_bindings=InMemoryAuthorityBindingRepository(),
        delivery_preferences=InMemoryDeliveryPreferenceRepository(),
        deadline_windows=InMemoryDeadlineWindowRepository(),
        stakeholders=InMemoryStakeholderRepository(),
        follow_ups=InMemoryFollowUpRepository(),
    )

    created = runtime.upsert_commitment(
        principal_id="exec-1",
        title="Send board follow-up",
        details="Draft and send by Friday",
        status="open",
        priority="high",
        due_at="2026-03-06T10:00:00+00:00",
        source_json={"source": "manual"},
    )
    assert created.commitment_id
    assert created.principal_id == "exec-1"

    listed = runtime.list_commitments(principal_id="exec-1", limit=10)
    assert len(listed) == 1
    assert listed[0].commitment_id == created.commitment_id

    wrong_scope = runtime.get_commitment(created.commitment_id, principal_id="exec-2")
    assert wrong_scope is None

    right_scope = runtime.get_commitment(created.commitment_id, principal_id="exec-1")
    assert right_scope is not None
    assert right_scope.title == "Send board follow-up"


def test_inmemory_authority_bindings_principal_scope() -> None:
    runtime = MemoryRuntimeService(
        candidates=InMemoryMemoryCandidateRepository(),
        items=InMemoryMemoryItemRepository(),
        entities=InMemoryEntityRepository(),
        relationships=InMemoryRelationshipRepository(),
        commitments=InMemoryCommitmentRepository(),
        decision_windows=InMemoryDecisionWindowRepository(),
        authority_bindings=InMemoryAuthorityBindingRepository(),
        delivery_preferences=InMemoryDeliveryPreferenceRepository(),
        deadline_windows=InMemoryDeadlineWindowRepository(),
        stakeholders=InMemoryStakeholderRepository(),
        follow_ups=InMemoryFollowUpRepository(),
    )

    created = runtime.upsert_authority_binding(
        principal_id="exec-1",
        subject_ref="assistant",
        action_scope="calendar.write",
        approval_level="manager",
        channel_scope=("email", "slack"),
        policy_json={"quiet_hours_enforced": True},
        status="active",
    )
    assert created.binding_id
    assert created.principal_id == "exec-1"

    listed = runtime.list_authority_bindings(principal_id="exec-1", limit=10)
    assert len(listed) == 1
    assert listed[0].binding_id == created.binding_id

    wrong_scope = runtime.get_authority_binding(created.binding_id, principal_id="exec-2")
    assert wrong_scope is None

    right_scope = runtime.get_authority_binding(created.binding_id, principal_id="exec-1")
    assert right_scope is not None
    assert right_scope.action_scope == "calendar.write"


def test_inmemory_delivery_preferences_principal_scope() -> None:
    runtime = MemoryRuntimeService(
        candidates=InMemoryMemoryCandidateRepository(),
        items=InMemoryMemoryItemRepository(),
        entities=InMemoryEntityRepository(),
        relationships=InMemoryRelationshipRepository(),
        commitments=InMemoryCommitmentRepository(),
        decision_windows=InMemoryDecisionWindowRepository(),
        authority_bindings=InMemoryAuthorityBindingRepository(),
        delivery_preferences=InMemoryDeliveryPreferenceRepository(),
        deadline_windows=InMemoryDeadlineWindowRepository(),
        stakeholders=InMemoryStakeholderRepository(),
        follow_ups=InMemoryFollowUpRepository(),
    )

    created = runtime.upsert_delivery_preference(
        principal_id="exec-1",
        channel="email",
        recipient_ref="ceo@example.com",
        cadence="urgent_only",
        quiet_hours_json={"start": "22:00", "end": "07:00"},
        format_json={"style": "concise"},
        status="active",
    )
    assert created.preference_id
    assert created.principal_id == "exec-1"

    listed = runtime.list_delivery_preferences(principal_id="exec-1", limit=10)
    assert len(listed) == 1
    assert listed[0].preference_id == created.preference_id

    wrong_scope = runtime.get_delivery_preference(created.preference_id, principal_id="exec-2")
    assert wrong_scope is None

    right_scope = runtime.get_delivery_preference(created.preference_id, principal_id="exec-1")
    assert right_scope is not None
    assert right_scope.channel == "email"


def test_inmemory_follow_ups_principal_scope() -> None:
    runtime = MemoryRuntimeService(
        candidates=InMemoryMemoryCandidateRepository(),
        items=InMemoryMemoryItemRepository(),
        entities=InMemoryEntityRepository(),
        relationships=InMemoryRelationshipRepository(),
        commitments=InMemoryCommitmentRepository(),
        decision_windows=InMemoryDecisionWindowRepository(),
        authority_bindings=InMemoryAuthorityBindingRepository(),
        delivery_preferences=InMemoryDeliveryPreferenceRepository(),
        deadline_windows=InMemoryDeadlineWindowRepository(),
        stakeholders=InMemoryStakeholderRepository(),
        follow_ups=InMemoryFollowUpRepository(),
    )

    created = runtime.upsert_follow_up(
        principal_id="exec-1",
        stakeholder_ref="ceo@example.com",
        topic="Board follow-up",
        status="open",
        due_at="2026-03-07T09:00:00+00:00",
        channel_hint="email",
        notes="Send summary after prep call",
        source_json={"source": "manual"},
    )
    assert created.follow_up_id
    assert created.principal_id == "exec-1"

    listed = runtime.list_follow_ups(principal_id="exec-1", limit=10)
    assert len(listed) == 1
    assert listed[0].follow_up_id == created.follow_up_id

    wrong_scope = runtime.get_follow_up(created.follow_up_id, principal_id="exec-2")
    assert wrong_scope is None

    right_scope = runtime.get_follow_up(created.follow_up_id, principal_id="exec-1")
    assert right_scope is not None
    assert right_scope.topic == "Board follow-up"


def test_inmemory_decision_windows_principal_scope() -> None:
    runtime = MemoryRuntimeService(
        candidates=InMemoryMemoryCandidateRepository(),
        items=InMemoryMemoryItemRepository(),
        entities=InMemoryEntityRepository(),
        relationships=InMemoryRelationshipRepository(),
        commitments=InMemoryCommitmentRepository(),
        decision_windows=InMemoryDecisionWindowRepository(),
        deadline_windows=InMemoryDeadlineWindowRepository(),
        stakeholders=InMemoryStakeholderRepository(),
        authority_bindings=InMemoryAuthorityBindingRepository(),
        delivery_preferences=InMemoryDeliveryPreferenceRepository(),
        follow_ups=InMemoryFollowUpRepository(),
    )

    created = runtime.upsert_decision_window(
        principal_id="exec-1",
        title="Board response decision",
        context="Choose timing and channel for reply",
        opens_at="2026-03-06T08:00:00+00:00",
        closes_at="2026-03-06T12:00:00+00:00",
        urgency="high",
        authority_required="exec",
        status="open",
        notes="Needs decision before board prep",
        source_json={"source": "manual"},
    )
    assert created.decision_window_id
    assert created.principal_id == "exec-1"

    listed = runtime.list_decision_windows(principal_id="exec-1", limit=10)
    assert len(listed) == 1
    assert listed[0].decision_window_id == created.decision_window_id

    wrong_scope = runtime.get_decision_window(created.decision_window_id, principal_id="exec-2")
    assert wrong_scope is None

    right_scope = runtime.get_decision_window(created.decision_window_id, principal_id="exec-1")
    assert right_scope is not None
    assert right_scope.title == "Board response decision"


def test_inmemory_deadline_windows_principal_scope() -> None:
    runtime = MemoryRuntimeService(
        candidates=InMemoryMemoryCandidateRepository(),
        items=InMemoryMemoryItemRepository(),
        entities=InMemoryEntityRepository(),
        relationships=InMemoryRelationshipRepository(),
        commitments=InMemoryCommitmentRepository(),
        decision_windows=InMemoryDecisionWindowRepository(),
        deadline_windows=InMemoryDeadlineWindowRepository(),
        stakeholders=InMemoryStakeholderRepository(),
        authority_bindings=InMemoryAuthorityBindingRepository(),
        delivery_preferences=InMemoryDeliveryPreferenceRepository(),
        follow_ups=InMemoryFollowUpRepository(),
    )

    created = runtime.upsert_deadline_window(
        principal_id="exec-1",
        title="Board prep delivery window",
        start_at="2026-03-07T08:30:00+00:00",
        end_at="2026-03-07T10:00:00+00:00",
        status="open",
        priority="high",
        notes="Draft must be ready before board sync",
        source_json={"source": "manual"},
    )
    assert created.window_id
    assert created.principal_id == "exec-1"

    listed = runtime.list_deadline_windows(principal_id="exec-1", limit=10)
    assert len(listed) == 1
    assert listed[0].window_id == created.window_id

    wrong_scope = runtime.get_deadline_window(created.window_id, principal_id="exec-2")
    assert wrong_scope is None

    right_scope = runtime.get_deadline_window(created.window_id, principal_id="exec-1")
    assert right_scope is not None
    assert right_scope.title == "Board prep delivery window"


def test_inmemory_stakeholders_principal_scope() -> None:
    runtime = MemoryRuntimeService(
        candidates=InMemoryMemoryCandidateRepository(),
        items=InMemoryMemoryItemRepository(),
        entities=InMemoryEntityRepository(),
        relationships=InMemoryRelationshipRepository(),
        commitments=InMemoryCommitmentRepository(),
        decision_windows=InMemoryDecisionWindowRepository(),
        deadline_windows=InMemoryDeadlineWindowRepository(),
        stakeholders=InMemoryStakeholderRepository(),
        authority_bindings=InMemoryAuthorityBindingRepository(),
        delivery_preferences=InMemoryDeliveryPreferenceRepository(),
        follow_ups=InMemoryFollowUpRepository(),
    )

    created = runtime.upsert_stakeholder(
        principal_id="exec-1",
        display_name="Sam Stakeholder",
        channel_ref="email:sam@example.com",
        authority_level="approver",
        importance="high",
        response_cadence="fast",
        tone_pref="diplomatic",
        sensitivity="confidential",
        escalation_policy="notify_exec",
        open_loops_json={"board_follow_up": "open"},
        friction_points_json={"scheduling": "tight"},
        last_interaction_at="2026-03-06T15:30:00+00:00",
        status="active",
        notes="Needs concise summaries",
    )
    assert created.stakeholder_id
    assert created.principal_id == "exec-1"

    listed = runtime.list_stakeholders(principal_id="exec-1", limit=10)
    assert len(listed) == 1
    assert listed[0].stakeholder_id == created.stakeholder_id

    wrong_scope = runtime.get_stakeholder(created.stakeholder_id, principal_id="exec-2")
    assert wrong_scope is None

    right_scope = runtime.get_stakeholder(created.stakeholder_id, principal_id="exec-1")
    assert right_scope is not None
    assert right_scope.display_name == "Sam Stakeholder"
