from __future__ import annotations

import uuid

from app.domain.models import IntentSpecV3, PlanSpec, PlanStepSpec, now_utc_iso
from app.services.task_contracts import TaskContractService


class PlannerService:
    def __init__(self, task_contracts: TaskContractService) -> None:
        self._task_contracts = task_contracts

    def _build_rewrite_steps(self, intent: IntentSpecV3) -> tuple[PlanStepSpec, ...]:
        approval_required = intent.approval_class not in {"", "none"}
        prepare_step = PlanStepSpec(
            step_key="step_input_prepare",
            step_kind="system_task",
            tool_name="",
            evidence_required=(),
            approval_required=False,
            reversible=False,
            expected_artifact="",
            fallback="request_human_intervention",
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
            depends_on=("step_input_prepare",),
            input_keys=("normalized_text", "text_length"),
            output_keys=("allow", "requires_approval", "reason", "retention_policy"),
        )
        save_step = PlanStepSpec(
            step_key="step_artifact_save",
            step_kind="tool_call",
            tool_name="artifact_repository",
            evidence_required=intent.evidence_requirements,
            approval_required=approval_required,
            reversible=False,
            expected_artifact=intent.deliverable_type,
            fallback="request_human_intervention",
            depends_on=("step_policy_evaluate",),
            input_keys=("normalized_text",),
            output_keys=("artifact_id", "receipt_id", "cost_id"),
        )
        return (prepare_step, policy_step, save_step)

    def compile_intent(
        self,
        *,
        task_key: str,
        principal_id: str,
        goal: str,
    ) -> IntentSpecV3:
        contract = self._task_contracts.contract_or_default(task_key)
        budget_class = str(contract.budget_policy_json.get("class") or "low")
        return IntentSpecV3(
            principal_id=str(principal_id or "local-user"),
            goal=str(goal or ""),
            task_type=contract.task_key,
            deliverable_type=contract.deliverable_type,
            risk_class=contract.default_risk_class,
            approval_class=contract.default_approval_class,
            budget_class=budget_class,
            allowed_tools=contract.allowed_tools,
            evidence_requirements=contract.evidence_requirements,
            desired_artifact=contract.deliverable_type,
            memory_write_policy=contract.memory_write_policy,
        )

    def build_plan(
        self,
        *,
        task_key: str,
        principal_id: str,
        goal: str,
    ) -> tuple[IntentSpecV3, PlanSpec]:
        intent = self.compile_intent(task_key=task_key, principal_id=principal_id, goal=goal)
        plan = PlanSpec(
            plan_id=str(uuid.uuid4()),
            task_key=intent.task_type,
            principal_id=intent.principal_id,
            created_at=now_utc_iso(),
            steps=self._build_rewrite_steps(intent),
        )
        return intent, plan
