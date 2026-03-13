from __future__ import annotations

import uuid
from collections.abc import Callable

from app.domain.models import (
    IntentSpecV3,
    PlanSpec,
    PlanStepSpec,
    PlanValidationError,
    TaskContract,
    TaskContractHumanReviewPolicy,
    TaskContractRetryPolicy,
    now_utc_iso,
    validate_plan_spec,
)
from app.services.provider_registry import CapabilityRoute, ProviderRegistryService
from app.services.task_contracts import TaskContractService
from app.services.tool_execution_common import ToolExecutionError


def _tool_authority_class(tool_name: str) -> str:
    normalized = str(tool_name or "").strip()
    if normalized == "connector.dispatch":
        return "execute"
    if normalized in {"browseract.extract_account_facts", "browseract.extract_account_inventory"}:
        return "observe"
    if normalized == "browseract.build_workflow_spec":
        return "draft"
    if normalized == "provider.gemini_vortex.structured_generate":
        return "draft"
    if normalized == "artifact_repository":
        return "draft"
    return "observe"


class PlannerService:
    def __init__(
        self,
        task_contracts: TaskContractService,
        provider_registry: ProviderRegistryService | None = None,
    ) -> None:
        self._task_contracts = task_contracts
        self._provider_registry = provider_registry or ProviderRegistryService()
        self._workflow_template_builders: dict[
            str, Callable[[IntentSpecV3, TaskContract], tuple[PlanStepSpec, ...]]
        ] = {
            "rewrite": self._build_rewrite_steps,
            "tool_then_artifact": self._build_tool_then_artifact_steps,
            "browseract_extract_then_artifact": self._build_browseract_extract_then_artifact_steps,
            "artifact_then_packs": self._build_artifact_then_packs_steps,
            "artifact_then_dispatch": self._build_artifact_then_dispatch_steps,
            "artifact_then_memory_candidate": self._build_artifact_then_memory_candidate_steps,
            "artifact_then_dispatch_then_memory_candidate": self._build_artifact_then_dispatch_then_memory_candidate_steps,
        }

    def _collect_provider_hints(self, contract: TaskContract) -> tuple[str, ...]:
        raw_hints = contract.runtime_policy().skill_catalog.provider_hints_json
        values: list[str] = []

        def _visit(value: object) -> None:
            if isinstance(value, str):
                normalized = str(value or "").strip()
                if normalized:
                    values.append(normalized)
                return
            if isinstance(value, dict):
                for nested in value.values():
                    _visit(nested)
                return
            if isinstance(value, (list, tuple, set)):
                for nested in value:
                    _visit(nested)

        _visit(raw_hints)
        seen: set[str] = set()
        deduped: list[str] = []
        for value in values:
            key = value.lower()
            if key in seen:
                continue
            seen.add(key)
            deduped.append(value)
        return tuple(deduped)

    def _route_tool_name(self, *, contract: TaskContract, capability_key: str) -> str:
        try:
            route = self._provider_registry.route_tool_by_capability(
                capability_key=capability_key,
                provider_hints=self._collect_provider_hints(contract),
                allowed_tools=contract.allowed_tools,
                require_executable=True,
            )
        except ToolExecutionError as exc:
            raise PlanValidationError(str(exc)) from exc
        return route.tool_name

    def _route_capability(
        self,
        *,
        contract: TaskContract,
        capability_key: str,
    ) -> CapabilityRoute:
        try:
            return self._provider_registry.route_tool_by_capability(
                capability_key=capability_key,
                provider_hints=self._collect_provider_hints(contract),
                allowed_tools=contract.allowed_tools,
                require_executable=True,
            )
        except ToolExecutionError as exc:
            raise PlanValidationError(str(exc)) from exc

    def _require_principal_id(self, principal_id: str) -> str:
        resolved = str(principal_id or "").strip()
        if resolved:
            return resolved
        raise ValueError("principal_id_required")

    def _build_prepare_step(
        self,
        *,
        input_keys: tuple[str, ...] = ("source_text",),
        output_keys: tuple[str, ...] = ("normalized_text", "text_length"),
        desired_output_json: dict[str, object] | None = None,
    ) -> PlanStepSpec:
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
            input_keys=input_keys,
            output_keys=output_keys,
            desired_output_json=dict(desired_output_json or {}),
        )

    def _step_retry_policy(self, contract: TaskContract, *, prefix: str) -> tuple[str, int, int]:
        policy = contract.runtime_policy()
        retry: TaskContractRetryPolicy
        if prefix == "artifact":
            retry = policy.artifact_retry
        elif prefix == "dispatch":
            retry = policy.dispatch_retry
        elif prefix == "browseract":
            retry = policy.browseract_retry
        else:
            retry = TaskContractRetryPolicy()
        return retry.failure_strategy, retry.max_attempts, retry.retry_backoff_seconds

    def _build_policy_step(
        self,
        *,
        depends_on: tuple[str, ...],
        additional_passthrough_keys: tuple[str, ...] = (),
    ) -> PlanStepSpec:
        input_keys = ("normalized_text", "text_length")
        output_keys = ("allow", "requires_approval", "reason", "retention_policy", "memory_write_allowed")
        for value in additional_passthrough_keys:
            key = str(value or "").strip()
            if key and key not in input_keys:
                input_keys += (key,)
            if key and key not in output_keys:
                output_keys += (key,)
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
            input_keys=input_keys,
            output_keys=output_keys,
        )

    def _build_artifact_save_step(
        self,
        intent: IntentSpecV3,
        *,
        contract: TaskContract,
        depends_on: tuple[str, ...],
        approval_required: bool,
        additional_input_keys: tuple[str, ...] = (),
    ) -> PlanStepSpec:
        artifact_tool_name = self._route_tool_name(contract=contract, capability_key="artifact_save")
        failure_strategy, max_attempts, retry_backoff_seconds = self._step_retry_policy(
            contract,
            prefix="artifact",
        )
        input_keys = ("normalized_text",)
        for value in additional_input_keys:
            key = str(value or "").strip()
            if key and key not in input_keys:
                input_keys += (key,)
        output_keys = ("artifact_id", "receipt_id", "cost_id", *self._artifact_evidence_output_keys(contract))
        return PlanStepSpec(
            step_key="step_artifact_save",
            step_kind="tool_call",
            tool_name=artifact_tool_name,
            evidence_required=intent.evidence_requirements,
            approval_required=approval_required,
            reversible=False,
            expected_artifact=intent.deliverable_type,
            fallback="request_human_intervention",
            owner="tool",
            authority_class=_tool_authority_class(artifact_tool_name),
            review_class="none",
            failure_strategy=failure_strategy,
            timeout_budget_seconds=60,
            max_attempts=max_attempts,
            retry_backoff_seconds=retry_backoff_seconds,
            depends_on=depends_on,
            input_keys=input_keys,
            output_keys=output_keys,
        )

    def _build_browseract_extract_step(
        self,
        *,
        contract: TaskContract,
        depends_on: tuple[str, ...],
        tool_name: str,
    ) -> PlanStepSpec:
        failure_strategy, max_attempts, retry_backoff_seconds = self._step_retry_policy(
            contract,
            prefix="browseract",
        )
        timeout_budget_seconds = contract.runtime_policy().browseract_timeout_budget_seconds
        return PlanStepSpec(
            step_key="step_browseract_extract",
            step_kind="tool_call",
            tool_name=tool_name,
            evidence_required=(),
            approval_required=False,
            reversible=False,
            expected_artifact="account_facts",
            fallback="request_human_intervention",
            owner="tool",
            authority_class=_tool_authority_class(tool_name),
            review_class="none",
            failure_strategy=failure_strategy,
            timeout_budget_seconds=timeout_budget_seconds,
            max_attempts=max_attempts,
            retry_backoff_seconds=retry_backoff_seconds,
            depends_on=depends_on,
            input_keys=("binding_id", "service_name", "requested_fields", "instructions", "account_hints_json", "run_url"),
            output_keys=(
                "service_name",
                "facts_json",
                "missing_fields",
                "account_email",
                "plan_tier",
                "discovery_status",
                "verification_source",
                "last_verified_at",
                "normalized_text",
                "preview_text",
                "mime_type",
                "structured_output_json",
            ),
        )

    def _build_browseract_inventory_step(
        self,
        *,
        contract: TaskContract,
        depends_on: tuple[str, ...],
        tool_name: str,
    ) -> PlanStepSpec:
        failure_strategy, max_attempts, retry_backoff_seconds = self._step_retry_policy(
            contract,
            prefix="browseract",
        )
        timeout_budget_seconds = contract.runtime_policy().browseract_timeout_budget_seconds
        return PlanStepSpec(
            step_key="step_browseract_inventory_extract",
            step_kind="tool_call",
            tool_name=tool_name,
            evidence_required=(),
            approval_required=False,
            reversible=False,
            expected_artifact="account_inventory",
            fallback="request_human_intervention",
            owner="tool",
            authority_class=_tool_authority_class(tool_name),
            review_class="none",
            failure_strategy=failure_strategy,
            timeout_budget_seconds=timeout_budget_seconds,
            max_attempts=max_attempts,
            retry_backoff_seconds=retry_backoff_seconds,
            depends_on=depends_on,
            input_keys=("binding_id", "service_names", "requested_fields", "instructions", "account_hints_json", "run_url"),
            output_keys=(
                "service_names",
                "services_json",
                "missing_services",
                "normalized_text",
                "preview_text",
                "mime_type",
                "structured_output_json",
            ),
        )

    def _resolve_pre_artifact_route(
        self,
        contract: TaskContract,
        *,
        default_tool_name: str = "",
        default_capability_key: str = "",
    ) -> CapabilityRoute:
        policy = contract.runtime_policy()
        capability_key = str(policy.pre_artifact_capability_key or default_capability_key or "").strip()
        if capability_key:
            return self._route_capability(contract=contract, capability_key=capability_key)
        tool_name = str(policy.pre_artifact_tool_name or default_tool_name).strip()
        if not tool_name:
            raise PlanValidationError("pre_artifact_tool_name_required")
        allowed_tools = {str(value or "").strip() for value in contract.allowed_tools if str(value or "").strip()}
        if allowed_tools and tool_name not in allowed_tools:
            raise PlanValidationError(f"pre_artifact_tool_not_allowed:{tool_name}")
        try:
            return self._provider_registry.route_tool(tool_name)
        except ToolExecutionError as exc:
            raise PlanValidationError(str(exc)) from exc

    def _build_supported_pre_artifact_tool_step(
        self,
        *,
        contract: TaskContract,
        route: CapabilityRoute,
        depends_on: tuple[str, ...],
    ) -> PlanStepSpec:
        capability = str(route.capability_key or "").strip()
        if capability == "account_facts":
            return self._build_browseract_extract_step(contract=contract, depends_on=depends_on, tool_name=route.tool_name)
        if capability == "account_inventory":
            return self._build_browseract_inventory_step(contract=contract, depends_on=depends_on, tool_name=route.tool_name)
        if capability == "workflow_spec_build":
            return self._build_browseract_workflow_spec_step(contract=contract, depends_on=depends_on, tool_name=route.tool_name)
        if capability == "structured_generate":
            return self._build_structured_generate_step(contract=contract, depends_on=depends_on, tool_name=route.tool_name)
        raise PlanValidationError(f"unsupported_pre_artifact_capability:{capability or '<empty>'}")

    def _additional_artifact_inputs_for_pre_artifact_capability(self, capability_key: str) -> tuple[str, ...]:
        normalized = str(capability_key or "").strip()
        if normalized in {"account_facts", "account_inventory", "workflow_spec_build", "structured_generate"}:
            return ("structured_output_json", "preview_text", "mime_type")
        return ()

    def _build_browseract_workflow_spec_step(
        self,
        *,
        contract: TaskContract,
        depends_on: tuple[str, ...],
        tool_name: str,
    ) -> PlanStepSpec:
        failure_strategy, max_attempts, retry_backoff_seconds = self._step_retry_policy(
            contract,
            prefix="browseract",
        )
        timeout_budget_seconds = contract.runtime_policy().browseract_timeout_budget_seconds
        return PlanStepSpec(
            step_key="step_browseract_workflow_spec_build",
            step_kind="tool_call",
            tool_name=tool_name,
            evidence_required=(),
            approval_required=False,
            reversible=False,
            expected_artifact="browseract_workflow_spec_packet",
            fallback="request_human_intervention",
            owner="tool",
            authority_class=_tool_authority_class(tool_name),
            review_class="none",
            failure_strategy=failure_strategy,
            timeout_budget_seconds=timeout_budget_seconds,
            max_attempts=max_attempts,
            retry_backoff_seconds=retry_backoff_seconds,
            depends_on=depends_on,
            input_keys=(
                "workflow_name",
                "purpose",
                "login_url",
                "tool_url",
            ),
            output_keys=("normalized_text", "structured_output_json", "preview_text", "mime_type"),
        )

    def _build_structured_generate_step(
        self,
        *,
        contract: TaskContract,
        depends_on: tuple[str, ...],
        tool_name: str,
    ) -> PlanStepSpec:
        failure_strategy, max_attempts, retry_backoff_seconds = self._step_retry_policy(
            contract,
            prefix="artifact",
        )
        return PlanStepSpec(
            step_key="step_structured_generate",
            step_kind="tool_call",
            tool_name=tool_name,
            evidence_required=(),
            approval_required=False,
            reversible=False,
            expected_artifact="structured_generation_packet",
            fallback="request_human_intervention",
            owner="tool",
            authority_class=_tool_authority_class(tool_name),
            review_class="none",
            failure_strategy=failure_strategy,
            timeout_budget_seconds=180,
            max_attempts=max_attempts,
            retry_backoff_seconds=retry_backoff_seconds,
            depends_on=depends_on,
            input_keys=("normalized_text",),
            output_keys=("normalized_text", "structured_output_json", "preview_text", "mime_type"),
        )

    def _artifact_output_template_key(self, contract: TaskContract) -> str:
        return contract.runtime_policy().artifact_output.template

    def _prepare_step_artifact_envelope(self, contract: TaskContract) -> tuple[tuple[str, ...], dict[str, object]]:
        template = self._artifact_output_template_key(contract)
        if template != "evidence_pack":
            return ("normalized_text", "text_length"), {}
        artifact_policy = contract.runtime_policy().artifact_output
        return (
            ("normalized_text", "text_length", "structured_output_json", "preview_text", "mime_type"),
            {
                "artifact_output_template": "evidence_pack",
                "default_confidence": artifact_policy.default_confidence,
            },
        )

    def _artifact_envelope_input_keys(self, contract: TaskContract) -> tuple[str, ...]:
        if self._artifact_output_template_key(contract) == "evidence_pack":
            return ("structured_output_json", "preview_text", "mime_type")
        return ()

    def _artifact_evidence_output_keys(self, contract: TaskContract) -> tuple[str, ...]:
        if self._artifact_output_template_key(contract) == "evidence_pack":
            return ("evidence_object_id", "citation_handle")
        return ()

    def _build_pre_artifact_tool_then_artifact_steps(
        self,
        intent: IntentSpecV3,
        *,
        contract: TaskContract,
        default_tool_name: str = "",
        default_capability_key: str = "",
    ) -> tuple[PlanStepSpec, ...]:
        route = self._resolve_pre_artifact_route(
            contract,
            default_tool_name=default_tool_name,
            default_capability_key=default_capability_key,
        )
        tool_step = self._build_supported_pre_artifact_tool_step(
            contract=contract,
            route=route,
            depends_on=("step_input_prepare",),
        )
        prepare_output_keys, prepare_desired_output_json = self._prepare_step_artifact_envelope(contract)
        prepare_step = self._build_prepare_step(
            input_keys=tuple(tool_step.input_keys or ("source_text",)),
            output_keys=prepare_output_keys,
            desired_output_json=prepare_desired_output_json,
        )
        additional_input_keys = self._additional_artifact_inputs_for_pre_artifact_capability(route.capability_key)
        for value in self._artifact_envelope_input_keys(contract):
            if value not in additional_input_keys:
                additional_input_keys += (value,)
        artifact_step = self._build_artifact_save_step(
            intent,
            contract=contract,
            depends_on=(tool_step.step_key,),
            approval_required=False,
            additional_input_keys=additional_input_keys,
        )
        return (prepare_step, tool_step, artifact_step)

    def _build_dispatch_step(
        self,
        *,
        contract: TaskContract,
        depends_on: tuple[str, ...],
    ) -> PlanStepSpec:
        dispatch_tool_name = self._route_tool_name(contract=contract, capability_key="dispatch")
        failure_strategy, max_attempts, retry_backoff_seconds = self._step_retry_policy(
            contract,
            prefix="dispatch",
        )
        return PlanStepSpec(
            step_key="step_connector_dispatch",
            step_kind="tool_call",
            tool_name=dispatch_tool_name,
            evidence_required=(),
            approval_required=True,
            reversible=False,
            expected_artifact="delivery_receipt",
            fallback="request_human_intervention",
            owner="tool",
            authority_class=_tool_authority_class(dispatch_tool_name),
            review_class="none",
            failure_strategy=failure_strategy,
            timeout_budget_seconds=60,
            max_attempts=max_attempts,
            retry_backoff_seconds=retry_backoff_seconds,
            depends_on=depends_on,
            input_keys=("binding_id", "channel", "recipient", "content"),
            output_keys=("delivery_id", "status", "binding_id"),
        )

    def _build_memory_candidate_step(
        self,
        intent: IntentSpecV3,
        *,
        contract: TaskContract,
        depends_on: tuple[str, ...],
        additional_input_keys: tuple[str, ...] = (),
    ) -> PlanStepSpec:
        memory_policy = contract.runtime_policy().memory_candidate
        category = str(memory_policy.category or intent.deliverable_type or "artifact_fact").strip()
        sensitivity = str(memory_policy.sensitivity or "internal").strip() or "internal"
        confidence = memory_policy.confidence
        input_keys = ("artifact_id", "normalized_text", "memory_write_allowed", *additional_input_keys)
        return PlanStepSpec(
            step_key="step_memory_candidate_stage",
            step_kind="memory_write",
            tool_name="",
            evidence_required=intent.evidence_requirements,
            approval_required=False,
            reversible=False,
            expected_artifact="memory_candidate",
            fallback="skip",
            owner="system",
            authority_class="queue",
            review_class="operator",
            failure_strategy="fail",
            timeout_budget_seconds=30,
            max_attempts=1,
            retry_backoff_seconds=0,
            depends_on=depends_on,
            input_keys=input_keys,
            output_keys=("candidate_id", "candidate_status", "candidate_category"),
            desired_output_json={
                "category": category,
                "sensitivity": sensitivity,
                "confidence": confidence,
            },
        )

    def _human_review_metadata(self, contract: TaskContract) -> TaskContractHumanReviewPolicy:
        return contract.runtime_policy().human_review

    def _build_human_review_step(
        self,
        intent: IntentSpecV3,
        *,
        depends_on: tuple[str, ...],
        metadata: TaskContractHumanReviewPolicy,
    ) -> PlanStepSpec | None:
        human_review_role = str(metadata.role or "").strip()
        if not human_review_role:
            return None
        human_review_sla_minutes = int(metadata.sla_minutes)
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
            task_type=str(metadata.task_type or "communications_review"),
            role_required=human_review_role,
            brief=str(metadata.brief or "Review the prepared rewrite before finalizing the artifact."),
            priority=str(metadata.priority or "normal"),
            sla_minutes=human_review_sla_minutes,
            auto_assign_if_unique=bool(metadata.auto_assign_if_unique),
            desired_output_json=dict(metadata.desired_output_json or {}),
            authority_required=str(metadata.authority_required or ""),
            why_human=str(metadata.why_human or ""),
            quality_rubric_json=dict(metadata.quality_rubric_json or {}),
        )

    def _resolve_post_artifact_packs(
        self,
        contract: TaskContract,
        *,
        fallback: tuple[str, ...] = (),
    ) -> tuple[str, ...]:
        values = [
            str(value or "").strip().lower()
            for value in contract.runtime_policy().post_artifact_packs
            if str(value or "").strip()
        ]
        if not values:
            values = [str(value or "").strip().lower() for value in fallback if str(value or "").strip()]
        resolved: list[str] = []
        for value in values:
            if value not in {"dispatch", "memory_candidate"}:
                raise PlanValidationError(f"unknown_post_artifact_pack:{value}")
            if value not in resolved:
                resolved.append(value)
        if not resolved:
            raise PlanValidationError("post_artifact_pack_required")
        return tuple(resolved)

    def _build_rewrite_steps(self, intent: IntentSpecV3, *, contract: TaskContract) -> tuple[PlanStepSpec, ...]:
        approval_required = intent.approval_class not in {"", "none"}
        human_review_metadata = self._human_review_metadata(contract)
        prepare_output_keys, prepare_desired_output_json = self._prepare_step_artifact_envelope(contract)
        prepare_step = self._build_prepare_step(
            output_keys=prepare_output_keys,
            desired_output_json=prepare_desired_output_json,
        )
        policy_step = self._build_policy_step(
            depends_on=("step_input_prepare",),
            additional_passthrough_keys=self._artifact_envelope_input_keys(contract),
        )
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
                contract=contract,
                depends_on=save_depends_on,
                approval_required=approval_required,
                additional_input_keys=self._artifact_envelope_input_keys(contract),
            )
        )
        return tuple(steps)

    def _build_browseract_extract_then_artifact_steps(
        self,
        intent: IntentSpecV3,
        *,
        contract: TaskContract,
    ) -> tuple[PlanStepSpec, ...]:
        return self._build_pre_artifact_tool_then_artifact_steps(
            intent,
            contract=contract,
            default_capability_key="account_facts",
        )

    def _build_tool_then_artifact_steps(
        self,
        intent: IntentSpecV3,
        *,
        contract: TaskContract,
    ) -> tuple[PlanStepSpec, ...]:
        return self._build_pre_artifact_tool_then_artifact_steps(
            intent,
            contract=contract,
        )

    def _build_artifact_then_packs_steps(
        self,
        intent: IntentSpecV3,
        *,
        contract: TaskContract,
        pack_keys: tuple[str, ...] | None = None,
    ) -> tuple[PlanStepSpec, ...]:
        packs = pack_keys or self._resolve_post_artifact_packs(contract)
        if "dispatch" not in packs and "memory_candidate" in packs:
            return self._build_artifact_then_memory_candidate_steps(
                intent,
                contract=contract,
                pack_keys=packs,
            )

        human_review_metadata = self._human_review_metadata(contract)
        prepare_output_keys, prepare_desired_output_json = self._prepare_step_artifact_envelope(contract)
        prepare_step = self._build_prepare_step(
            output_keys=prepare_output_keys,
            desired_output_json=prepare_desired_output_json,
        )
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
                contract=contract,
                depends_on=artifact_depends_on,
                approval_required=False,
                additional_input_keys=self._artifact_envelope_input_keys(contract),
            )
        )
        policy_depends_on = ("step_artifact_save",)
        steps.append(self._build_policy_step(depends_on=policy_depends_on))
        if "dispatch" in packs:
            steps.append(self._build_dispatch_step(contract=contract, depends_on=("step_policy_evaluate",)))
        if "memory_candidate" in packs:
            memory_depends_on = ["step_artifact_save", "step_policy_evaluate"]
            additional_input_keys: tuple[str, ...] = self._artifact_evidence_output_keys(contract)
            if "dispatch" in packs:
                memory_depends_on.append("step_connector_dispatch")
                additional_input_keys = (
                    "delivery_id",
                    "status",
                    "binding_id",
                    "channel",
                    "recipient",
                    *self._artifact_evidence_output_keys(contract),
                )
            steps.append(
                self._build_memory_candidate_step(
                    intent,
                    contract=contract,
                    depends_on=tuple(memory_depends_on),
                    additional_input_keys=additional_input_keys,
                )
            )
        return tuple(steps)

    def _build_artifact_then_dispatch_steps(
        self,
        intent: IntentSpecV3,
        *,
        contract: TaskContract,
    ) -> tuple[PlanStepSpec, ...]:
        return self._build_artifact_then_packs_steps(intent, contract=contract, pack_keys=("dispatch",))

    def _build_artifact_then_memory_candidate_steps(
        self,
        intent: IntentSpecV3,
        *,
        contract: TaskContract,
        pack_keys: tuple[str, ...] | None = None,
    ) -> tuple[PlanStepSpec, ...]:
        prepare_output_keys, prepare_desired_output_json = self._prepare_step_artifact_envelope(contract)
        prepare_step = self._build_prepare_step(
            output_keys=prepare_output_keys,
            desired_output_json=prepare_desired_output_json,
        )
        policy_step = self._build_policy_step(
            depends_on=("step_input_prepare",),
            additional_passthrough_keys=self._artifact_envelope_input_keys(contract),
        )
        artifact_step = self._build_artifact_save_step(
            intent,
            contract=contract,
            depends_on=("step_policy_evaluate",),
            approval_required=False,
            additional_input_keys=self._artifact_envelope_input_keys(contract),
        )
        packs = pack_keys or self._resolve_post_artifact_packs(contract, fallback=("memory_candidate",))
        steps: list[PlanStepSpec] = [prepare_step, policy_step, artifact_step]
        memory_depends_on = ["step_artifact_save", "step_policy_evaluate"]
        additional_input_keys: tuple[str, ...] = self._artifact_evidence_output_keys(contract)
        if "dispatch" in packs:
            steps.append(self._build_dispatch_step(contract=contract, depends_on=("step_policy_evaluate",)))
            memory_depends_on.append("step_connector_dispatch")
            additional_input_keys = (
                "delivery_id",
                "status",
                "binding_id",
                "channel",
                "recipient",
                *self._artifact_evidence_output_keys(contract),
            )
        steps.append(
            self._build_memory_candidate_step(
                intent,
                contract=contract,
                depends_on=tuple(memory_depends_on),
                additional_input_keys=additional_input_keys,
            )
        )
        return tuple(steps)

    def _build_artifact_then_dispatch_then_memory_candidate_steps(
        self,
        intent: IntentSpecV3,
        *,
        contract: TaskContract,
    ) -> tuple[PlanStepSpec, ...]:
        return self._build_artifact_then_packs_steps(
            intent,
            contract=contract,
            pack_keys=("dispatch", "memory_candidate"),
        )

    def _workflow_template_key(self, contract: TaskContract) -> str:
        return contract.runtime_policy().workflow_template_key

    def _steps_for_contract(self, intent: IntentSpecV3, contract: TaskContract) -> tuple[PlanStepSpec, ...]:
        workflow_template = self._workflow_template_key(contract)
        builder = self._workflow_template_builders.get(workflow_template)
        if builder is None:
            raise PlanValidationError(f"unknown_workflow_template:{workflow_template}")
        return builder(intent, contract=contract)

    def compile_intent(
        self,
        *,
        task_key: str,
        principal_id: str,
        goal: str,
    ) -> IntentSpecV3:
        contract = self._task_contracts.get_contract_or_raise(task_key)
        budget_class = str(contract.runtime_policy().budget_class or "low")
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
        contract = self._task_contracts.get_contract_or_raise(task_key)
        intent = self.compile_intent(task_key=task_key, principal_id=principal_id, goal=goal)
        steps = self._steps_for_contract(intent, contract)
        plan = PlanSpec(
            plan_id=str(uuid.uuid4()),
            task_key=intent.task_type,
            principal_id=intent.principal_id,
            created_at=now_utc_iso(),
            steps=steps,
        )
        validate_plan_spec(plan)
        return intent, plan
