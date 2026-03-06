from __future__ import annotations

import uuid

from app.domain.models import IntentSpecV3, PlanSpec, PlanStepSpec, TaskContract, now_utc_iso, validate_plan_spec
from app.services.task_contracts import TaskContractService


def _policy_int(value: object, default: int = 0) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed >= 0 else default


def _policy_bool(value: object, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    raw = str(value or "").strip().lower()
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    return default


def _tool_authority_class(tool_name: str) -> str:
    normalized = str(tool_name or "").strip()
    if normalized == "connector.dispatch":
        return "execute"
    if normalized == "artifact_repository":
        return "draft"
    return "observe"


class PlannerService:
    def __init__(self, task_contracts: TaskContractService) -> None:
        self._task_contracts = task_contracts

    def _require_principal_id(self, principal_id: str) -> str:
        resolved = str(principal_id or "").strip()
        if resolved:
            return resolved
        raise ValueError("principal_id_required")

    def _build_prepare_step(self) -> PlanStepSpec:
        return PlanStepSpec(
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

    def _build_policy_step(
        self,
        *,
        depends_on: tuple[str, ...],
    ) -> PlanStepSpec:
        return PlanStepSpec(
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
            depends_on=depends_on,
            input_keys=("normalized_text", "text_length"),
            output_keys=("allow", "requires_approval", "reason", "retention_policy"),
        )

    def _build_artifact_save_step(
        self,
        intent: IntentSpecV3,
        *,
        depends_on: tuple[str, ...],
        approval_required: bool,
    ) -> PlanStepSpec:
        return PlanStepSpec(
            step_key="step_artifact_save",
            step_kind="tool_call",
            tool_name="artifact_repository",
            evidence_required=intent.evidence_requirements,
            approval_required=approval_required,
            reversible=False,
            expected_artifact=intent.deliverable_type,
            fallback="request_human_intervention",
            owner="tool",
            authority_class=_tool_authority_class("artifact_repository"),
            review_class="none",
            failure_strategy="fail",
            timeout_budget_seconds=60,
            max_attempts=1,
            retry_backoff_seconds=0,
            depends_on=depends_on,
            input_keys=("normalized_text",),
            output_keys=("artifact_id", "receipt_id", "cost_id"),
        )

    def _build_dispatch_step(
        self,
        *,
        depends_on: tuple[str, ...],
    ) -> PlanStepSpec:
        return PlanStepSpec(
            step_key="step_connector_dispatch",
            step_kind="tool_call",
            tool_name="connector.dispatch",
            evidence_required=(),
            approval_required=True,
            reversible=False,
            expected_artifact="delivery_receipt",
            fallback="request_human_intervention",
            owner="tool",
            authority_class=_tool_authority_class("connector.dispatch"),
            review_class="none",
            failure_strategy="fail",
            timeout_budget_seconds=60,
            max_attempts=1,
            retry_backoff_seconds=0,
            depends_on=depends_on,
            input_keys=("binding_id", "channel", "recipient", "content"),
            output_keys=("delivery_id", "status", "binding_id"),
        )

    def _human_review_metadata(self, contract: TaskContract) -> dict[str, object]:
        human_review_role = str(contract.budget_policy_json.get("human_review_role") or "").strip()
        human_review_task_type = str(
            contract.budget_policy_json.get("human_review_task_type") or "communications_review"
        ).strip()
        human_review_brief = str(
            contract.budget_policy_json.get("human_review_brief")
            or "Review the prepared rewrite before finalizing the artifact."
        ).strip()
        human_review_priority = str(contract.budget_policy_json.get("human_review_priority") or "normal").strip() or "normal"
        human_review_sla_minutes = _policy_int(contract.budget_policy_json.get("human_review_sla_minutes"), default=0)
        human_review_auto_assign_if_unique = _policy_bool(
            contract.budget_policy_json.get("human_review_auto_assign_if_unique"),
            default=False,
        )
        human_review_authority_required = str(
            contract.budget_policy_json.get("human_review_authority_required") or ""
        ).strip()
        human_review_why_human = str(
            contract.budget_policy_json.get("human_review_why_human")
            or "Human judgment is required before finalizing this review-sensitive rewrite."
        ).strip()
        raw_human_review_output = contract.budget_policy_json.get("human_review_desired_output_json")
        human_review_desired_output_json = (
            {str(key): value for key, value in raw_human_review_output.items()}
            if isinstance(raw_human_review_output, dict)
            else {}
        )
        if not str(human_review_desired_output_json.get("format") or "").strip():
            human_review_desired_output_json["format"] = "review_packet"
        raw_human_review_rubric = contract.budget_policy_json.get("human_review_quality_rubric_json")
        human_review_quality_rubric_json = (
            {str(key): value for key, value in raw_human_review_rubric.items()}
            if isinstance(raw_human_review_rubric, dict)
            else {}
        )
        return {
            "role": human_review_role,
            "task_type": human_review_task_type,
            "brief": human_review_brief,
            "priority": human_review_priority,
            "sla_minutes": human_review_sla_minutes,
            "auto_assign_if_unique": human_review_auto_assign_if_unique,
            "desired_output_json": human_review_desired_output_json,
            "authority_required": human_review_authority_required,
            "why_human": human_review_why_human,
            "quality_rubric_json": human_review_quality_rubric_json,
        }

    def _build_human_review_step(
        self,
        intent: IntentSpecV3,
        *,
        depends_on: tuple[str, ...],
        metadata: dict[str, object],
    ) -> PlanStepSpec | None:
        human_review_role = str(metadata.get("role") or "").strip()
        if not human_review_role:
            return None
        human_review_sla_minutes = _policy_int(metadata.get("sla_minutes"), default=0)
        return PlanStepSpec(
            step_key="step_human_review",
            step_kind="human_task",
            tool_name="",
            evidence_required=intent.evidence_requirements,
            approval_required=False,
            reversible=False,
            expected_artifact="review_packet",
            fallback="request_human_intervention",
            owner="human",
            authority_class="draft",
            review_class="operator",
            failure_strategy="fail",
            timeout_budget_seconds=max(human_review_sla_minutes * 60, 3600) if human_review_sla_minutes else 3600,
            max_attempts=1,
            retry_backoff_seconds=0,
            depends_on=depends_on,
            input_keys=("normalized_text",),
            output_keys=("human_resolution", "human_returned_payload_json"),
            task_type=str(metadata.get("task_type") or "communications_review"),
            role_required=human_review_role,
            brief=str(metadata.get("brief") or "Review the prepared rewrite before finalizing the artifact."),
            priority=str(metadata.get("priority") or "normal"),
            sla_minutes=human_review_sla_minutes,
            auto_assign_if_unique=_policy_bool(metadata.get("auto_assign_if_unique"), default=False),
            desired_output_json=dict(metadata.get("desired_output_json") or {}),
            authority_required=str(metadata.get("authority_required") or ""),
            why_human=str(metadata.get("why_human") or ""),
            quality_rubric_json=dict(metadata.get("quality_rubric_json") or {}),
        )

    def _build_rewrite_steps(self, intent: IntentSpecV3, *, contract: TaskContract) -> tuple[PlanStepSpec, ...]:
        approval_required = intent.approval_class not in {"", "none"}
        human_review_metadata = self._human_review_metadata(contract)
        prepare_step = self._build_prepare_step()
        policy_step = self._build_policy_step(depends_on=("step_input_prepare",))
        steps: list[PlanStepSpec] = [prepare_step, policy_step]
        save_depends_on = ("step_policy_evaluate",)
        human_review_step = self._build_human_review_step(
            intent,
            depends_on=("step_policy_evaluate",),
            metadata=human_review_metadata,
        )
        if human_review_step is not None:
            steps.append(human_review_step)
            save_depends_on = ("step_human_review",)
        steps.append(
            self._build_artifact_save_step(
                intent,
                depends_on=save_depends_on,
                approval_required=approval_required,
            )
        )
        return tuple(steps)

    def _build_artifact_then_dispatch_steps(
        self,
        intent: IntentSpecV3,
        *,
        contract: TaskContract,
    ) -> tuple[PlanStepSpec, ...]:
        human_review_metadata = self._human_review_metadata(contract)
        prepare_step = self._build_prepare_step()
        steps: list[PlanStepSpec] = [prepare_step]
        artifact_depends_on = ("step_input_prepare",)
        human_review_step = self._build_human_review_step(
            intent,
            depends_on=("step_input_prepare",),
            metadata=human_review_metadata,
        )
        if human_review_step is not None:
            steps.append(human_review_step)
            artifact_depends_on = ("step_human_review",)
        steps.append(
            self._build_artifact_save_step(
                intent,
                depends_on=artifact_depends_on,
                approval_required=False,
            )
        )
        steps.append(self._build_policy_step(depends_on=("step_artifact_save",)))
        steps.append(self._build_dispatch_step(depends_on=("step_policy_evaluate",)))
        return tuple(steps)

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
            principal_id=self._require_principal_id(principal_id),
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
        contract = self._task_contracts.contract_or_default(task_key)
        intent = self.compile_intent(task_key=task_key, principal_id=principal_id, goal=goal)
        workflow_template = str(contract.budget_policy_json.get("workflow_template") or "").strip().lower()
        if workflow_template == "artifact_then_dispatch":
            steps = self._build_artifact_then_dispatch_steps(intent, contract=contract)
        else:
            steps = self._build_rewrite_steps(intent, contract=contract)
        plan = PlanSpec(
            plan_id=str(uuid.uuid4()),
            task_key=intent.task_type,
            principal_id=intent.principal_id,
            created_at=now_utc_iso(),
            steps=steps,
        )
        validate_plan_spec(plan)
        return intent, plan
