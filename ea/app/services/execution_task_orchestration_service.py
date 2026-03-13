from __future__ import annotations

import uuid
from typing import Callable

from app.domain.models import (
    Artifact,
    ExecutionSession,
    IntentSpecV3,
    PlanSpec,
    PlanStepSpec,
    TaskExecutionRequest,
    now_utc_iso,
    validate_plan_spec,
)
from app.repositories.ledger import ExecutionLedgerRepository
from app.services.memory_reasoning_service import MemoryReasoningService
from app.services.planner import PlannerService
from app.services.skills import SkillCatalogService
from app.services.task_contracts import TaskContractService
from app.services.execution_async_state_service import ExecutionAsyncStateService


class ExecutionTaskOrchestrationService:
    def __init__(
        self,
        *,
        ledger: ExecutionLedgerRepository,
        planner: PlannerService | None,
        task_contracts: TaskContractService | None,
        execute_next_ready_step: Callable[[str], Artifact | None],
        fetch_session_snapshot: Callable[[str], object | None],
        async_state_service: ExecutionAsyncStateService,
        memory_reasoning_service: MemoryReasoningService | None = None,
        skills: SkillCatalogService | None = None,
    ) -> None:
        self._ledger = ledger
        self._planner = planner
        self._task_contracts = task_contracts
        self._execute_next_ready_step = execute_next_ready_step
        self._fetch_session_snapshot = fetch_session_snapshot
        self._async_state_service = async_state_service
        self._memory_reasoning_service = memory_reasoning_service
        self._skills = skills

    def execute_task_artifact(self, req: TaskExecutionRequest) -> Artifact:
        task_key, skill_key = self.resolve_task_selector(req)
        principal_id = self.require_effective_principal(req.principal_id)
        goal = str(req.goal or "").strip() or self.default_goal_for_task(task_key)
        if self._planner:
            intent, plan = self._planner.build_plan(
                task_key=task_key,
                principal_id=principal_id,
                goal=goal,
            )
        else:
            intent = self.fallback_intent(task_key=task_key, principal_id=principal_id, goal=goal)
            plan = self.fallback_plan(intent)
        validate_plan_spec(plan)
        session = self._ledger.start_session(intent)
        correlation_id = str(uuid.uuid4())
        self._append_plan_events(session, intent, plan)
        task_input_json = self.normalized_task_input_json(
            req,
            principal_id=principal_id,
            task_key=task_key,
            skill_key=skill_key,
            goal=goal,
        )
        self._start_plan_steps(
            session=session,
            plan=plan,
            task_input_json=task_input_json,
            correlation_id=correlation_id,
        )
        artifact = self._execute_next_ready_step(session.session_id)
        snapshot = self._fetch_session_snapshot(session.session_id)
        if snapshot is not None:
            self._async_state_service.raise_for_snapshot_state(snapshot)
            session_row = getattr(snapshot, "session", None)
            if session_row is not None and getattr(session_row, "status", "") == "completed":
                if artifact is not None:
                    return artifact
                snapshot_artifacts = list(getattr(snapshot, "artifacts", []) or [])
                if snapshot_artifacts:
                    return snapshot_artifacts[-1]
        if artifact is not None:
            return artifact
        raise RuntimeError(f"queued task did not execute: {session.session_id}")

    def default_goal_for_task(self, task_key: str) -> str:
        key = str(task_key or "").strip() or "rewrite_text"
        if key == "rewrite_text":
            return "rewrite supplied text into an artifact"
        return f"execute {key} into an artifact"

    def normalized_task_input_json(
        self,
        req: TaskExecutionRequest,
        *,
        principal_id: str | None = None,
        task_key: str | None = None,
        skill_key: str | None = None,
        goal: str | None = None,
    ) -> dict[str, object]:
        payload = {str(key): value for key, value in dict(req.input_json or {}).items() if str(key).strip()}
        context_refs = tuple(str(value or "").strip() for value in (req.context_refs or ()) if str(value or "").strip())
        text_alias = str(getattr(req, "text", "") or "").strip()
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
        resolved_principal = str(principal_id or getattr(req, "principal_id", "") or "").strip()
        resolved_task_key = str(task_key or getattr(req, "task_key", "") or "").strip() or "rewrite_text"
        resolved_skill_key = str(skill_key or getattr(req, "skill_key", "") or "").strip()
        if resolved_skill_key:
            payload.setdefault("skill_key", resolved_skill_key)
        if self._memory_reasoning_service is not None and resolved_principal:
            payload["context_pack"] = self._memory_reasoning_service.build_context_pack(
                principal_id=resolved_principal,
                task_key=resolved_task_key,
                goal=str(goal or getattr(req, "goal", "") or "").strip(),
                context_refs=context_refs,
            ).as_dict()
        return payload

    def resolve_task_selector(self, req: TaskExecutionRequest) -> tuple[str, str]:
        resolved_task_key = str(getattr(req, "task_key", "") or "").strip()
        resolved_skill_key = str(getattr(req, "skill_key", "") or "").strip()
        if resolved_skill_key:
            if self._skills is None:
                raise ValueError("skill_catalog_unavailable")
            row = self._skills.get_skill(resolved_skill_key)
            if row is None:
                raise ValueError(f"skill_not_found:{resolved_skill_key}")
            row_task_key = str(row.task_key or resolved_skill_key).strip() or resolved_skill_key
            if resolved_task_key and resolved_task_key != row_task_key:
                raise ValueError("task_skill_key_mismatch")
            return row_task_key, resolved_skill_key
        return resolved_task_key or "rewrite_text", ""

    def require_effective_principal(self, principal_id: str) -> str:
        resolved = str(principal_id or "").strip()
        if resolved:
            return resolved
        raise ValueError("principal_id_required")

    def legacy_parent_step_id(
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

    def fallback_intent(self, *, task_key: str, principal_id: str, goal: str) -> IntentSpecV3:
        key = str(task_key or "").strip() or "rewrite_text"
        resolved_principal = self.require_effective_principal(principal_id)
        if key == "rewrite_text":
            return IntentSpecV3(
                principal_id=resolved_principal,
                goal=str(goal or self.default_goal_for_task(key)),
                task_type="rewrite_text",
                deliverable_type="rewrite_note",
                risk_class="low",
                approval_class="none",
                budget_class="low",
                allowed_tools=("artifact_repository",),
                desired_artifact="rewrite_note",
                memory_write_policy="reviewed_only",
            )
        contract = self._task_contracts.get_contract_or_raise(key) if self._task_contracts else None
        deliverable_type = str(contract.deliverable_type if contract is not None else "generic_artifact") or "generic_artifact"
        default_risk_class = str(contract.default_risk_class if contract is not None else "low") or "low"
        default_approval_class = str(contract.default_approval_class if contract is not None else "none") or "none"
        budget_class = str((contract.runtime_policy().budget_class if contract is not None else "low") or "low")
        allowed_tools = (
            tuple(str(value) for value in contract.allowed_tools) if contract is not None else ("artifact_repository",)
        )
        if not allowed_tools:
            allowed_tools = ("artifact_repository",)
        evidence_requirements = tuple(str(value) for value in (contract.evidence_requirements if contract is not None else ()))
        memory_write_policy = str(contract.memory_write_policy if contract is not None else "reviewed_only") or "reviewed_only"
        return IntentSpecV3(
            principal_id=resolved_principal,
            goal=str(goal or self.default_goal_for_task(key)),
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

    def fallback_plan(self, intent: IntentSpecV3) -> PlanSpec:
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

    def default_action_kind_for_step(self, plan_step: PlanStepSpec) -> str:
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

    def _append_plan_events(self, session: ExecutionSession, intent: IntentSpecV3, plan: PlanSpec) -> None:
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

    def _start_plan_steps(
        self,
        *,
        session: ExecutionSession,
        plan: PlanSpec,
        task_input_json: dict[str, object],
        correlation_id: str,
    ) -> None:
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
                expected_artifact=session.intent.deliverable_type,
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
        created_steps: list[object] = []
        step_ids_by_key: dict[str, str] = {}
        for index, plan_step in enumerate(plan_steps):
            created_step = self._ledger.start_step(
                session.session_id,
                plan_step.step_kind or "tool_call",
                parent_step_id=self.legacy_parent_step_id(plan_step, step_ids_by_key=step_ids_by_key),
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
                    "action_kind": self.default_action_kind_for_step(plan_step),
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
            created_steps.append(created_step)
            step_ids_by_key[str(plan_step.step_key or "")] = str(getattr(created_step, "step_id"))
