from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.domain.models import Artifact, IntentSpecV3, TaskContract
from app.repositories.authority_bindings import InMemoryAuthorityBindingRepository
from app.repositories.commitments import InMemoryCommitmentRepository
from app.repositories.communication_policies import InMemoryCommunicationPolicyRepository
from app.repositories.deadline_windows import InMemoryDeadlineWindowRepository
from app.repositories.decision_windows import InMemoryDecisionWindowRepository
from app.repositories.delivery_outbox import InMemoryDeliveryOutboxRepository
from app.repositories.delivery_preferences import InMemoryDeliveryPreferenceRepository
from app.repositories.entities import InMemoryEntityRepository
from app.repositories.follow_up_rules import InMemoryFollowUpRuleRepository
from app.repositories.follow_ups import InMemoryFollowUpRepository
from app.repositories.interruption_budgets import InMemoryInterruptionBudgetRepository
from app.repositories.ledger import InMemoryExecutionLedgerRepository
from app.repositories.memory_candidates import InMemoryMemoryCandidateRepository
from app.repositories.memory_items import InMemoryMemoryItemRepository
from app.repositories.observation import InMemoryObservationEventRepository
from app.repositories.relationships import InMemoryRelationshipRepository
from app.repositories.stakeholders import InMemoryStakeholderRepository
from app.repositories.task_contracts import InMemoryTaskContractRepository
from app.services.cognitive_load import CognitiveLoadService
from app.services.channel_runtime import ChannelRuntimeService
from app.services.memory_runtime import MemoryRuntimeService
from app.services.policy import PolicyDecisionService
from app.services.proactive_horizon import ProactiveHorizonService
from app.services.provider_registry import CapabilityRoute
from app.services.replanning import ReplanningService
from app.services.style_reflection import ReflectionRequest, StyleReflectionService
from app.services.task_contracts import TaskContractService


def _memory_runtime() -> MemoryRuntimeService:
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


class _FakeOrchestrator:
    def __init__(self) -> None:
        self.requests = []

    def execute_task_artifact(self, request):  # type: ignore[no-untyped-def]
        self.requests.append(request)
        return Artifact(
            artifact_id=f"artifact-{len(self.requests)}",
            kind="rewrite_note",
            content=str((request.input_json or {}).get("source_text") or ""),
            execution_session_id=f"session-{len(self.requests)}",
            principal_id=request.principal_id,
        )


def test_proactive_horizon_scans_and_dedupes_successful_launches() -> None:
    runtime = _memory_runtime()
    now = datetime.now(timezone.utc)
    decision = runtime.upsert_decision_window(
        principal_id="exec-1",
        title="Board packet",
        context="Need a decision on launch timing",
        closes_at=(now + timedelta(hours=2)).isoformat(),
    )
    _deadline = runtime.upsert_deadline_window(
        principal_id="exec-2",
        title="Partner reply",
        end_at=(now + timedelta(hours=4)).isoformat(),
    )
    _commitment = runtime.upsert_commitment(
        principal_id="exec-3",
        title="Send sponsor follow-up",
        due_at=(now + timedelta(hours=3)).isoformat(),
    )
    observations = InMemoryObservationEventRepository()
    channel_runtime = ChannelRuntimeService(observations=observations, outbox=InMemoryDeliveryOutboxRepository())
    task_contracts = TaskContractService(InMemoryTaskContractRepository())
    orchestrator = _FakeOrchestrator()
    service = ProactiveHorizonService(
        memory_runtime=runtime,
        orchestrator=orchestrator,  # type: ignore[arg-type]
        task_contracts=task_contracts,
        channel_runtime=channel_runtime,
    )

    launched = service.run_once(now=now)
    assert len(launched) == 3
    assert len(orchestrator.requests) == 3
    assert {row.principal_id for row in launched} == {"exec-1", "exec-2", "exec-3"}
    assert {row.task_key for row in launched} == {"decision_briefing", "stakeholder_briefing"}
    assert any(ref == f"decision_window:{decision.decision_window_id}" for ref in orchestrator.requests[0].context_refs)

    second = service.run_once(now=now)
    assert second == ()
    assert len(orchestrator.requests) == 3


def test_builtin_groundwork_contracts_default_to_groundwork_and_review_light() -> None:
    contracts = TaskContractService(InMemoryTaskContractRepository())

    meeting = contracts.get_contract_or_raise("meeting_prep")
    decision = contracts.get_contract_or_raise("decision_briefing")
    stakeholder = contracts.get_contract_or_raise("stakeholder_briefing")

    assert meeting.runtime_policy().brain_profile == "groundwork"
    assert decision.runtime_policy().brain_profile == "groundwork"
    assert stakeholder.runtime_policy().brain_profile == "groundwork"
    assert meeting.runtime_policy().workflow_template == "tool_then_artifact"
    assert decision.runtime_policy().workflow_template == "tool_then_artifact"
    assert stakeholder.runtime_policy().workflow_template == "tool_then_artifact"
    assert meeting.runtime_policy().pre_artifact_capability_key == "structured_generate"
    assert decision.runtime_policy().pre_artifact_capability_key == "structured_generate"
    assert stakeholder.runtime_policy().pre_artifact_capability_key == "structured_generate"
    assert meeting.runtime_policy().posthoc_review_profile == "review_light"
    assert decision.runtime_policy().posthoc_review_profile == "review_light"
    assert stakeholder.runtime_policy().posthoc_review_profile == "review_light"
    assert meeting.runtime_policy().posthoc_review_required is False
    assert decision.runtime_policy().posthoc_review_required is False
    assert stakeholder.runtime_policy().posthoc_review_required is False


def test_proactive_horizon_keeps_in_process_dedupe_when_observation_persist_fails() -> None:
    runtime = _memory_runtime()
    now = datetime.now(timezone.utc)
    runtime.upsert_decision_window(
        principal_id="exec-1",
        title="Board packet",
        context="Need a decision on launch timing",
        closes_at=(now + timedelta(hours=2)).isoformat(),
    )
    task_contracts = TaskContractService(InMemoryTaskContractRepository())
    orchestrator = _FakeOrchestrator()

    class _FlakyChannelRuntime:
        def __init__(self) -> None:
            self._rows = {}
            self.calls = 0

        def find_observation_by_dedupe(self, dedupe_key: str):
            return self._rows.get(dedupe_key)

        def ingest_observation(self, principal_id: str, channel: str, event_type: str, payload=None, *, dedupe_key: str = "", **kwargs):
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("observation_write_failed")
            row = type("ObservationStub", (), {"principal_id": principal_id, "dedupe_key": dedupe_key})()
            self._rows[dedupe_key] = row
            return row

    channel_runtime = _FlakyChannelRuntime()
    service = ProactiveHorizonService(
        memory_runtime=runtime,
        orchestrator=orchestrator,  # type: ignore[arg-type]
        task_contracts=task_contracts,
        channel_runtime=channel_runtime,  # type: ignore[arg-type]
    )

    first = service.run_once(now=now)
    second = service.run_once(now=now)

    assert first == ()
    assert len(second) == 1
    assert len(orchestrator.requests) == 1


def test_style_reflection_stages_communication_policy_candidate_for_major_human_rewrite() -> None:
    runtime = _memory_runtime()
    service = StyleReflectionService(runtime)

    candidate = service.maybe_stage_reflection(
        ReflectionRequest(
            principal_id="exec-1",
            source_session_id="session-1",
            source_step_id="step-1",
            human_task_id="human-1",
            original_text="We should share a detailed narrative about the board meeting and its implications.",
            edited_text="- Share the board decision\n- Note the launch impact\n- Keep the follow-up short",
            stakeholder_hint="board",
        )
    )

    assert candidate is not None
    assert candidate.category == "communication_policy"
    assert "bullet" in candidate.summary.lower()

    trivial = service.maybe_stage_reflection(
        ReflectionRequest(
            principal_id="exec-1",
            source_session_id="session-2",
            source_step_id="step-2",
            human_task_id="human-2",
            original_text="Short note.",
            edited_text="Short note!",
        )
    )
    assert trivial is None


def test_channel_runtime_defers_low_priority_delivery_when_focus_budget_is_exhausted() -> None:
    runtime = _memory_runtime()
    observations = InMemoryObservationEventRepository()
    cognitive_load = CognitiveLoadService(
        count_recent_for_principal=observations.count_recent_for_principal,
        memory_runtime=runtime,
    )
    channel_runtime = ChannelRuntimeService(
        observations=observations,
        outbox=InMemoryDeliveryOutboxRepository(),
        cognitive_load=cognitive_load,
        policy=PolicyDecisionService(),
    )

    for index in range(11):
        channel_runtime.ingest_observation(
            principal_id="exec-1",
            channel="chat",
            event_type=f"principal.message.{index}",
            payload={"principal_originated": True},
            auth_context_json={"actor_type": "principal"},
        )

    deferred = channel_runtime.queue_delivery(
        channel="email",
        recipient="ceo@example.com",
        content="Routine status update",
        metadata={"principal_id": "exec-1", "priority": "normal"},
    )
    assert deferred.status == "retry"
    assert deferred.last_error == "deferred_by_interruption_budget"

    urgent = channel_runtime.queue_delivery(
        channel="email",
        recipient="ceo@example.com",
        content="Urgent decision needed",
        metadata={"principal_id": "exec-1", "priority": "urgent"},
    )
    assert urgent.status == "queued"


class _FakeProviderRegistry:
    def candidate_routes_by_capability_with_context(
        self,
        *,
        capability_key: str,
        principal_id: str | None = None,
        allowed_tools: tuple[str, ...] = (),
        provider_hints: tuple[str, ...] = (),
        require_executable: bool = True,
    ) -> tuple[CapabilityRoute, ...]:
        assert capability_key == "demo_generate"
        return (
            CapabilityRoute(
                provider_key="primary",
                capability_key="demo_generate",
                tool_name="tool.primary",
                executable=True,
            ),
            CapabilityRoute(
                provider_key="backup",
                capability_key="demo_generate",
                tool_name="tool.backup",
                executable=True,
            ),
        )


def test_replanning_service_appends_recovery_step_with_same_plan_step_key() -> None:
    ledger = InMemoryExecutionLedgerRepository()
    session = ledger.start_session(
        IntentSpecV3(
            principal_id="exec-1",
            goal="demo",
            task_type="rewrite_text",
            deliverable_type="rewrite_note",
            risk_class="low",
            approval_class="none",
            budget_class="low",
            allowed_tools=("tool.primary", "tool.backup"),
        )
    )
    step = ledger.start_step(
        session.session_id,
        "tool_call",
        input_json={
            "tool_name": "tool.primary",
            "capability_key": "demo_generate",
            "plan_step_key": "step_demo",
            "failure_strategy": "replan",
            "replan_max_attempts": 2,
        },
    )
    queue_item = ledger.enqueue_step(
        session.session_id,
        step.step_id,
        idempotency_key=f"rewrite:{session.session_id}:{step.step_id}",
    )
    service = ReplanningService(
        get_session=ledger.get_session,
        get_step=ledger.get_step,
        start_step=ledger.start_step,
        enqueue_step=ledger.enqueue_step,
        set_session_status=ledger.set_session_status,
        append_event=ledger.append_event,
        provider_registry=_FakeProviderRegistry(),  # type: ignore[arg-type]
    )

    result = service.request_replan(queue_item, step, RuntimeError("primary failed"))

    assert result is not None
    assert result.replacement_tool_name == "tool.backup"
    steps = ledger.steps_for(session.session_id)
    assert len(steps) == 2
    replacement = steps[-1]
    assert replacement.input_json["tool_name"] == "tool.backup"
    assert replacement.input_json["plan_step_key"] == "step_demo"
    assert replacement.input_json["replan_attempts"] == 1


def test_runtime_policy_accepts_replan_failure_strategy() -> None:
    contract = TaskContract(
        task_key="rewrite_text",
        deliverable_type="rewrite_note",
        default_risk_class="low",
        default_approval_class="none",
        allowed_tools=("artifact_repository",),
        evidence_requirements=(),
        memory_write_policy="reviewed_only",
        budget_policy_json={"artifact_failure_strategy": "replan"},
        updated_at="2026-03-19T00:00:00+00:00",
        runtime_policy_json={},
    )

    assert contract.runtime_policy().artifact_retry.failure_strategy == "replan"
