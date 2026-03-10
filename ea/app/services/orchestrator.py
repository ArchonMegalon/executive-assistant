from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from app.domain.models import (
    ApprovalDecision,
    ApprovalRequest,
    Artifact,
    artifact_preview_text,
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
    ToolInvocationRequest,
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
from app.services.execution_runtime_services import (
    ExecutionOperatorRoutingService,
    ExecutionQueueClaimLeaseService,
)
from app.services.human_task_routing_runtime_service import HumanTaskRoutingService
from app.services.operator_task_routing_service import OperatorTaskRoutingService
from app.services.policy import ApprovalRequiredError, PolicyDecisionService, PolicyDeniedError
from app.services.task_contracts import TaskContractService, build_task_contract_service
from app.services.tool_execution import ToolExecutionService


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
        self._tool_execution = tool_execution or ToolExecutionService(artifacts=self._artifacts)
        self._queue_runtime = ExecutionQueueRuntimeService(
            enqueue_step=self._ledger.enqueue_step,
            retry_queue_item=self._ledger.retry_queue_item,
            update_step=self._ledger.update_step,
            set_session_status=self._ledger.set_session_status,
            append_event=self._ledger.append_event,
            step_id_to_retry_key=self._queue_idempotency_key,
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
        human_task_routing_service = HumanTaskRoutingService(
            list_profiles_for_principal=lambda principal_id: self._operator_profiles.list_for_principal(
                principal_id=principal_id,
                status="active",
                limit=200,
            ),
            fetch_session_events=self._ledger.events_for,
        )
        operator_task_routing_service = operator_task_routing or OperatorTaskRoutingService(
            fetch_human_task=self.fetch_human_task,
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
        )
        self._queue_claim_lease_service = ExecutionQueueClaimLeaseService(self._queue_runtime_facade)

    def _required_skill_tags(self, row: HumanTask) -> tuple[str, ...]:
        return self._operator_routing_service.required_skill_tags(row)

    def _required_trust_rank(self, authority_required: str) -> int:
        return self._operator_routing_service.required_trust_rank(authority_required)

    def _required_trust_tier(self, authority_required: str) -> str:
        return self._operator_routing_service.required_trust_tier(authority_required)

    def _operator_match_details(self, profile: OperatorProfile, row: HumanTask) -> dict[str, object]:
        return self._operator_routing_service.operator_match_details(profile, row)

    def _build_human_task_routing_hints(self, row: HumanTask) -> dict[str, object]:
        return self._operator_routing_service.build_human_task_routing_hints(row)

    def _human_task_assignment_events(self, row: HumanTask) -> list[ExecutionEvent]:
        return self._operator_routing_service.human_task_assignment_events(row)

    def _build_human_task_last_transition_summary(self, row: HumanTask) -> dict[str, object]:
        return self._operator_routing_service.build_human_task_last_transition_summary(row)

    def _decorate_human_task(self, row: HumanTask) -> HumanTask:
        return self._operator_routing_service.decorate_human_task(row)

    def _sort_human_tasks(self, rows: list[HumanTask], *, sort: str | None = None) -> list[HumanTask]:
        return self._operator_routing_service.sort_human_tasks(rows, sort=sort)

    def _filter_human_task_rows(
        self,
        rows: list[HumanTask],
        *,
        principal_id: str,
        status: str | None = None,
        role_required: str | None = None,
        priority: str | None = None,
        assigned_operator_id: str | None = None,
        assignment_state: str | None = None,
        assignment_source: str | None = None,
        overdue_only: bool = False,
    ) -> list[HumanTask]:
        return self._operator_routing_service.filter_human_task_rows(
            rows,
            principal_id=principal_id,
            status=status,
            role_required=role_required,
            priority=priority,
            assigned_operator_id=assigned_operator_id,
            assignment_state=assignment_state,
            assignment_source=assignment_source,
            overdue_only=overdue_only,
        )

    def _default_goal_for_task(self, task_key: str) -> str:
        key = str(task_key or "").strip() or "rewrite_text"
        if key == "rewrite_text":
            return "rewrite supplied text into an artifact"
        return f"execute {key} into an artifact"

    def _normalized_task_input_json(self, req: TaskExecutionRequest) -> dict[str, object]:
        payload = {str(key): value for key, value in dict(req.input_json or {}).items() if str(key).strip()}
        context_refs = tuple(str(value or "").strip() for value in (req.context_refs or ()) if str(value or "").strip())
        text_alias = str(req.text or "").strip()
        structured_text = str(
            payload.get("normalized_text") or payload.get("source_text") or payload.get("text") or ""
        ).strip()
        effective_text = text_alias or structured_text
        if effective_text:
            payload.setdefault("source_text", effective_text)
            payload.setdefault("normalized_text", effective_text)
        if "text_length" not in payload and effective_text:
            payload["text_length"] = len(effective_text)
        if context_refs:
            payload["context_refs"] = list(context_refs)
        return payload

    def _legacy_parent_step_id(
        self,
        plan_step: PlanStepSpec,
        *,
        step_ids_by_key: dict[str, str],
    ) -> str | None:
        dependencies = tuple(
            key
            for key in (plan_step.depends_on or ())
            if str(key or "").strip() and str(key or "").strip() in step_ids_by_key
        )
        if len(dependencies) == 1:
            return step_ids_by_key[dependencies[0]]
        return None

    def _require_effective_principal(self, principal_id: str) -> str:
        resolved = str(principal_id or "").strip()
        if resolved:
            return resolved
        raise ValueError("principal_id_required")

    def _fallback_intent(self, *, task_key: str, principal_id: str, goal: str) -> IntentSpecV3:
        key = str(task_key or "").strip() or "rewrite_text"
        resolved_principal = self._require_effective_principal(principal_id)
        if key == "rewrite_text":
            return IntentSpecV3(
                principal_id=resolved_principal,
                goal=str(goal or self._default_goal_for_task(key)),
                task_type="rewrite_text",
                deliverable_type="rewrite_note",
                risk_class="low",
                approval_class="none",
                budget_class="low",
                allowed_tools=("artifact_repository",),
                desired_artifact="rewrite_note",
                memory_write_policy="reviewed_only",
            )
        contract = self._task_contracts.contract_or_default(key) if self._task_contracts else None
        deliverable_type = str(contract.deliverable_type if contract is not None else "generic_artifact") or "generic_artifact"
        default_risk_class = str(contract.default_risk_class if contract is not None else "low") or "low"
        default_approval_class = str(contract.default_approval_class if contract is not None else "none") or "none"
        budget_class = str((contract.budget_policy_json if contract is not None else {}).get("class") or "low")
        allowed_tools = (
            tuple(str(value) for value in contract.allowed_tools) if contract is not None else ("artifact_repository",)
        )
        if not allowed_tools:
            allowed_tools = ("artifact_repository",)
        evidence_requirements = tuple(str(value) for value in (contract.evidence_requirements if contract is not None else ()))
        memory_write_policy = str(contract.memory_write_policy if contract is not None else "reviewed_only") or "reviewed_only"
        return IntentSpecV3(
            principal_id=resolved_principal,
            goal=str(goal or self._default_goal_for_task(key)),
            task_type=key,
            deliverable_type=deliverable_type,
            risk_class=default_risk_class,
            approval_class=default_approval_class,
            budget_class=budget_class,
            allowed_tools=allowed_tools,
            evidence_requirements=evidence_requirements,
            desired_artifact=deliverable_type,
            memory_write_policy=memory_write_policy,
        )

    def _fallback_plan(self, intent: IntentSpecV3) -> PlanSpec:
        prepare_step = PlanStepSpec(
            step_key="step_input_prepare",
            step_kind="system_task",
            tool_name="",
            evidence_required=(),
            approval_required=False,
            reversible=False,
            expected_artifact="",
            fallback="request_human_intervention",
            owner="system",
            authority_class="observe",
            review_class="none",
            failure_strategy="fail",
            timeout_budget_seconds=30,
            max_attempts=1,
            retry_backoff_seconds=0,
            input_keys=("source_text",),
            output_keys=("normalized_text", "text_length"),
        )
        policy_step = PlanStepSpec(
            step_key="step_policy_evaluate",
            step_kind="policy_check",
            tool_name="",
            evidence_required=(),
            approval_required=False,
            reversible=False,
            expected_artifact="",
            fallback="pause_for_approval_or_block",
            owner="system",
            authority_class="observe",
            review_class="none",
            failure_strategy="fail",
            timeout_budget_seconds=30,
            max_attempts=1,
            retry_backoff_seconds=0,
            depends_on=("step_input_prepare",),
            input_keys=("normalized_text", "text_length"),
            output_keys=("allow", "requires_approval", "reason", "retention_policy", "memory_write_allowed"),
        )
        step = PlanStepSpec(
            step_key="step_artifact_save",
            step_kind="tool_call",
            tool_name="artifact_repository",
            evidence_required=intent.evidence_requirements,
            approval_required=intent.approval_class not in {"", "none"},
            reversible=False,
            expected_artifact=intent.deliverable_type,
            fallback="request_human_intervention",
            owner="tool",
            authority_class="draft",
            review_class="none",
            failure_strategy="fail",
            timeout_budget_seconds=60,
            max_attempts=1,
            retry_backoff_seconds=0,
            depends_on=("step_policy_evaluate",),
            input_keys=("normalized_text",),
            output_keys=("artifact_id", "receipt_id", "cost_id"),
        )
        return PlanSpec(
            plan_id=str(uuid.uuid4()),
            task_key=intent.task_type,
            principal_id=intent.principal_id,
            created_at=now_utc_iso(),
            steps=(prepare_step, policy_step, step),
        )

    def _default_action_kind_for_step(self, plan_step: PlanStepSpec) -> str:
        if plan_step.step_kind != "tool_call":
            return ""
        tool_name = str(plan_step.tool_name or "").strip()
        if tool_name == "connector.dispatch":
            return "delivery.send"
        if tool_name == "browseract.extract_account_inventory":
            return "account.extract_inventory"
        if tool_name == "browseract.extract_account_facts":
            return "account.extract"
        if tool_name == "artifact_repository":
            return "artifact.save"
        return tool_name or "artifact.save"

    def _queue_idempotency_key(self, session_id: str, step_id: str) -> str:
        return f"rewrite:{session_id}:{step_id}"

    def _delayed_retry_queue_item(
        self,
        snapshot: ExecutionSessionSnapshot,
    ) -> ExecutionQueueItem | None:
        return self._queue_claim_lease_service.delayed_retry_queue_item(snapshot)

    def _raise_for_async_snapshot_state(self, snapshot: ExecutionSessionSnapshot) -> None:
        if snapshot.session.status == "awaiting_human":
            human_task_id = snapshot.human_tasks[-1].human_task_id if snapshot.human_tasks else ""
            raise HumanTaskRequiredError(
                session_id=snapshot.session.session_id,
                human_task_id=human_task_id,
                status=snapshot.session.status,
            )
        if snapshot.session.status == "awaiting_approval":
            approval_request = next(
                (row for row in self._approvals.list_pending(limit=100) if row.session_id == snapshot.session.session_id),
                None,
            )
            raise ApprovalRequiredError(
                session_id=snapshot.session.session_id,
                approval_id=approval_request.approval_id if approval_request is not None else "",
                status=snapshot.session.status,
            )
        if snapshot.session.status == "blocked":
            decision = next(iter(self._policy_repo.list_recent(limit=1, session_id=snapshot.session.session_id)), None)
            reason = str(decision.reason if decision is not None else "") or "policy_denied"
            raise PolicyDeniedError(reason)
        delayed_retry = self._delayed_retry_queue_item(snapshot)
        if delayed_retry is not None:
            raise AsyncExecutionQueuedError(
                session_id=snapshot.session.session_id,
                status="queued",
                next_attempt_at=delayed_retry.next_attempt_at,
            )

    def _complete_input_prepare_step(self, session_id: str, rewrite_step: ExecutionStep) -> None:
        input_json = self._merged_step_input_json(session_id, rewrite_step)
        source_text = str(input_json.get("source_text") or "").strip()
        plan_id = str(input_json.get("plan_id") or "")
        plan_step_key = str(input_json.get("plan_step_key") or "")
        desired_output_json = dict((rewrite_step.input_json or {}).get("desired_output_json") or {})
        output_json = {
            "normalized_text": source_text,
            "text_length": len(source_text),
            "plan_id": plan_id,
            "plan_step_key": plan_step_key,
        }
        artifact_output_template = str(
            desired_output_json.get("artifact_output_template")
            or input_json.get("artifact_output_template")
            or ""
        ).strip()
        if artifact_output_template == "evidence_pack":
            claims = [str(value or "").strip() for value in (input_json.get("claims") or []) if str(value or "").strip()]
            evidence_refs = [
                str(value or "").strip()
                for value in (input_json.get("evidence_refs") or input_json.get("context_refs") or [])
                if str(value or "").strip()
            ]
            open_questions = [
                str(value or "").strip()
                for value in (input_json.get("open_questions") or [])
                if str(value or "").strip()
            ]
            confidence_value = input_json.get("confidence")
            if confidence_value is None:
                confidence_value = desired_output_json.get("default_confidence")
            try:
                confidence = float(confidence_value if confidence_value is not None else 0.5)
            except (TypeError, ValueError):
                confidence = 0.5
            confidence = min(max(confidence, 0.0), 1.0)
            output_json.update(
                {
                    "structured_output_json": {
                        "format": "evidence_pack",
                        "claims": claims,
                        "evidence_refs": evidence_refs,
                        "open_questions": open_questions,
                        "confidence": confidence,
                    },
                    "preview_text": artifact_preview_text(source_text),
                    "mime_type": str(input_json.get("mime_type") or "text/plain") or "text/plain",
                }
            )
        output_json = self._validate_step_output_contract(
            rewrite_step,
            output_json,
        )
        self._ledger.update_step(
            rewrite_step.step_id,
            state="completed",
            output_json=output_json,
            error_json={},
        )
        self._ledger.append_event(
            session_id,
            "input_prepared",
            {
                "step_id": rewrite_step.step_id,
                "text_length": len(source_text),
                "plan_id": plan_id,
                "plan_step_key": plan_step_key,
            },
        )

    def _dependency_steps_for_step(self, session_id: str, rewrite_step: ExecutionStep) -> list[ExecutionStep]:
        steps = self._ledger.steps_for(session_id)
        lookup = self._dependency_lookup(steps)
        resolved: list[ExecutionStep] = []
        seen: set[str] = set()
        for key in self._step_dependency_keys(rewrite_step):
            row = lookup.get(key)
            if row is None or row.step_id in seen:
                continue
            resolved.append(row)
            seen.add(row.step_id)
        if not resolved and rewrite_step.parent_step_id:
            parent_step = self._ledger.get_step(rewrite_step.parent_step_id)
            if parent_step is not None:
                resolved.append(parent_step)
        return resolved

    def _declared_step_input_keys(self, rewrite_step: ExecutionStep) -> tuple[str, ...]:
        raw = (rewrite_step.input_json or {}).get("input_keys") or ()
        if isinstance(raw, (list, tuple)):
            values = tuple(str(value or "").strip() for value in raw if str(value or "").strip())
            if values:
                return values
        return ()

    def _declared_step_output_keys(self, rewrite_step: ExecutionStep) -> tuple[str, ...]:
        raw = (rewrite_step.input_json or {}).get("output_keys") or ()
        if isinstance(raw, (list, tuple)):
            values = tuple(str(value or "").strip() for value in raw if str(value or "").strip())
            if values:
                return values
        return ()

    def _validate_step_input_contract(self, rewrite_step: ExecutionStep, input_json: dict[str, object]) -> dict[str, object]:
        plan_step_key = str((rewrite_step.input_json or {}).get("plan_step_key") or rewrite_step.step_kind or "")
        for key in self._declared_step_input_keys(rewrite_step):
            if key not in input_json:
                raise RuntimeError(f"missing_step_input:{plan_step_key}:{key}")
        return input_json

    def _validate_step_output_contract(
        self, rewrite_step: ExecutionStep, output_json: dict[str, object]
    ) -> dict[str, object]:
        plan_step_key = str((rewrite_step.input_json or {}).get("plan_step_key") or rewrite_step.step_kind or "")
        for key in self._declared_step_output_keys(rewrite_step):
            if key not in output_json:
                raise RuntimeError(f"missing_step_output:{plan_step_key}:{key}")
        return output_json

    def _merged_step_input_json(self, session_id: str, rewrite_step: ExecutionStep) -> dict[str, object]:
        input_json = dict(rewrite_step.input_json or {})
        declared_input_keys = set(self._declared_step_input_keys(rewrite_step))
        for dependency in self._dependency_steps_for_step(session_id, rewrite_step):
            for key, value in dict(dependency.output_json or {}).items():
                if key not in input_json and (not declared_input_keys or key in declared_input_keys):
                    input_json[key] = value
            human_payload = (dependency.output_json or {}).get("human_returned_payload_json")
            if isinstance(human_payload, dict):
                final_text = str(human_payload.get("final_text") or human_payload.get("content") or "").strip()
                if final_text:
                    if not declared_input_keys or "source_text" in declared_input_keys:
                        input_json["source_text"] = final_text
                    if not declared_input_keys or "normalized_text" in declared_input_keys:
                        input_json["normalized_text"] = final_text
                    input_json["human_task_id"] = str((dependency.output_json or {}).get("human_task_id") or "")
        normalized_text = str(input_json.get("normalized_text") or "").strip()
        if normalized_text and not str(input_json.get("source_text") or "").strip():
            input_json["source_text"] = normalized_text
        source_text = str(input_json.get("source_text") or "").strip()
        if source_text and not str(input_json.get("normalized_text") or "").strip():
            input_json["normalized_text"] = source_text
        if "text_length" not in input_json and source_text:
            input_json["text_length"] = len(source_text)
        # BrowserAct pre-artifact flows project optional live-discovery hint fields in
        # `input_keys`; populate empty defaults so the typed contract stays explicit
        # without forcing callers to send every optional hint on every request.
        optional_defaults: dict[str, object] = {
            "requested_fields": [],
            "service_names": [],
            "instructions": "",
            "account_hints_json": {},
            "run_url": "",
        }
        for key, default in optional_defaults.items():
            if key in declared_input_keys and key not in input_json:
                input_json[key] = list(default) if isinstance(default, list) else dict(default) if isinstance(default, dict) else default
        if not str(input_json.get("content") or "").strip():
            content = str(input_json.get("normalized_text") or input_json.get("source_text") or "").strip()
            if content:
                input_json["content"] = content
        return self._validate_step_input_contract(rewrite_step, input_json)

    def _approval_target_step_for_session(self, session_id: str) -> ExecutionStep | None:
        steps = self._ledger.steps_for(session_id)
        return next(
            (
                row
                for row in reversed(steps)
                if bool((row.input_json or {}).get("approval_required")) or row.step_kind == "tool_call"
            ),
            steps[0] if steps else None,
        )

    def _complete_policy_evaluate_step(self, session_id: str, rewrite_step: ExecutionStep) -> None:
        session = self._ledger.get_session(session_id)
        if session is None:
            raise RuntimeError(f"session missing for policy step: {session_id}")
        input_json = self._merged_step_input_json(session_id, rewrite_step)
        target_step = self._approval_target_step_for_session(session_id)
        target_tool_name = (
            str(((target_step.input_json if target_step is not None else {}) or {}).get("tool_name") or "").strip()
            or "artifact_repository"
        )
        target_action_kind = (
            str(((target_step.input_json if target_step is not None else {}) or {}).get("action_kind") or "").strip()
            or "artifact.save"
        )
        target_step_kind = (
            str(((target_step.input_json if target_step is not None else {}) or {}).get("plan_step_kind") or "").strip()
            or str(target_step.step_kind if target_step is not None else "").strip()
            or "tool_call"
        )
        target_authority_class = (
            str(((target_step.input_json if target_step is not None else {}) or {}).get("authority_class") or "").strip()
            or "observe"
        )
        target_review_class = (
            str(((target_step.input_json if target_step is not None else {}) or {}).get("review_class") or "").strip()
            or "none"
        )
        target_channel = str(((target_step.input_json if target_step is not None else {}) or {}).get("channel") or "").strip()
        normalized_text = str(input_json.get("normalized_text") or input_json.get("source_text") or "").strip()
        decision = self._policy.evaluate_step(
            session.intent,
            normalized_text,
            tool_name=target_tool_name,
            action_kind=target_action_kind,
            channel=target_channel,
            step_kind=target_step_kind,
            authority_class=target_authority_class,
            review_class=target_review_class,
        )
        self._policy_repo.append(session_id, decision)
        self._ledger.append_event(
            session_id,
            "policy_decision",
            {
                "allow": decision.allow,
                "requires_approval": decision.requires_approval,
                "reason": decision.reason,
                "retention_policy": decision.retention_policy,
                "memory_write_allowed": decision.memory_write_allowed,
            },
        )
        output_json = {
            "plan_id": str((rewrite_step.input_json or {}).get("plan_id") or ""),
            "plan_step_key": str((rewrite_step.input_json or {}).get("plan_step_key") or ""),
            "tool_name": target_tool_name,
            "action_kind": target_action_kind,
            "channel": target_channel,
            "step_kind": target_step_kind,
            "authority_class": target_authority_class,
            "review_class": target_review_class,
            "normalized_text": normalized_text,
            "text_length": int(input_json.get("text_length") or len(normalized_text)),
            "allow": decision.allow,
            "requires_approval": decision.requires_approval,
            "reason": decision.reason,
            "retention_policy": decision.retention_policy,
            "memory_write_allowed": decision.memory_write_allowed,
        }
        for key in ("structured_output_json", "preview_text", "mime_type"):
            if key in input_json:
                output_json[key] = input_json[key]
        output_json = self._validate_step_output_contract(rewrite_step, output_json)
        self._ledger.update_step(
            rewrite_step.step_id,
            state="completed",
            output_json=output_json,
            error_json={},
        )
        self._ledger.append_event(
            session_id,
            "policy_step_completed",
            {
                "step_id": rewrite_step.step_id,
                "allow": bool(output_json.get("allow", False)),
                "requires_approval": bool(output_json.get("requires_approval", False)),
                "reason": str(output_json.get("reason") or ""),
            },
        )
        if not decision.allow:
            if target_step is None or target_step.step_id == rewrite_step.step_id:
                self._ledger.update_step(
                    rewrite_step.step_id,
                    state="blocked",
                    output_json=output_json,
                    error_json={"reason": decision.reason},
                )
            else:
                self._ledger.update_step(
                    target_step.step_id,
                    state="blocked",
                    output_json=target_step.output_json,
                    error_json={"reason": decision.reason},
                )
            self._ledger.set_session_status(session_id, "blocked")
            self._ledger.append_event(
                session_id,
                "session_blocked",
                {"reason": decision.reason},
            )
            return
        if decision.requires_approval and target_step is not None and target_step.step_id != rewrite_step.step_id:
            approval_request = self._approvals.create_request(
                session_id,
                target_step.step_id,
                reason="approval_required",
                requested_action_json={
                    "action": target_action_kind,
                    "artifact_kind": str((target_step.input_json or {}).get("expected_artifact") or ""),
                    "text_length": len(normalized_text),
                    "plan_id": str((rewrite_step.input_json or {}).get("plan_id") or ""),
                    "plan_step_key": str((target_step.input_json or {}).get("plan_step_key") or ""),
                    "tool_name": target_tool_name,
                    "channel": target_channel,
                    "step_kind": target_step_kind,
                    "authority_class": target_authority_class,
                    "review_class": target_review_class,
                },
            )
            self._ledger.update_step(
                target_step.step_id,
                state="waiting_approval",
                output_json=target_step.output_json,
                error_json={"reason": "approval_required", "approval_id": approval_request.approval_id},
            )
            self._ledger.set_session_status(session_id, "awaiting_approval")
            self._ledger.append_event(
                session_id,
                "session_paused_for_approval",
                {"reason": "approval_required", "approval_id": approval_request.approval_id},
            )

    def _start_human_task_step(self, session_id: str, rewrite_step: ExecutionStep) -> HumanTask:
        session = self._ledger.get_session(session_id)
        if session is None:
            raise RuntimeError(f"session missing for human-task step: {session_id}")
        input_json = self._merged_step_input_json(session_id, rewrite_step)
        desired_output_json = dict(input_json.get("desired_output_json") or {})
        if not str(desired_output_json.get("format") or "").strip():
            desired_output_json["format"] = str(input_json.get("expected_artifact") or "review_packet")
        priority = str(input_json.get("priority") or "normal").strip() or "normal"
        sla_due_at = str(input_json.get("sla_due_at") or "").strip()
        if not sla_due_at:
            try:
                sla_minutes = int(input_json.get("sla_minutes") or 0)
            except (TypeError, ValueError):
                sla_minutes = 0
            if sla_minutes > 0:
                sla_due_at = (datetime.now(timezone.utc) + timedelta(minutes=sla_minutes)).isoformat()
        row = self.create_human_task(
            session_id=session_id,
            step_id=rewrite_step.step_id,
            principal_id=session.intent.principal_id,
            task_type=str(input_json.get("task_type") or "communications_review"),
            role_required=str(input_json.get("role_required") or "communications_reviewer"),
            brief=str(input_json.get("brief") or "Review the prepared rewrite before finalizing the artifact."),
            authority_required=str(input_json.get("authority_required") or ""),
            why_human=str(input_json.get("why_human") or ""),
            quality_rubric_json=dict(input_json.get("quality_rubric_json") or {}),
            input_json={
                "source_text": str(input_json.get("source_text") or ""),
                "normalized_text": str(input_json.get("normalized_text") or input_json.get("source_text") or ""),
                "text_length": int(input_json.get("text_length") or 0),
                "plan_id": str(input_json.get("plan_id") or ""),
                "plan_step_key": str(input_json.get("plan_step_key") or ""),
            },
            desired_output_json=desired_output_json,
            priority=priority,
            sla_due_at=sla_due_at or None,
            resume_session_on_return=True,
        )
        if bool(input_json.get("auto_assign_if_unique")):
            auto_assign_operator_id = str((row.routing_hints_json or {}).get("auto_assign_operator_id") or "").strip()
            if auto_assign_operator_id:
                updated = self.assign_human_task(
                    row.human_task_id,
                    principal_id=session.intent.principal_id,
                    operator_id=auto_assign_operator_id,
                    assignment_source="auto_preselected",
                    assigned_by_actor_id="orchestrator:auto_preselected",
                )
                if updated is not None:
                    row = updated
        self._ledger.append_event(
            session_id,
            "human_task_step_started",
            {
                "step_id": rewrite_step.step_id,
                "human_task_id": row.human_task_id,
                "task_type": row.task_type,
                "role_required": row.role_required,
                "authority_required": row.authority_required,
                "priority": row.priority,
                "sla_due_at": row.sla_due_at or "",
                "assignment_state": row.assignment_state,
                "assigned_operator_id": row.assigned_operator_id,
                "assignment_source": row.assignment_source,
                "assigned_at": row.assigned_at or "",
                "assigned_by_actor_id": row.assigned_by_actor_id,
            },
        )
        return self._decorate_human_task(row)

    def _complete_tool_step(self, session_id: str, rewrite_step: ExecutionStep) -> Artifact | None:
        input_json = self._merged_step_input_json(session_id, rewrite_step)
        session = self._ledger.get_session(session_id)
        tool_name = str(input_json.get("tool_name") or "artifact_repository") or "artifact_repository"
        action_kind = str(input_json.get("action_kind") or "artifact.save") or "artifact.save"
        self._ledger.append_event(
            session_id,
            "tool_execution_started",
            {
                "step_id": rewrite_step.step_id,
                "tool_name": tool_name,
                "action_kind": action_kind,
            },
        )
        result = self._tool_execution.execute_invocation(
            ToolInvocationRequest(
                session_id=session_id,
                step_id=rewrite_step.step_id,
                tool_name=tool_name,
                action_kind=action_kind,
                payload_json=input_json,
                context_json={
                    "principal_id": session.intent.principal_id if session is not None else "",
                    "correlation_id": rewrite_step.correlation_id,
                    "causation_id": rewrite_step.causation_id,
                },
            )
        )
        receipt = self._ledger.append_tool_receipt(
            session_id,
            rewrite_step.step_id,
            tool_name=result.tool_name,
            action_kind=result.action_kind,
            target_ref=result.target_ref,
            receipt_json=result.receipt_json,
        )
        cost = self._ledger.append_run_cost(
            session_id,
            model_name=result.model_name,
            tokens_in=result.tokens_in,
            tokens_out=result.tokens_out,
            cost_usd=result.cost_usd,
        )
        output_json = dict(result.output_json or {})
        output_json.setdefault("receipt_id", receipt.receipt_id)
        output_json.setdefault("cost_id", cost.cost_id)
        output_json = self._validate_step_output_contract(rewrite_step, output_json)
        self._ledger.update_step(
            rewrite_step.step_id,
            state="completed",
            output_json=output_json,
            error_json={},
        )
        self._ledger.append_event(
            session_id,
            "tool_execution_completed",
            {
                "step_id": rewrite_step.step_id,
                "tool_name": result.tool_name,
                "action_kind": result.action_kind,
                "target_ref": result.target_ref,
            },
        )
        artifact = result.artifacts[0] if result.artifacts else None
        if artifact is not None:
            self._ledger.append_event(
                session_id,
                "artifact_persisted",
                {
                    "artifact_id": artifact.artifact_id,
                    "artifact_kind": artifact.kind,
                    "plan_id": str((result.output_json or {}).get("plan_id") or ""),
                    "plan_step_key": str((result.output_json or {}).get("plan_step_key") or ""),
                },
            )
        return artifact

    def _execute_step_handler(self, session_id: str, rewrite_step: ExecutionStep) -> Artifact | None:
        plan_step_key = str((rewrite_step.input_json or {}).get("plan_step_key") or "")
        if plan_step_key == "step_input_prepare":
            self._complete_input_prepare_step(session_id, rewrite_step)
            return None
        if plan_step_key == "step_policy_evaluate" or rewrite_step.step_kind == "policy_check":
            self._complete_policy_evaluate_step(session_id, rewrite_step)
            return None
        if plan_step_key == "step_human_review" or rewrite_step.step_kind == "human_task":
            self._start_human_task_step(session_id, rewrite_step)
            return None
        if plan_step_key == "step_memory_candidate_stage" or rewrite_step.step_kind == "memory_write":
            self._complete_memory_candidate_step(session_id, rewrite_step)
            return None
        if rewrite_step.step_kind == "tool_call":
            return self._complete_tool_step(session_id, rewrite_step)
        raise RuntimeError(f"unsupported_step_handler:{plan_step_key or rewrite_step.step_kind}")

    def _complete_memory_candidate_step(self, session_id: str, rewrite_step: ExecutionStep) -> None:
        session = self._ledger.get_session(session_id)
        if session is None:
            raise RuntimeError(f"session missing for memory step: {session_id}")
        if self._memory_runtime is None:
            raise RuntimeError("memory_runtime_unavailable")
        input_json = self._merged_step_input_json(session_id, rewrite_step)
        desired_output_json = dict((rewrite_step.input_json or {}).get("desired_output_json") or {})
        category = str(desired_output_json.get("category") or session.intent.deliverable_type or "artifact_fact").strip()
        sensitivity = str(desired_output_json.get("sensitivity") or "internal").strip() or "internal"
        confidence_value = desired_output_json.get("confidence")
        try:
            confidence = float(confidence_value if confidence_value is not None else 0.5)
        except (TypeError, ValueError):
            confidence = 0.5
        confidence = min(max(confidence, 0.0), 1.0)
        memory_write_allowed = bool(input_json.get("memory_write_allowed", session.intent.memory_write_policy != "none"))
        artifact_id = str(input_json.get("artifact_id") or "").strip()
        normalized_text = str(input_json.get("normalized_text") or input_json.get("source_text") or "").strip()
        artifact_structured_output_json: dict[str, object] = {}
        if artifact_id:
            artifact = self._artifacts.get(artifact_id)
            artifact_content = str((artifact.content if artifact is not None else "") or "").strip()
            if artifact_content:
                normalized_text = artifact_content
            artifact_structured_output_json = dict(
                ((artifact.structured_output_json if artifact is not None else {}) or {})
            )
        delivery_id = str(input_json.get("delivery_id") or "").strip()
        delivery_status = str(input_json.get("status") or "").strip()
        binding_id = str(input_json.get("binding_id") or "").strip()
        channel = str(input_json.get("channel") or "").strip()
        recipient = str(input_json.get("recipient") or "").strip()
        if not memory_write_allowed or session.intent.memory_write_policy == "none":
            output_json = self._validate_step_output_contract(
                rewrite_step,
                {
                    "candidate_id": "",
                    "candidate_status": "skipped",
                    "candidate_category": category,
                },
            )
            self._ledger.update_step(
                rewrite_step.step_id,
                state="completed",
                output_json=output_json,
                error_json={},
            )
            self._ledger.append_event(
                session_id,
                "memory_candidate_skipped",
                {"step_id": rewrite_step.step_id, "candidate_category": category},
            )
            return
        summary = normalized_text[:4000]
        fact_json = {
            "artifact_id": artifact_id,
            "deliverable_type": session.intent.deliverable_type,
            "task_key": session.intent.task_type,
            "normalized_text": normalized_text,
            "delivery_id": delivery_id,
            "delivery_status": delivery_status,
            "binding_id": binding_id,
            "channel": channel,
            "recipient": recipient,
        }
        if str(artifact_structured_output_json.get("format") or "").strip() == "evidence_pack":
            fact_json.update(
                {
                    "evidence_pack": artifact_structured_output_json,
                    "claims": list(artifact_structured_output_json.get("claims") or []),
                    "evidence_refs": list(artifact_structured_output_json.get("evidence_refs") or []),
                    "open_questions": list(artifact_structured_output_json.get("open_questions") or []),
                }
            )
        evidence_object_id = str(input_json.get("evidence_object_id") or "").strip()
        citation_handle = str(input_json.get("citation_handle") or "").strip()
        if evidence_object_id:
            fact_json["evidence_object_id"] = evidence_object_id
        if citation_handle:
            fact_json["citation_handle"] = citation_handle
        candidate = self._memory_runtime.stage_candidate(
            principal_id=session.intent.principal_id,
            category=category,
            summary=summary,
            fact_json=fact_json,
            source_session_id=session_id,
            source_step_id=rewrite_step.step_id,
            confidence=confidence,
            sensitivity=sensitivity,
        )
        output_json = self._validate_step_output_contract(
            rewrite_step,
            {
                "candidate_id": candidate.candidate_id,
                "candidate_status": candidate.status,
                "candidate_category": candidate.category,
            },
        )
        self._ledger.update_step(
            rewrite_step.step_id,
            state="completed",
            output_json=output_json,
            error_json={},
        )
        self._ledger.append_event(
            session_id,
            "memory_candidate_staged",
            {
                "step_id": rewrite_step.step_id,
                "candidate_id": candidate.candidate_id,
                "candidate_category": candidate.category,
            },
        )

    def _step_dependency_keys(self, row: ExecutionStep) -> tuple[str, ...]:
        raw = (row.input_json or {}).get("depends_on") or ()
        if isinstance(raw, (list, tuple)):
            values = tuple(str(value or "").strip() for value in raw if str(value or "").strip())
            if values:
                return values
        if row.parent_step_id:
            return (f"step-id:{row.parent_step_id}",)
        return ()

    def _dependency_lookup(self, steps: list[ExecutionStep]) -> dict[str, ExecutionStep]:
        lookup: dict[str, ExecutionStep] = {}
        for row in steps:
            step_key = str((row.input_json or {}).get("plan_step_key") or "").strip()
            if step_key:
                lookup[step_key] = row
            lookup[f"step-id:{row.step_id}"] = row
        return lookup

    def _active_queue_step_ids(self, session_id: str) -> set[str]:
        return self._queue_claim_lease_service.active_queue_step_ids(session_id)

    def _queue_item_is_eligible_now(self, row: ExecutionQueueItem) -> bool:
        return self._queue_claim_lease_service.queue_item_is_eligible_now(row)

    def _next_eligible_queue_item_for_session(self, session_id: str) -> ExecutionQueueItem | None:
        return self._queue_claim_lease_service.next_eligible_queue_item_for_session(session_id)

    def _drain_session_inline(
        self,
        session_id: str,
        *,
        stop_before_step_id: str | None = None,
    ) -> Artifact | None:
        return self._queue_claim_lease_service.drain_session_inline(
            session_id,
            stop_before_step_id=stop_before_step_id,
        )

    def _ready_steps(
        self,
        session_id: str,
        *,
        stop_before_step_id: str | None = None,
    ) -> list[ExecutionStep]:
        return self._queue_claim_lease_service.ready_steps(
            session_id,
            stop_before_step_id=stop_before_step_id,
        )

    def _next_ready_step(
        self,
        session_id: str,
        *,
        stop_before_step_id: str | None = None,
    ) -> ExecutionStep | None:
        return self._queue_claim_lease_service.next_ready_step(
            session_id,
            stop_before_step_id=stop_before_step_id,
        )

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

    def _execute_leased_queue_item(
        self,
        queue_item: ExecutionQueueItem,
        *,
        stop_before_step_id: str | None = None,
    ) -> Artifact | None:
        return self._queue_claim_lease_service.execute_leased_queue_item(
            queue_item,
            stop_before_step_id=stop_before_step_id,
        )

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

    def execute_task_artifact(self, req: TaskExecutionRequest) -> Artifact:
        task_key = str(req.task_key or "").strip() or "rewrite_text"
        principal_id = self._require_effective_principal(req.principal_id)
        goal = str(req.goal or "").strip() or self._default_goal_for_task(task_key)
        if self._planner:
            intent, plan = self._planner.build_plan(
                task_key=task_key,
                principal_id=principal_id,
                goal=goal,
            )
        elif self._task_contracts:
            intent = self._fallback_intent(task_key=task_key, principal_id=principal_id, goal=goal)
            plan = self._fallback_plan(intent)
        else:
            intent = self._fallback_intent(task_key=task_key, principal_id=principal_id, goal=goal)
            plan = self._fallback_plan(intent)
        validate_plan_spec(plan)
        session = self._ledger.start_session(intent)
        correlation_id = str(uuid.uuid4())
        self._ledger.append_event(
            session.session_id,
            "intent_compiled",
            {
                "task_type": intent.task_type,
                "risk_class": intent.risk_class,
                "approval_class": intent.approval_class,
            },
        )
        self._ledger.append_event(
            session.session_id,
            "plan_compiled",
            {
                "plan_id": plan.plan_id,
                "task_key": plan.task_key,
                "step_count": len(plan.steps),
                "primary_step": plan.steps[0].step_key if plan.steps else "",
                "step_keys": [step.step_key for step in plan.steps],
                "step_semantics": [
                    {
                        "step_key": step.step_key,
                        "owner": step.owner,
                        "authority_class": step.authority_class,
                        "review_class": step.review_class,
                        "failure_strategy": step.failure_strategy,
                        "timeout_budget_seconds": step.timeout_budget_seconds,
                        "max_attempts": step.max_attempts,
                        "retry_backoff_seconds": step.retry_backoff_seconds,
                    }
                    for step in plan.steps
                ],
            },
        )
        task_input_json = self._normalized_task_input_json(req)
        normalized_text = str(task_input_json.get("source_text") or "").strip()
        plan_steps = tuple(plan.steps) or (
            PlanStepSpec(
                step_key="step_input_prepare",
                step_kind="system_task",
                tool_name="",
                evidence_required=(),
                approval_required=False,
                reversible=False,
                expected_artifact="",
                fallback="request_human_intervention",
                owner="system",
                authority_class="observe",
                review_class="none",
                failure_strategy="fail",
                timeout_budget_seconds=30,
                max_attempts=1,
                retry_backoff_seconds=0,
                input_keys=("source_text",),
                output_keys=("normalized_text", "text_length"),
            ),
            PlanStepSpec(
                step_key="step_policy_evaluate",
                step_kind="policy_check",
                tool_name="",
                evidence_required=(),
                approval_required=False,
                reversible=False,
                expected_artifact="",
                fallback="pause_for_approval_or_block",
                owner="system",
                authority_class="observe",
                review_class="none",
                failure_strategy="fail",
                timeout_budget_seconds=30,
                max_attempts=1,
                retry_backoff_seconds=0,
                depends_on=("step_input_prepare",),
                input_keys=("normalized_text", "text_length"),
                output_keys=("allow", "requires_approval", "reason", "retention_policy", "memory_write_allowed"),
            ),
            PlanStepSpec(
                step_key="step_artifact_save",
                step_kind="tool_call",
                tool_name="artifact_repository",
                evidence_required=(),
                approval_required=False,
                reversible=False,
                expected_artifact=intent.deliverable_type,
                fallback="request_human_intervention",
                owner="tool",
                authority_class="draft",
                review_class="none",
                failure_strategy="fail",
                timeout_budget_seconds=60,
                max_attempts=1,
                retry_backoff_seconds=0,
                depends_on=("step_policy_evaluate",),
                input_keys=("normalized_text",),
                output_keys=("artifact_id", "receipt_id", "cost_id"),
            ),
        )
        created_steps: list[ExecutionStep] = []
        step_ids_by_key: dict[str, str] = {}
        for index, plan_step in enumerate(plan_steps):
            created_steps.append(
                self._ledger.start_step(
                    session.session_id,
                    plan_step.step_kind or "tool_call",
                    parent_step_id=self._legacy_parent_step_id(plan_step, step_ids_by_key=step_ids_by_key),
                    input_json={
                        **task_input_json,
                        "plan_id": plan.plan_id,
                        "plan_step_key": plan_step.step_key,
                        "plan_step_kind": plan_step.step_kind,
                        "tool_name": plan_step.tool_name,
                        "owner": plan_step.owner,
                        "authority_class": plan_step.authority_class,
                        "review_class": plan_step.review_class,
                        "failure_strategy": plan_step.failure_strategy,
                        "timeout_budget_seconds": plan_step.timeout_budget_seconds,
                        "max_attempts": plan_step.max_attempts,
                        "retry_backoff_seconds": plan_step.retry_backoff_seconds,
                        "action_kind": self._default_action_kind_for_step(plan_step),
                        "approval_required": plan_step.approval_required,
                        "expected_artifact": plan_step.expected_artifact,
                        "fallback": plan_step.fallback,
                        "depends_on": list(plan_step.depends_on),
                        "input_keys": list(plan_step.input_keys),
                        "output_keys": list(plan_step.output_keys),
                        "task_type": plan_step.task_type,
                        "role_required": plan_step.role_required,
                        "brief": plan_step.brief,
                        "priority": plan_step.priority,
                        "sla_minutes": plan_step.sla_minutes,
                        "auto_assign_if_unique": plan_step.auto_assign_if_unique,
                        "desired_output_json": dict(plan_step.desired_output_json),
                        "authority_required": plan_step.authority_required,
                        "why_human": plan_step.why_human,
                        "quality_rubric_json": dict(plan_step.quality_rubric_json),
                        "step_index": index,
                        "step_count": len(plan_steps),
                    },
                    correlation_id=correlation_id,
                    causation_id=plan.plan_id,
                    actor_type="assistant",
                    actor_id="orchestrator",
                )
            )
            step_ids_by_key[str(plan_step.step_key or "")] = created_steps[-1].step_id
        next_step = self._next_ready_step(session.session_id)
        if next_step is None:
            raise RuntimeError(f"task queue did not resolve a ready step: {session.session_id}")
        queue_item = self._queue_runtime.enqueue_rewrite_step(session.session_id, next_step.step_id)
        artifact = self.run_queue_item(queue_item.queue_id, lease_owner="inline")
        drained_artifact = self._drain_session_inline(session.session_id)
        if drained_artifact is not None:
            artifact = drained_artifact
        snapshot = self.fetch_session(session.session_id)
        if snapshot is not None:
            self._raise_for_async_snapshot_state(snapshot)
            if snapshot.session.status == "completed":
                if artifact is not None:
                    return artifact
                if snapshot.artifacts:
                    return snapshot.artifacts[-1]
        if artifact is not None:
            return artifact
        raise RuntimeError(f"queued task did not execute: {queue_item.queue_id}")

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
        session = self._ledger.get_session(session_id)
        if session is None:
            raise KeyError("session_not_found")
        self._require_session_principal_alignment(session, principal_id=principal_id)
        step: ExecutionStep | None = None
        if resume_session_on_return and not step_id:
            raise KeyError("step_id_required")
        if step_id:
            step = self._ledger.get_step(step_id)
            if step is None or step.session_id != session.session_id:
                raise KeyError("step_not_found")
        row = self._human_tasks.create(
            session_id=session.session_id,
            step_id=step_id,
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
            resume_session_on_return=resume_session_on_return,
        )
        if row.resume_session_on_return and step is not None:
            self._ledger.update_step(
                step.step_id,
                state="waiting_human",
                output_json=step.output_json,
                error_json={"reason": "human_task_required", "human_task_id": row.human_task_id},
                attempt_count=step.attempt_count,
            )
            self._ledger.set_session_status(session.session_id, "awaiting_human")
            self._ledger.append_event(
                session.session_id,
                "session_paused_for_human_task",
                {
                    "human_task_id": row.human_task_id,
                    "step_id": step.step_id,
                    "role_required": row.role_required,
                },
            )
        self._ledger.append_event(
            session.session_id,
            "human_task_created",
            {
                "human_task_id": row.human_task_id,
                "step_id": row.step_id or "",
                "task_type": row.task_type,
                "role_required": row.role_required,
                "authority_required": row.authority_required,
                "why_human": row.why_human,
                "quality_rubric_json": row.quality_rubric_json,
                "priority": row.priority,
                "sla_due_at": row.sla_due_at or "",
                "desired_output_json": row.desired_output_json,
                "assignment_state": row.assignment_state,
                "assigned_operator_id": row.assigned_operator_id,
                "assignment_source": row.assignment_source,
                "assigned_at": row.assigned_at or "",
                "assigned_by_actor_id": row.assigned_by_actor_id,
                "resume_session_on_return": row.resume_session_on_return,
            },
        )
        return self._decorate_human_task(row)

    def fetch_human_task(self, human_task_id: str, *, principal_id: str) -> HumanTask | None:
        row = self._human_tasks.get(human_task_id)
        if row is None or row.principal_id != str(principal_id or ""):
            return None
        return self._decorate_human_task(row)

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
        session = str(session_id or "").strip()
        if session:
            found = self._ledger.get_session(session)
            if found is None:
                return []
            self._require_session_principal_alignment(found, principal_id=principal_id)
            rows = self._human_tasks.list_for_session(session, limit=max(limit, 1))
            rows = self._filter_human_task_rows(
                rows,
                principal_id=principal_id,
                status=status,
                role_required=role_required,
                priority=priority,
                assigned_operator_id=assigned_operator_id,
                assignment_state=assignment_state,
                assignment_source=assignment_source,
                overdue_only=overdue_only,
            )
            decorated = [self._decorate_human_task(row) for row in rows]
            resolved_operator_id = str(operator_id or "").strip()
            if not resolved_operator_id:
                return self._sort_human_tasks(decorated, sort=sort)
            profile = self.fetch_operator_profile(resolved_operator_id, principal_id=principal_id)
            if profile is None:
                return []
            return self._sort_human_tasks(
                [row for row in decorated if self._operator_matches_human_task(profile, row)],
                sort=sort,
            )
        rows = self._human_tasks.list_for_principal(
            principal_id,
            status=status,
            role_required=role_required,
            priority=priority,
            assigned_operator_id=assigned_operator_id,
            assignment_state=assignment_state,
            assignment_source=assignment_source,
            overdue_only=overdue_only,
            limit=limit,
        )
        resolved_operator_id = str(operator_id or "").strip()
        if not resolved_operator_id:
            return self._sort_human_tasks([self._decorate_human_task(row) for row in rows], sort=sort)
        profile = self.fetch_operator_profile(resolved_operator_id, principal_id=principal_id)
        if profile is None:
            return []
        return self._sort_human_tasks(
            [self._decorate_human_task(row) for row in rows if self._operator_matches_human_task(profile, row)],
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
        resolved_operator_id = str(operator_id or "").strip()
        requested_assignment_source = str(assignment_source or "").strip()
        if resolved_operator_id:
            profile = self.fetch_operator_profile(resolved_operator_id, principal_id=principal_id)
            if profile is None:
                counts: dict[str, int] = {}
            else:
                rows = self._human_tasks.list_for_principal(
                    principal_id,
                    status=status,
                    role_required=role_required,
                    assigned_operator_id=assigned_operator_id,
                    assignment_state=assignment_state,
                    assignment_source=assignment_source,
                    overdue_only=overdue_only,
                    limit=0,
                )
                counts = {}
                for row in rows:
                    if not self._operator_matches_human_task(profile, row):
                        continue
                    key = str(row.priority or "").strip().lower() or "normal"
                    counts[key] = counts.get(key, 0) + 1
        else:
            counts = self._human_tasks.count_by_priority_for_principal(
                principal_id,
                status=status,
                role_required=role_required,
                assigned_operator_id=assigned_operator_id,
                assignment_state=assignment_state,
                assignment_source=assignment_source,
                overdue_only=overdue_only,
            )
        normalized = {
            "urgent": int(counts.get("urgent", 0)),
            "high": int(counts.get("high", 0)),
            "normal": int(counts.get("normal", 0)),
            "low": int(counts.get("low", 0)),
        }
        extra = {
            key: int(value)
            for key, value in counts.items()
            if key not in normalized
        }
        ordered = {**normalized, **dict(sorted(extra.items()))}
        highest_priority = next((key for key in ("urgent", "high", "normal", "low") if ordered.get(key, 0) > 0), "")
        return {
            "status": status,
            "role_required": str(role_required or ""),
            "operator_id": resolved_operator_id,
            "assigned_operator_id": str(assigned_operator_id or ""),
            "assignment_state": str(assignment_state or ""),
            "assignment_source": requested_assignment_source,
            "overdue_only": bool(overdue_only),
            "counts_json": ordered,
            "total": sum(ordered.values()),
            "highest_priority": highest_priority,
        }

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
        found = self.fetch_human_task(human_task_id, principal_id=principal_id)
        if found is None:
            return []
        n = max(1, min(500, int(limit or 100)))
        event_filter = str(event_name or "").strip()
        operator_filter = str(assigned_operator_id or "").strip()
        actor_filter = str(assigned_by_actor_id or "").strip()
        has_source_filter, source_filter = _parse_assignment_source_filter(assignment_source)
        rows = self._human_task_assignment_events(found)
        if event_filter:
            rows = [event for event in rows if event.name == event_filter]
        if operator_filter:
            rows = [
                event
                for event in rows
                if str((event.payload or {}).get("assigned_operator_id") or (event.payload or {}).get("operator_id") or "")
                == operator_filter
            ]
        if actor_filter:
            rows = [
                event
                for event in rows
                if str((event.payload or {}).get("assigned_by_actor_id") or "") == actor_filter
            ]
        if has_source_filter:
            rows = [
                event
                for event in rows
                if str((event.payload or {}).get("assignment_source") or "") == source_filter
            ]
        if len(rows) <= n:
            return rows
        return rows[-n:]

    def _operator_matches_human_task(self, profile: OperatorProfile, row: HumanTask) -> bool:
        return self._operator_routing_service.operator_matches_human_task(profile, row)

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
        row = self._operator_profiles.upsert_profile(
            principal_id=principal_id,
            operator_id=operator_id,
            display_name=display_name,
            roles=roles,
            skill_tags=skill_tags,
            trust_tier=trust_tier,
            status=status,
            notes=notes,
        )
        return row

    def fetch_operator_profile(self, operator_id: str, *, principal_id: str) -> OperatorProfile | None:
        row = self._operator_profiles.get(operator_id)
        if row is None or row.principal_id != str(principal_id or ""):
            return None
        return row

    def list_operator_profiles(
        self,
        *,
        principal_id: str,
        status: str | None = None,
        limit: int = 100,
    ) -> list[OperatorProfile]:
        return self._operator_profiles.list_for_principal(
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
        found = self.fetch_human_task(human_task_id, principal_id=principal_id)
        if found is None:
            return None
        updated = self._operator_routing_service.claim_human_task(
            human_task_id,
            principal_id=principal_id,
            operator_id=operator_id,
            assigned_by_actor_id=assigned_by_actor_id,
        )
        if updated is None:
            return None
        return self._decorate_human_task(updated)

    def assign_human_task(
        self,
        human_task_id: str,
        *,
        principal_id: str,
        operator_id: str,
        assignment_source: str = "manual",
        assigned_by_actor_id: str | None = None,
    ) -> HumanTask | None:
        found = self.fetch_human_task(human_task_id, principal_id=principal_id)
        if found is None:
            return None
        updated = self._operator_routing_service.assign_human_task(
            human_task_id,
            principal_id=principal_id,
            operator_id=operator_id,
            assignment_source=assignment_source,
            assigned_by_actor_id=assigned_by_actor_id,
        )
        if updated is None:
            return None
        return self._decorate_human_task(updated)

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
        found = self.fetch_human_task(human_task_id, principal_id=principal_id)
        if found is None:
            return None
        return self._operator_routing_service.return_human_task(
            found,
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
            human_tasks=[self._decorate_human_task(row) for row in self._human_tasks.list_for_session(sid)],
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
        found = self._approvals.decide(
            approval_id,
            decision=decision,
            decided_by=decided_by,
            reason=reason,
        )
        if not found:
            return None
        request, decision_row = found
        self._ledger.append_event(
            request.session_id,
            "approval_decided",
            {
                "approval_id": request.approval_id,
                "step_id": request.step_id,
                "decision": decision_row.decision,
                "decided_by": decision_row.decided_by,
                "reason": decision_row.reason,
            },
        )
        if decision_row.decision == "approved":
            updated_step = self._ledger.update_step(
                request.step_id,
                state="queued",
                output_json={"approval_id": request.approval_id, "decision": "approved"},
                error_json={},
            )
            self._ledger.set_session_status(request.session_id, "running")
            self._ledger.append_event(
                request.session_id,
                "session_resumed_from_approval",
                {"approval_id": request.approval_id, "step_id": request.step_id},
            )
            if updated_step is not None:
                next_step = self._next_ready_step(request.session_id)
                if next_step is None:
                    raise RuntimeError(f"approved queue item did not resolve a ready step: {request.session_id}")
                queue_item = self._queue_runtime.enqueue_rewrite_step(request.session_id, next_step.step_id)
                artifact = self.run_queue_item(queue_item.queue_id, lease_owner="inline")
                drained_artifact = self._drain_session_inline(request.session_id)
                if drained_artifact is not None:
                    artifact = drained_artifact
                if artifact is None:
                    snapshot = self.fetch_session(request.session_id)
                    if snapshot is not None:
                        if snapshot.session.status in {"awaiting_human", "awaiting_approval", "completed"}:
                            return request, decision_row
                        if self._delayed_retry_queue_item(snapshot) is not None:
                            return request, decision_row
                    raise RuntimeError(f"approved queue item did not execute: {queue_item.queue_id}")
        else:
            self._ledger.update_step(
                request.step_id,
                state="blocked",
                error_json={"approval_id": request.approval_id, "decision": decision_row.decision},
            )
            self._ledger.set_session_status(request.session_id, "blocked")
            self._ledger.append_event(
                request.session_id,
                "session_blocked",
                {"reason": f"approval_{decision_row.decision}", "approval_id": request.approval_id},
            )
        return request, decision_row

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
        tool_execution=tool_execution or ToolExecutionService(artifacts=artifact_repo, evidence_runtime=evidence_service),
    )
