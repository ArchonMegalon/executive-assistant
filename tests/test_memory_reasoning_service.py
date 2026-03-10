from __future__ import annotations

from app.repositories.authority_bindings import InMemoryAuthorityBindingRepository
from app.repositories.commitments import InMemoryCommitmentRepository
from app.repositories.communication_policies import InMemoryCommunicationPolicyRepository
from app.repositories.decision_windows import InMemoryDecisionWindowRepository
from app.repositories.deadline_windows import InMemoryDeadlineWindowRepository
from app.repositories.delivery_preferences import InMemoryDeliveryPreferenceRepository
from app.repositories.entities import InMemoryEntityRepository
from app.repositories.follow_up_rules import InMemoryFollowUpRuleRepository
from app.repositories.follow_ups import InMemoryFollowUpRepository
from app.repositories.interruption_budgets import InMemoryInterruptionBudgetRepository
from app.repositories.memory_candidates import InMemoryMemoryCandidateRepository
from app.repositories.memory_items import InMemoryMemoryItemRepository
from app.repositories.relationships import InMemoryRelationshipRepository
from app.repositories.stakeholders import InMemoryStakeholderRepository
from app.services.memory_reasoning_service import MemoryReasoningService
from app.services.memory_runtime import MemoryRuntimeService


def _runtime() -> MemoryRuntimeService:
    return MemoryRuntimeService(
        candidates=InMemoryMemoryCandidateRepository(),
        items=InMemoryMemoryItemRepository(),
        entities=InMemoryEntityRepository(),
        relationships=InMemoryRelationshipRepository(),
        commitments=InMemoryCommitmentRepository(),
        communication_policies=InMemoryCommunicationPolicyRepository(),
        decision_windows=InMemoryDecisionWindowRepository(),
        deadline_windows=InMemoryDeadlineWindowRepository(),
        stakeholders=InMemoryStakeholderRepository(),
        authority_bindings=InMemoryAuthorityBindingRepository(),
        delivery_preferences=InMemoryDeliveryPreferenceRepository(),
        follow_ups=InMemoryFollowUpRepository(),
        follow_up_rules=InMemoryFollowUpRuleRepository(),
        interruption_budgets=InMemoryInterruptionBudgetRepository(),
    )


def test_memory_reasoning_builds_context_pack_with_conflicts_and_risks() -> None:
    runtime = _runtime()
    item = runtime.stage_candidate(
        principal_id="exec-1",
        category="commitment",
        summary="Board follow-up due Friday",
        fact_json={"due_at": "2026-03-14T09:00:00+00:00", "status": "open"},
        source_session_id="session-1",
        source_step_id="step-1",
        confidence=0.92,
    )
    promoted = runtime.promote_candidate(item.candidate_id, reviewer="operator-1")
    assert promoted is not None

    runtime.stage_candidate(
        principal_id="exec-1",
        category="commitment",
        summary="Board follow-up due Friday",
        fact_json={"due_at": "2026-03-10T09:00:00+00:00", "status": "in_progress", "evidence_object_id": "evidence-1"},
        source_session_id="session-2",
        source_step_id="step-2",
        confidence=0.88,
    )
    runtime.upsert_commitment(
        principal_id="exec-1",
        title="Board follow-up due Friday",
        details="Send revised note",
        status="open",
        priority="high",
        due_at="2026-03-10T06:00:00+00:00",
    )
    runtime.upsert_stakeholder(
        principal_id="exec-1",
        display_name="Alex Board",
        channel_ref="alex@example.com",
        importance="high",
        open_loops_json={"board_follow_up": True},
    )
    runtime.upsert_follow_up(
        principal_id="exec-1",
        stakeholder_ref="alex@example.com",
        topic="Board follow-up due Friday",
        status="open",
        due_at="2026-03-10T08:00:00+00:00",
        channel_hint="email",
    )
    runtime.upsert_decision_window(
        principal_id="exec-1",
        title="Approve board statement",
        context="Requires exec sign-off",
        closes_at="2026-03-11T08:00:00+00:00",
        authority_required="executive",
        status="open",
    )
    runtime.upsert_interruption_budget(
        principal_id="exec-1",
        scope="board-comms",
        budget_minutes=60,
        used_minutes=60,
        status="active",
    )

    pack = MemoryReasoningService(runtime).build_context_pack(
        principal_id="exec-1",
        task_key="rewrite_text",
        goal="Draft board follow-up",
        context_refs=(f"memory:item:{promoted[1].item_id}", "thread:board-prep"),
    )

    assert pack.memory_items[0]["item_id"] == promoted[1].item_id
    assert pack.unresolved_refs == ("thread:board-prep",)
    assert any(row.conflict_type == "candidate_item_mismatch" for row in pack.conflicts)
    assert any("requires_conflict_review" in row.reasons for row in pack.promotion_signals)
    assert any(row.risk_type == "commitment_deadline" for row in pack.commitment_risks)
    assert any(row.risk_type == "decision_window" for row in pack.commitment_risks)
    assert any(row.risk_type == "interruption_budget_exhausted" for row in pack.commitment_risks)

