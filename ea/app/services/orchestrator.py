from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from app.domain.models import (
    ApprovalDecision,
    ApprovalRequest,
    Artifact,
    ExecutionEvent,
    ExecutionQueueItem,
    ExecutionSession,
    ExecutionStep,
    HumanTask,
    IntentSpecV3,
    OperatorProfile,
    PlanSpec,
    PlanStepSpec,
    PolicyDecision,
    RewriteRequest,
    RunCost,
    TaskExecutionRequest,
    ToolReceipt,
    PlanValidationError,
    validate_plan_spec,
    now_utc_iso,
)
from app.repositories.approvals import ApprovalRepository, InMemoryApprovalRepository
from app.repositories.approvals_postgres import PostgresApprovalRepository
from app.repositories.artifacts import ArtifactRepository, InMemoryArtifactRepository
from app.repositories.artifacts_postgres import PostgresArtifactRepository
from app.repositories.human_tasks import (
    HumanTaskRepository,
    InMemoryHumanTaskRepository,
    _parse_assignment_source_filter,
)
from app.repositories.human_tasks_postgres import PostgresHumanTaskRepository
from app.repositories.ledger import ExecutionLedgerRepository, InMemoryExecutionLedgerRepository
from app.repositories.ledger_postgres import PostgresExecutionLedgerRepository
from app.repositories.operator_profiles import InMemoryOperatorProfileRepository, OperatorProfileRepository
from app.repositories.operator_profiles_postgres import PostgresOperatorProfileRepository
from app.repositories.policy_decisions import InMemoryPolicyDecisionRepository, PolicyDecisionRepository
from app.repositories.policy_decisions_postgres import PostgresPolicyDecisionRepository
from app.settings import Settings, ensure_storage_fallback_allowed, get_settings
from app.services.planner import PlannerService
from app.services.evidence_runtime import EvidenceRuntimeService, build_evidence_runtime
from app.services.memory_runtime import MemoryRuntimeService, build_memory_runtime
from app.services.execution_queue_service import ExecutionQueueService
from app.services.execution_queue_runtime_service import ExecutionQueueRuntimeService
from app.services.execution_queue_runtime_facade import ExecutionQueueRuntimeFacade
from app.services.execution_async_state_service import ExecutionAsyncStateService
from app.services.execution_approval_pause_service import ExecutionApprovalPauseService
from app.services.execution_approval_resume_service import ExecutionApprovalResumeService
from app.services.execution_human_task_step_service import ExecutionHumanTaskStepService
from app.services.execution_operator_profile_service import ExecutionOperatorProfileService
from app.services.execution_operator_routing_service import ExecutionOperatorRoutingService
from app.services.execution_queue_claim_lease_service import ExecutionQueueClaimLeaseService
from app.services.execution_step_dependency_service import ExecutionStepDependencyService
from app.services.execution_step_runtime_service import ExecutionStepRuntimeService
from app.services.execution_task_orchestration_service import ExecutionTaskOrchestrationService
from app.services.human_task_routing_runtime_service import HumanTaskRoutingService
from app.services.memory_reasoning_service import MemoryReasoningService
from app.services.operator_task_routing_service import OperatorTaskRoutingService
from app.services.policy import ApprovalRequiredError, PolicyDecisionService, PolicyDeniedError
from app.services.task_contracts import TaskContractService, build_task_contract_service
from app.services.tool_execution import ToolExecutionService
from app.services.tool_runtime import ToolRuntimeService, build_tool_runtime


@dataclass(frozen=True)
class ExecutionSessionSnapshot:
    session: ExecutionSession
    events: list[ExecutionEvent]
    steps: list[ExecutionStep]
    queue_items: list[ExecutionQueueItem]
    receipts: list[ToolReceipt]
    artifacts: list[Artifact]
    run_costs: list[RunCost]
    human_tasks: list[HumanTask]


class HumanTaskRequiredError(RuntimeError):
    def __init__(self, *, session_id: str, human_task_id: str, status: str = "awaiting_human") -> None:
        super().__init__(status)
        self.session_id = session_id
        self.human_task_id = human_task_id
        self.status = status


class AsyncExecutionQueuedError(RuntimeError):
    def __init__(
        self,
        *,
        session_id: str,
        status: str = "queued",
        next_attempt_at: str | None = None,
    ) -> None:
        super().__init__(status)
        self.session_id = session_id
        self.status = status
        self.next_attempt_at = next_attempt_at


class _UnconfiguredToolExecutionService:
    def execute_invocation(self, *_args, **_kwargs):
        raise RuntimeError("tool_execution_unconfigured")


class RewriteOrchestrator:
    def __init__(
        self,
        artifacts: ArtifactRepository | None = None,
        ledger: ExecutionLedgerRepository | None = None,
        policy_repo: PolicyDecisionRepository | None = None,
        approvals: ApprovalRepository | None = None,
        human_tasks: HumanTaskRepository | None = None,
        operator_profiles: OperatorProfileRepository | None = None,
        policy: PolicyDecisionService | None = None,
        task_contracts: TaskContractService | None = None,
        planner: PlannerService | None = None,
        memory_runtime: MemoryRuntimeService | None = None,
        tool_execution: ToolExecutionService | None = None,
        tool_runtime: ToolRuntimeService | None = None,
        queue_service: ExecutionQueueService | None = None,
        operator_task_routing: OperatorTaskRoutingService | None = None,
    ) -> None:
        self._artifacts = artifacts or InMemoryArtifactRepository()
        self._ledger = ledger or InMemoryExecutionLedgerRepository()
        self._policy_repo = policy_repo or InMemoryPolicyDecisionRepository()
        self._approvals = approvals or InMemoryApprovalRepository()
        self._human_tasks = human_tasks or InMemoryHumanTaskRepository()
        self._operator_profiles = operator_profiles or InMemoryOperatorProfileRepository()
        self._policy = policy or PolicyDecisionService()
        self._task_contracts = task_contracts
        self._planner = planner
        self._memory_runtime = memory_runtime
        self._memory_reasoning_service = (
            MemoryReasoningService(self._memory_runtime) if self._memory_runtime is not None else None
        )
        self._tool_execution = tool_execution or _UnconfiguredToolExecutionService()
        self._queue_runtime = ExecutionQueueRuntimeService(
            enqueue_step=self._ledger.enqueue_step,
            retry_queue_item=self._ledger.retry_queue_item,
            update_step=self._ledger.update_step,
            set_session_status=self._ledger.set_session_status,
            append_event=self._ledger.append_event,
            step_id_to_retry_key=ExecutionQueueRuntimeService.default_step_id_to_retry_key,
        )
        self._queue_service = queue_service or ExecutionQueueService(
            lease_queue_item=self._ledger.lease_queue_item,
            lease_next_queue_item=self._ledger.lease_next_queue_item,
            queue_for_session=self._ledger.queue_for_session,
            get_session=self._ledger.get_session,
            get_step=self._ledger.get_step,
            steps_for=self._ledger.steps_for,
            update_step=self._ledger.update_step,
            append_event=self._ledger.append_event,
            complete_queue_item=self._ledger.complete_queue_item,
            fail_queue_item=self._ledger.fail_queue_item,
            complete_session=self._ledger.complete_session,
            set_session_status=self._ledger.set_session_status,
            enqueue_step=self._queue_runtime.enqueue_rewrite_step,
            execute_step=self._execute_step_handler,
            continue_session_queue=lambda session_id, step_id, *, lease_owner, stop_before_step_id=None: self._queue_service.queue_next_step_after(
                session_id,
                step_id,
                lease_owner=lease_owner,
                stop_before_step_id=stop_before_step_id,
            ),
            schedule_retry=self._queue_runtime.schedule_step_retry,
        )
        self._queue_runtime_facade = ExecutionQueueRuntimeFacade(
            queue_service=self._queue_service,
        )
        self._step_dependency_service = ExecutionStepDependencyService(
            get_step=self._ledger.get_step,
            steps_for_session=self._ledger.steps_for,
        )
        human_task_routing_service = HumanTaskRoutingService(
            list_profiles_for_principal=lambda principal_id: self._operator_profiles.list_for_principal(
                principal_id=principal_id,
                status="active",
                limit=200,
            ),
            fetch_session_events=self._ledger.events_for,
        )
        operator_task_routing_service = operator_task_routing or OperatorTaskRoutingService(
            fetch_human_task=self._human_tasks.get,
            claim_human_task=self._human_tasks.claim,
            assign_human_task=self._human_tasks.assign,
            return_human_task=self._human_tasks.return_task,
            get_step=self._ledger.get_step,
            update_step=self._ledger.update_step,
            validate_step_output_contract=self._validate_step_output_contract,
            set_session_status=self._ledger.set_session_status,
            append_event=self._ledger.append_event,
            queue_next_step_after=self._queue_runtime_facade.queue_next_step_after,
            drain_session_inline=self._queue_runtime_facade.drain_session_inline,
            decorate_human_task=human_task_routing_service.decorate_human_task,
        )
        self._human_task_routing_service = human_task_routing_service
        self._operator_task_routing_service = operator_task_routing_service
        self._operator_routing_service = ExecutionOperatorRoutingService(
            human_task_routing=human_task_routing_service,
            operator_task_routing=operator_task_routing_service,
            get_session=self._ledger.get_session,
            get_step=self._ledger.get_step,
            update_step=self._ledger.update_step,
            append_event=self._ledger.append_event,
            set_session_status=self._ledger.set_session_status,
            create_human_task=self._human_tasks.create,
            require_session_principal_alignment=self._require_session_principal_alignment,
            fetch_human_task=self._human_tasks.get,
            list_human_tasks_for_session=self._human_tasks.list_for_session,
            list_human_tasks_for_principal=self._human_tasks.list_for_principal,
            count_human_tasks_by_priority=self._human_tasks.count_by_priority_for_principal,
            fetch_session_for_principal=self.fetch_session_for_principal,
            fetch_operator_profile=self.fetch_operator_profile,
        )
        self._queue_claim_lease_service = ExecutionQueueClaimLeaseService(
            self._queue_runtime_facade,
            self._queue_runtime,
        )
        self._approval_pause_service = ExecutionApprovalPauseService(
            create_request=self._approvals.create_request,
            update_step=self._ledger.update_step,
            set_session_status=self._ledger.set_session_status,
            append_event=self._ledger.append_event,
        )
        self._approval_resume_service = ExecutionApprovalResumeService(
            decide_approval=self._approvals.decide,
            append_event=self._ledger.append_event,
            update_step=self._ledger.update_step,
            set_session_status=self._ledger.set_session_status,
            execute_next_ready_step=lambda session_id: self._queue_claim_lease_service.execute_next_ready_step(
                session_id,
                lease_owner="inline",
                missing_step_error=f"approved queue item did not resolve a ready step: {session_id}",
            ),
            fetch_session=self.fetch_session,
            delayed_retry_queue_item=self._queue_claim_lease_service.delayed_retry_queue_item,
        )
        self._async_state_service = ExecutionAsyncStateService(
            list_pending_approvals=self._approvals.list_pending,
            list_recent_policy_decisions=self._policy_repo.list_recent,
            delayed_retry_queue_item=self._queue_claim_lease_service.delayed_retry_queue_item,
            raise_human_task_required=self._raise_human_task_required,
            raise_approval_required=self._raise_approval_required,
            raise_policy_denied=self._raise_policy_denied,
            raise_async_execution_queued=self._raise_async_execution_queued,
        )
        self._human_task_step_service = ExecutionHumanTaskStepService(
            get_session=self._ledger.get_session,
            merged_step_input_json=self._step_dependency_service.merged_step_input_json,
            create_human_task=self.create_human_task,
            assign_human_task=self.assign_human_task,
            append_event=self._ledger.append_event,
            decorate_human_task=self._operator_routing_service.decorate_human_task,
        )
        self._step_runtime_service = ExecutionStepRuntimeService(
            get_session=self._ledger.get_session,
            get_artifact=self._artifacts.get,
            update_step=self._ledger.update_step,
            append_event=self._ledger.append_event,
            append_policy_decision=self._policy_repo.append,
            append_tool_receipt=self._ledger.append_tool_receipt,
            append_run_cost=self._ledger.append_run_cost,
            set_session_status=self._ledger.set_session_status,
            approval_target_step_for_session=self._step_dependency_service.approval_target_step_for_session,
            step_dependency_service=self._step_dependency_service,
            approval_pause_service=self._approval_pause_service,
            human_task_step_service=self._human_task_step_service,
            policy=self._policy,
            tool_execution=self._tool_execution,
            memory_runtime=self._memory_runtime,
        )
        self._operator_profile_service = ExecutionOperatorProfileService(
            upsert_profile=self._operator_profiles.upsert_profile,
            get_profile=self._operator_profiles.get,
            list_profiles_for_principal=self._operator_profiles.list_for_principal,
        )
        self._task_orchestration_service = ExecutionTaskOrchestrationService(
            ledger=self._ledger,
            planner=self._planner,
            task_contracts=self._task_contracts,
            execute_next_ready_step=lambda session_id: self._queue_claim_lease_service.execute_next_ready_step(
                session_id,
                lease_owner="inline",
                missing_step_error=f"task queue did not resolve a ready step: {session_id}",
            ),
            fetch_session_snapshot=self.fetch_session,
            async_state_service=self._async_state_service,
            memory_reasoning_service=self._memory_reasoning_service,
        )

    def _default_goal_for_task(self, task_key: str) -> str:
        return self._task_orchestration_service.default_goal_for_task(task_key)

    def _normalized_task_input_json(self, req: TaskExecutionRequest) -> dict[str, object]:
        return self._task_orchestration_service.normalized_task_input_json(
            req,
            principal_id=req.principal_id,
            task_key=req.task_key,
            goal=req.goal,
        )

    def _legacy_parent_step_id(
        self,
        plan_step: PlanStepSpec,
        *,
        step_ids_by_key: dict[str, str],
    ) -> str | None:
        return self._task_orchestration_service.legacy_parent_step_id(
            plan_step,
            step_ids_by_key=step_ids_by_key,
        )

    def _require_effective_principal(self, principal_id: str) -> str:
        return self._task_orchestration_service.require_effective_principal(principal_id)

    def _fallback_intent(self, *, task_key: str, principal_id: str, goal: str) -> IntentSpecV3:
        return self._task_orchestration_service.fallback_intent(
            task_key=task_key,
            principal_id=principal_id,
            goal=goal,
        )

    def _fallback_plan(self, intent: IntentSpecV3) -> PlanSpec:
        return self._task_orchestration_service.fallback_plan(intent)

    def _default_action_kind_for_step(self, plan_step: PlanStepSpec) -> str:
        return self._task_orchestration_service.default_action_kind_for_step(plan_step)

    def _delayed_retry_queue_item(
        self,
        snapshot: ExecutionSessionSnapshot,
    ) -> ExecutionQueueItem | None:
        return self._queue_claim_lease_service.delayed_retry_queue_item(snapshot)

    def _raise_for_async_snapshot_state(self, snapshot: ExecutionSessionSnapshot) -> None:
        self._async_state_service.raise_for_snapshot_state(snapshot)

    def _complete_input_prepare_step(self, session_id: str, rewrite_step: ExecutionStep) -> None:
        self._step_runtime_service.complete_input_prepare_step(session_id, rewrite_step)

    def _dependency_steps_for_step(self, session_id: str, rewrite_step: ExecutionStep) -> list[ExecutionStep]:
        return self._step_dependency_service.dependency_steps_for_step(session_id, rewrite_step)

    def _declared_step_input_keys(self, rewrite_step: ExecutionStep) -> tuple[str, ...]:
        return self._step_dependency_service.declared_step_input_keys(rewrite_step)

    def _declared_step_output_keys(self, rewrite_step: ExecutionStep) -> tuple[str, ...]:
        return self._step_dependency_service.declared_step_output_keys(rewrite_step)

    def _validate_step_input_contract(self, rewrite_step: ExecutionStep, input_json: dict[str, object]) -> dict[str, object]:
        return self._step_dependency_service.validate_step_input_contract(rewrite_step, input_json)

    def _validate_step_output_contract(
        self, rewrite_step: ExecutionStep, output_json: dict[str, object]
    ) -> dict[str, object]:
        return self._step_dependency_service.validate_step_output_contract(rewrite_step, output_json)

    def _merged_step_input_json(self, session_id: str, rewrite_step: ExecutionStep) -> dict[str, object]:
        return self._step_dependency_service.merged_step_input_json(session_id, rewrite_step)

    def _complete_policy_evaluate_step(self, session_id: str, rewrite_step: ExecutionStep) -> None:
        self._step_runtime_service.complete_policy_evaluate_step(session_id, rewrite_step)

    def _start_human_task_step(self, session_id: str, rewrite_step: ExecutionStep) -> HumanTask:
        return self._step_runtime_service.start_human_task_step(session_id, rewrite_step)

    def _complete_tool_step(self, session_id: str, rewrite_step: ExecutionStep) -> Artifact | None:
        return self._step_runtime_service.complete_tool_step(session_id, rewrite_step)

    def _execute_step_handler(self, session_id: str, rewrite_step: ExecutionStep) -> Artifact | None:
        return self._step_runtime_service.execute_step(session_id, rewrite_step)

    def _complete_memory_candidate_step(self, session_id: str, rewrite_step: ExecutionStep) -> None:
        self._step_runtime_service.complete_memory_candidate_step(session_id, rewrite_step)

    def _step_dependency_keys(self, row: ExecutionStep) -> tuple[str, ...]:
        return self._step_dependency_service.step_dependency_keys(row)

    def _raise_human_task_required(self, snapshot: ExecutionSessionSnapshot) -> None:
        human_task_id = snapshot.human_tasks[-1].human_task_id if snapshot.human_tasks else ""
        raise HumanTaskRequiredError(
            session_id=snapshot.session.session_id,
            human_task_id=human_task_id,
            status=snapshot.session.status,
        )

    def _raise_approval_required(self, snapshot: ExecutionSessionSnapshot, approval_id: str) -> None:
        raise ApprovalRequiredError(
            session_id=snapshot.session.session_id,
            approval_id=approval_id,
            status=snapshot.session.status,
        )

    def _raise_policy_denied(self, reason: str) -> None:
        raise PolicyDeniedError(reason)

    def _raise_async_execution_queued(
        self,
        snapshot: ExecutionSessionSnapshot,
        next_attempt_at: str | None,
    ) -> None:
        raise AsyncExecutionQueuedError(
            session_id=snapshot.session.session_id,
            status="queued",
            next_attempt_at=next_attempt_at,
        )

    def _dependency_lookup(self, steps: list[ExecutionStep]) -> dict[str, ExecutionStep]:
        return self._step_dependency_service.dependency_lookup(steps)

    def run_queue_item(
        self,
        queue_id: str,
        *,
        lease_owner: str = "inline",
        stop_before_step_id: str | None = None,
    ) -> Artifact | None:
        return self._queue_claim_lease_service.run_queue_item(
            queue_id,
            lease_owner=lease_owner,
            stop_before_step_id=stop_before_step_id,
        )

    def run_next_queue_item(self, *, lease_owner: str = "worker") -> Artifact | None:
        return self._queue_claim_lease_service.run_next_queue_item(lease_owner=lease_owner)

    def _queue_next_step_after(
        self,
        session_id: str,
        step_id: str,
        *,
        lease_owner: str,
        stop_before_step_id: str | None = None,
    ) -> Artifact | None:
        return self._queue_claim_lease_service.queue_next_step_after(
            session_id,
            step_id,
            lease_owner=lease_owner,
            stop_before_step_id=stop_before_step_id,
        )

    def execute_task_artifact(self, req: TaskExecutionRequest) -> Artifact:
        return self._task_orchestration_service.execute_task_artifact(req)

    def build_artifact(self, req: RewriteRequest) -> Artifact:
        return self.execute_task_artifact(
            TaskExecutionRequest(
                task_key="rewrite_text",
                text=req.text,
                principal_id=req.principal_id,
                goal=req.goal,
            )
        )

    def fetch_session_for_principal(
        self,
        session_id: str,
        *,
        principal_id: str,
    ) -> ExecutionSessionSnapshot | None:
        found = self.fetch_session(session_id)
        if found is None:
            return None
        self._require_session_principal_alignment(found.session, principal_id=principal_id)
        return found

    def fetch_artifact(self, artifact_id: str) -> Artifact | None:
        return self._artifacts.get(artifact_id)

    def fetch_artifact_for_principal(
        self,
        artifact_id: str,
        *,
        principal_id: str,
    ) -> tuple[Artifact, ExecutionSessionSnapshot] | None:
        artifact = self.fetch_artifact(artifact_id)
        if artifact is None:
            return None
        requested_principal = self._require_effective_principal(principal_id)
        artifact_principal = str(artifact.principal_id or "").strip()
        if artifact_principal:
            if artifact_principal != requested_principal:
                raise PermissionError("principal_scope_mismatch")
        else:
            # Legacy rows created before explicit artifact ownership still fall back to the
            # linked session scope until the migration/backfill has touched them.
            session = self.fetch_session_for_principal(artifact.execution_session_id, principal_id=principal_id)
            if session is None:
                return None
            return artifact, session
        session = self.fetch_session_for_principal(artifact.execution_session_id, principal_id=principal_id)
        if session is None:
            return None
        return artifact, session

    def fetch_receipt(self, receipt_id: str) -> ToolReceipt | None:
        return self._ledger.get_receipt(receipt_id)

    def fetch_receipt_for_principal(
        self,
        receipt_id: str,
        *,
        principal_id: str,
    ) -> tuple[ToolReceipt, ExecutionSessionSnapshot] | None:
        receipt = self.fetch_receipt(receipt_id)
        if receipt is None:
            return None
        session = self.fetch_session_for_principal(receipt.session_id, principal_id=principal_id)
        if session is None:
            return None
        return receipt, session

    def fetch_run_cost(self, cost_id: str) -> RunCost | None:
        return self._ledger.get_run_cost(cost_id)

    def fetch_run_cost_for_principal(
        self,
        cost_id: str,
        *,
        principal_id: str,
    ) -> tuple[RunCost, ExecutionSessionSnapshot] | None:
        run_cost = self.fetch_run_cost(cost_id)
        if run_cost is None:
            return None
        session = self.fetch_session_for_principal(run_cost.session_id, principal_id=principal_id)
        if session is None:
            return None
        return run_cost, session

    def fetch_approval_request(self, approval_id: str) -> ApprovalRequest | None:
        return self._approvals.get_request(approval_id)

    def fetch_approval_request_for_principal(
        self,
        approval_id: str,
        *,
        principal_id: str,
    ) -> ApprovalRequest | None:
        request = self.fetch_approval_request(approval_id)
        if request is None:
            return None
        session = self.fetch_session_for_principal(request.session_id, principal_id=principal_id)
        if session is None:
            return None
        return request

    def _require_session_principal_alignment(self, session: ExecutionSession, *, principal_id: str) -> None:
        session_principal = self._require_effective_principal(session.intent.principal_id)
        requested_principal = self._require_effective_principal(principal_id)
        if session_principal != requested_principal:
            raise PermissionError("principal_scope_mismatch")

    def create_human_task(
        self,
        *,
        session_id: str,
        principal_id: str,
        task_type: str,
        role_required: str,
        brief: str,
        authority_required: str = "",
        why_human: str = "",
        quality_rubric_json: dict[str, object] | None = None,
        input_json: dict[str, object] | None = None,
        desired_output_json: dict[str, object] | None = None,
        priority: str = "normal",
        sla_due_at: str | None = None,
        step_id: str | None = None,
        resume_session_on_return: bool = False,
    ) -> HumanTask:
        return self._operator_routing_service.create_human_task(
            session_id=session_id,
            principal_id=principal_id,
            task_type=task_type,
            role_required=role_required,
            brief=brief,
            authority_required=authority_required,
            why_human=why_human,
            quality_rubric_json=quality_rubric_json,
            input_json=input_json,
            desired_output_json=desired_output_json,
            priority=priority,
            sla_due_at=sla_due_at,
            step_id=step_id,
            resume_session_on_return=resume_session_on_return,
        )

    def fetch_human_task(self, human_task_id: str, *, principal_id: str) -> HumanTask | None:
        return self._operator_routing_service.fetch_human_task(
            human_task_id,
            principal_id=principal_id,
        )

    def list_human_tasks(
        self,
        *,
        principal_id: str,
        session_id: str | None = None,
        status: str | None = None,
        role_required: str | None = None,
        priority: str | None = None,
        assigned_operator_id: str | None = None,
        assignment_state: str | None = None,
        assignment_source: str | None = None,
        operator_id: str | None = None,
        overdue_only: bool = False,
        limit: int = 50,
        sort: str | None = None,
    ) -> list[HumanTask]:
        return self._operator_routing_service.list_human_tasks(
            principal_id=principal_id,
            session_id=session_id,
            status=status,
            role_required=role_required,
            priority=priority,
            assigned_operator_id=assigned_operator_id,
            assignment_state=assignment_state,
            assignment_source=assignment_source,
            operator_id=operator_id,
            overdue_only=overdue_only,
            limit=limit,
            sort=sort,
        )

    def summarize_human_task_priorities(
        self,
        *,
        principal_id: str,
        status: str = "pending",
        role_required: str | None = None,
        operator_id: str | None = None,
        assigned_operator_id: str | None = None,
        assignment_state: str | None = None,
        assignment_source: str | None = None,
        overdue_only: bool = False,
    ) -> dict[str, object]:
        return self._operator_routing_service.summarize_human_task_priorities(
            principal_id=principal_id,
            status=status,
            role_required=role_required,
            operator_id=operator_id,
            assigned_operator_id=assigned_operator_id,
            assignment_state=assignment_state,
            assignment_source=assignment_source,
            overdue_only=overdue_only,
        )

    def list_human_task_assignment_history(
        self,
        human_task_id: str,
        *,
        principal_id: str,
        event_name: str | None = None,
        assigned_operator_id: str | None = None,
        assigned_by_actor_id: str | None = None,
        assignment_source: str | None = None,
        limit: int = 100,
    ) -> list[ExecutionEvent]:
        return self._operator_routing_service.list_human_task_assignment_history(
            human_task_id,
            principal_id=principal_id,
            event_name=event_name,
            assigned_operator_id=assigned_operator_id,
            assigned_by_actor_id=assigned_by_actor_id,
            assignment_source=assignment_source,
            limit=limit,
        )

    def upsert_operator_profile(
        self,
        *,
        principal_id: str,
        operator_id: str | None = None,
        display_name: str,
        roles: tuple[str, ...] = (),
        skill_tags: tuple[str, ...] = (),
        trust_tier: str = "standard",
        status: str = "active",
        notes: str = "",
    ) -> OperatorProfile:
        return self._operator_profile_service.upsert_operator_profile(
            principal_id=principal_id,
            operator_id=operator_id,
            display_name=display_name,
            roles=roles,
            skill_tags=skill_tags,
            trust_tier=trust_tier,
            status=status,
            notes=notes,
        )

    def fetch_operator_profile(self, operator_id: str, *, principal_id: str) -> OperatorProfile | None:
        return self._operator_profile_service.fetch_operator_profile(
            operator_id,
            principal_id=principal_id,
        )

    def list_operator_profiles(
        self,
        *,
        principal_id: str,
        status: str | None = None,
        limit: int = 100,
    ) -> list[OperatorProfile]:
        return self._operator_profile_service.list_operator_profiles(
            principal_id=principal_id,
            status=status,
            limit=limit,
        )

    def claim_human_task(
        self,
        human_task_id: str,
        *,
        principal_id: str,
        operator_id: str,
        assigned_by_actor_id: str | None = None,
    ) -> HumanTask | None:
        return self._operator_routing_service.claim_human_task(
            human_task_id,
            principal_id=principal_id,
            operator_id=operator_id,
            assigned_by_actor_id=assigned_by_actor_id,
        )

    def assign_human_task(
        self,
        human_task_id: str,
        *,
        principal_id: str,
        operator_id: str,
        assignment_source: str = "manual",
        assigned_by_actor_id: str | None = None,
    ) -> HumanTask | None:
        return self._operator_routing_service.assign_human_task(
            human_task_id,
            principal_id=principal_id,
            operator_id=operator_id,
            assignment_source=assignment_source,
            assigned_by_actor_id=assigned_by_actor_id,
        )

    def return_human_task(
        self,
        human_task_id: str,
        *,
        principal_id: str,
        operator_id: str,
        resolution: str,
        returned_payload_json: dict[str, object] | None = None,
        provenance_json: dict[str, object] | None = None,
    ) -> HumanTask | None:
        return self._operator_routing_service.return_human_task_by_id(
            human_task_id,
            principal_id=principal_id,
            operator_id=operator_id,
            resolution=resolution,
            returned_payload_json=returned_payload_json,
            provenance_json=provenance_json,
        )

    def fetch_session(self, session_id: str) -> ExecutionSessionSnapshot | None:
        session = self._ledger.get_session(session_id)
        if not session:
            return None
        sid = session.session_id
        return ExecutionSessionSnapshot(
            session=session,
            events=self._ledger.events_for(sid),
            steps=self._ledger.steps_for(sid),
            queue_items=self._ledger.queue_for_session(sid),
            receipts=self._ledger.receipts_for(sid),
            artifacts=self._artifacts.list_for_session(sid),
            run_costs=self._ledger.run_costs_for(sid),
            human_tasks=[self._operator_routing_service.decorate_human_task(row) for row in self._human_tasks.list_for_session(sid)],
        )

    def list_policy_decisions(self, limit: int = 50, session_id: str | None = None):
        return self._policy_repo.list_recent(limit=limit, session_id=session_id)

    def list_policy_decisions_for_principal(
        self,
        *,
        principal_id: str,
        limit: int = 50,
        session_id: str | None = None,
    ) -> list[PolicyDecision]:
        n = max(1, min(500, int(limit or 50)))
        rows = self._policy_repo.list_recent(limit=500, session_id=session_id)
        filtered: list[PolicyDecision] = []
        for row in rows:
            try:
                session = self.fetch_session_for_principal(row.session_id, principal_id=principal_id)
            except PermissionError:
                continue
            if session is None:
                continue
            filtered.append(row)
            if len(filtered) >= n:
                break
        return filtered

    def list_pending_approvals(self, limit: int = 50) -> list[ApprovalRequest]:
        return self._approvals.list_pending(limit=limit)

    def list_pending_approvals_for_principal(
        self,
        *,
        principal_id: str,
        limit: int = 50,
    ) -> list[ApprovalRequest]:
        n = max(1, min(500, int(limit or 50)))
        rows = self._approvals.list_pending(limit=500)
        filtered: list[ApprovalRequest] = []
        for row in rows:
            try:
                session = self.fetch_session_for_principal(row.session_id, principal_id=principal_id)
            except PermissionError:
                continue
            if session is None:
                continue
            filtered.append(row)
            if len(filtered) >= n:
                break
        return filtered

    def list_approval_history(self, limit: int = 50, session_id: str | None = None) -> list[ApprovalDecision]:
        return self._approvals.list_history(limit=limit, session_id=session_id)

    def list_approval_history_for_principal(
        self,
        *,
        principal_id: str,
        limit: int = 50,
        session_id: str | None = None,
    ) -> list[ApprovalDecision]:
        n = max(1, min(500, int(limit or 50)))
        rows = self._approvals.list_history(limit=500, session_id=session_id)
        filtered: list[ApprovalDecision] = []
        for row in rows:
            try:
                session = self.fetch_session_for_principal(row.session_id, principal_id=principal_id)
            except PermissionError:
                continue
            if session is None:
                continue
            filtered.append(row)
            if len(filtered) >= n:
                break
        return filtered

    def decide_approval(
        self,
        approval_id: str,
        *,
        decision: str,
        decided_by: str,
        reason: str,
    ) -> tuple[ApprovalRequest, ApprovalDecision] | None:
        return self._approval_resume_service.decide_approval(
            approval_id,
            decision=decision,
            decided_by=decided_by,
            reason=reason,
        )

    def expire_approval(
        self,
        approval_id: str,
        *,
        decided_by: str,
        reason: str,
    ) -> tuple[ApprovalRequest, ApprovalDecision] | None:
        return self.decide_approval(
            approval_id,
            decision="expired",
            decided_by=decided_by,
            reason=reason,
        )


def _backend_mode(settings: Settings) -> str:
    return str(settings.storage.backend or "auto").strip().lower()


def build_execution_ledger(settings: Settings) -> ExecutionLedgerRepository:
    backend = _backend_mode(settings)
    log = logging.getLogger("ea.ledger")
    if backend == "memory":
        ensure_storage_fallback_allowed(settings, "execution ledger configured for memory")
        return InMemoryExecutionLedgerRepository()
    if backend == "postgres":
        if not settings.database_url:
            raise RuntimeError("EA_STORAGE_BACKEND=postgres requires DATABASE_URL")
        return PostgresExecutionLedgerRepository(settings.database_url)

    if settings.database_url:
        try:
            return PostgresExecutionLedgerRepository(settings.database_url)
        except Exception as exc:
            ensure_storage_fallback_allowed(settings, "execution ledger auto fallback", exc)
            log.warning("postgres ledger unavailable in auto mode; falling back to memory: %s", exc)
    ensure_storage_fallback_allowed(settings, "execution ledger auto backend without DATABASE_URL")
    return InMemoryExecutionLedgerRepository()


def build_policy_repo(settings: Settings) -> PolicyDecisionRepository:
    backend = _backend_mode(settings)
    log = logging.getLogger("ea.policy_repo")
    if backend == "memory":
        ensure_storage_fallback_allowed(settings, "policy repo configured for memory")
        return InMemoryPolicyDecisionRepository()
    if backend == "postgres":
        if not settings.database_url:
            raise RuntimeError("EA_STORAGE_BACKEND=postgres requires DATABASE_URL")
        return PostgresPolicyDecisionRepository(settings.database_url)
    if settings.database_url:
        try:
            return PostgresPolicyDecisionRepository(settings.database_url)
        except Exception as exc:
            ensure_storage_fallback_allowed(settings, "policy repo auto fallback", exc)
            log.warning("postgres policy backend unavailable in auto mode; falling back to memory: %s", exc)
    ensure_storage_fallback_allowed(settings, "policy repo auto backend without DATABASE_URL")
    return InMemoryPolicyDecisionRepository()


def build_approval_repo(settings: Settings) -> ApprovalRepository:
    backend = _backend_mode(settings)
    log = logging.getLogger("ea.approvals")
    if backend == "memory":
        ensure_storage_fallback_allowed(settings, "approvals configured for memory")
        return InMemoryApprovalRepository(default_ttl_minutes=settings.policy.approval_ttl_minutes)
    if backend == "postgres":
        if not settings.database_url:
            raise RuntimeError("EA_STORAGE_BACKEND=postgres requires DATABASE_URL")
        return PostgresApprovalRepository(
            settings.database_url,
            default_ttl_minutes=settings.policy.approval_ttl_minutes,
        )
    if settings.database_url:
        try:
            return PostgresApprovalRepository(
                settings.database_url,
                default_ttl_minutes=settings.policy.approval_ttl_minutes,
            )
        except Exception as exc:
            ensure_storage_fallback_allowed(settings, "approvals auto fallback", exc)
            log.warning("postgres approval backend unavailable in auto mode; falling back to memory: %s", exc)
    ensure_storage_fallback_allowed(settings, "approvals auto backend without DATABASE_URL")
    return InMemoryApprovalRepository(default_ttl_minutes=settings.policy.approval_ttl_minutes)


def build_human_task_repo(settings: Settings) -> HumanTaskRepository:
    backend = _backend_mode(settings)
    log = logging.getLogger("ea.human_tasks")
    if backend == "memory":
        ensure_storage_fallback_allowed(settings, "human tasks configured for memory")
        return InMemoryHumanTaskRepository()
    if backend == "postgres":
        if not settings.database_url:
            raise RuntimeError("EA_STORAGE_BACKEND=postgres requires DATABASE_URL")
        return PostgresHumanTaskRepository(settings.database_url)
    if settings.database_url:
        try:
            return PostgresHumanTaskRepository(settings.database_url)
        except Exception as exc:
            ensure_storage_fallback_allowed(settings, "human tasks auto fallback", exc)
            log.warning("postgres human-task backend unavailable in auto mode; falling back to memory: %s", exc)
    ensure_storage_fallback_allowed(settings, "human tasks auto backend without DATABASE_URL")
    return InMemoryHumanTaskRepository()


def build_operator_profile_repo(settings: Settings) -> OperatorProfileRepository:
    backend = _backend_mode(settings)
    log = logging.getLogger("ea.operator_profiles")
    if backend == "memory":
        ensure_storage_fallback_allowed(settings, "operator profiles configured for memory")
        return InMemoryOperatorProfileRepository()
    if backend == "postgres":
        if not settings.database_url:
            raise RuntimeError("EA_STORAGE_BACKEND=postgres requires DATABASE_URL")
        return PostgresOperatorProfileRepository(settings.database_url)
    if settings.database_url:
        try:
            return PostgresOperatorProfileRepository(settings.database_url)
        except Exception as exc:
            ensure_storage_fallback_allowed(settings, "operator profiles auto fallback", exc)
            log.warning("postgres operator-profile backend unavailable in auto mode; falling back to memory: %s", exc)
    ensure_storage_fallback_allowed(settings, "operator profiles auto backend without DATABASE_URL")
    return InMemoryOperatorProfileRepository()


def build_artifact_repo(settings: Settings) -> ArtifactRepository:
    backend = _backend_mode(settings)
    log = logging.getLogger("ea.artifacts")
    if backend == "memory":
        ensure_storage_fallback_allowed(settings, "artifacts configured for memory")
        return InMemoryArtifactRepository()
    if backend == "postgres":
        if not settings.database_url:
            raise RuntimeError("EA_STORAGE_BACKEND=postgres requires DATABASE_URL")
        return PostgresArtifactRepository(
            settings.database_url,
            artifacts_dir=settings.storage.artifacts_dir,
            tenant_id=settings.tenant_id,
        )
    if settings.database_url:
        try:
            return PostgresArtifactRepository(
                settings.database_url,
                artifacts_dir=settings.storage.artifacts_dir,
                tenant_id=settings.tenant_id,
            )
        except Exception as exc:
            ensure_storage_fallback_allowed(settings, "artifacts auto fallback", exc)
            log.warning("postgres artifact backend unavailable in auto mode; falling back to memory: %s", exc)
    ensure_storage_fallback_allowed(settings, "artifacts auto backend without DATABASE_URL")
    return InMemoryArtifactRepository()


def build_default_orchestrator(
    settings: Settings | None = None,
    *,
    artifacts: ArtifactRepository | None = None,
    task_contracts: TaskContractService | None = None,
    planner: PlannerService | None = None,
    evidence_runtime: EvidenceRuntimeService | None = None,
    memory_runtime: MemoryRuntimeService | None = None,
    tool_execution: ToolExecutionService | None = None,
) -> RewriteOrchestrator:
    resolved = settings or get_settings()
    ledger = build_execution_ledger(resolved)
    policy_repo = build_policy_repo(resolved)
    approvals = build_approval_repo(resolved)
    human_tasks = build_human_task_repo(resolved)
    operator_profiles = build_operator_profile_repo(resolved)
    artifact_repo = artifacts or build_artifact_repo(resolved)
    task_contract_service = task_contracts or build_task_contract_service(resolved)
    planner_service = planner or PlannerService(task_contract_service)
    evidence_service = evidence_runtime or build_evidence_runtime(resolved)
    memory_service = memory_runtime or build_memory_runtime(resolved)
    policy = PolicyDecisionService(
        max_rewrite_chars=resolved.policy.max_rewrite_chars,
        approval_required_chars=resolved.policy.approval_required_chars,
    )
    return RewriteOrchestrator(
        artifacts=artifact_repo,
        ledger=ledger,
        policy_repo=policy_repo,
        approvals=approvals,
        human_tasks=human_tasks,
        operator_profiles=operator_profiles,
        policy=policy,
        task_contracts=task_contract_service,
        planner=planner_service,
        memory_runtime=memory_service,
        tool_execution=tool_execution,
    )
