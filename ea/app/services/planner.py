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
from app.services.browseract_ui_service_catalog import (
    BrowserActUiServiceDefinition,
    browseract_ui_service_by_capability,
    browseract_ui_service_by_tool,
)
from app.services.brain_router import BrainRouterService
from app.services.provider_registry import CapabilityRoute, ProviderRegistryService
from app.services.task_contracts import TaskContractService
from app.services.tool_execution_common import ToolExecutionError


def _tool_authority_class(tool_name: str) -> str:
    normalized = str(tool_name or "").strip()
    if normalized == "connector.dispatch":
        return "execute"
    if normalized == "browseract.crezlo_property_tour":
        return "execute"
    if browseract_ui_service_by_tool(normalized) is not None:
        return "execute"
    if normalized in {"browseract.extract_account_facts", "browseract.extract_account_inventory"}:
        return "observe"
    if normalized == "browseract.build_workflow_spec":
        return "draft"
    if normalized == "provider.gemini_vortex.structured_generate":
        return "draft"
    if normalized == "provider.magixai.structured_generate":
        return "draft"
    if normalized == "provider.onemin.code_generate":
        return "draft"
    if normalized in {"provider.onemin.image_generate", "provider.onemin.media_transform"}:
        return "draft"
    if normalized == "provider.brain_router.structured_generate":
        return "draft"
    if normalized == "provider.brain_router.reasoned_patch_review":
        return "observe"
    if normalized == "artifact_repository":
        return "draft"
    return "observe"


class PlannerService:
    def __init__(
        self,
        task_contracts: TaskContractService,
        provider_registry: ProviderRegistryService | None = None,
        brain_router: BrainRouterService | None = None,
    ) -> None:
        self._task_contracts = task_contracts
        self._provider_registry = provider_registry or ProviderRegistryService()
        self._brain_router = brain_router or BrainRouterService(provider_registry=self._provider_registry)
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
        return self._brain_router.provider_hints_for_contract(contract)

    def _step_brain_metadata(
        self,
        *,
        contract: TaskContract,
        route: CapabilityRoute | None = None,
        principal_id: str = "",
        profile_name: str = "",
    ) -> dict[str, object]:
        normalized_profile_name = str(profile_name or "").strip()
        posthoc_review_profile = ""
        fallback_brain_profile = ""
        if normalized_profile_name:
            decision = self._brain_router.resolve_profile(normalized_profile_name, principal_id=principal_id or None)
        elif route is not None and str(route.capability_key or "").strip():
            try:
                brain_route = self._brain_router.route_brain_capability_for_contract(
                    contract=contract,
                    capability_key=route.capability_key,
                    principal_id=principal_id or None,
                )
            except ToolExecutionError:
                decision = self._brain_router.contract_brain_decision(contract, principal_id=principal_id or None)
            else:
                decision = brain_route.decision
                posthoc_review_profile = brain_route.posthoc_review_profile
                fallback_brain_profile = brain_route.fallback_brain_profile
        else:
            decision = self._brain_router.contract_brain_decision(contract, principal_id=principal_id or None)
        if not normalized_profile_name and not posthoc_review_profile:
            posthoc_review_profile = self._brain_router.posthoc_review_profile_for_contract(contract)
        if not normalized_profile_name and not fallback_brain_profile:
            fallback_brain_profile = self._brain_router.fallback_brain_profile_for_contract(contract)
        metadata: dict[str, object] = {
            "brain_profile": decision.profile,
            "posthoc_review_profile": "" if normalized_profile_name else posthoc_review_profile,
            "fallback_brain_profile": "" if normalized_profile_name else fallback_brain_profile,
            "provider_hint_order": tuple(decision.provider_hint_order or ()),
            "routed_public_model": decision.public_model,
        }
        if route is not None:
            metadata["routed_provider_key"] = route.provider_key
            metadata["routed_capability_key"] = route.capability_key
        return metadata

    def _route_tool_name(self, *, contract: TaskContract, capability_key: str, principal_id: str = "") -> str:
        try:
            route = self._brain_router.route_capability_for_contract(
                contract=contract,
                capability_key=capability_key,
                principal_id=principal_id or None,
            )
        except ToolExecutionError as exc:
            raise PlanValidationError(str(exc)) from exc
        return route.tool_name

    def _route_capability(
        self,
        *,
        contract: TaskContract,
        capability_key: str,
        principal_id: str = "",
    ) -> CapabilityRoute:
        try:
            return self._brain_router.route_capability_for_contract(
                contract=contract,
                capability_key=capability_key,
                principal_id=principal_id or None,
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

    def _contract_allows_capability(self, contract: TaskContract, capability_key: str) -> bool:
        allowed_tools = {str(value or "").strip() for value in contract.allowed_tools if str(value or "").strip()}
        if not allowed_tools:
            return True
        normalized_capability = str(capability_key or "").strip().lower()
        for binding in self._provider_registry.list_bindings():
            for capability in binding.capabilities:
                if str(capability.capability_key or "").strip().lower() != normalized_capability:
                    continue
                if str(capability.tool_name or "").strip() in allowed_tools:
                    return True
        return False

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
        principal_id: str,
        depends_on: tuple[str, ...],
        approval_required: bool,
        additional_input_keys: tuple[str, ...] = (),
    ) -> PlanStepSpec:
        artifact_tool_name = self._route_tool_name(contract=contract, capability_key="artifact_save", principal_id=principal_id)
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
            desired_output_json=self._artifact_desired_output_json(contract=contract, deliverable_type=intent.deliverable_type),
            **self._step_brain_metadata(contract=contract, principal_id=principal_id),
        )

    def _structured_generate_desired_output_json(self, contract: TaskContract) -> dict[str, object]:
        runtime_policy = contract.runtime_policy()
        template = str(runtime_policy.artifact_output.template or "").strip().lower()
        profile = str(runtime_policy.brain_profile or "").strip().lower()
        if template == "groundwork_brief" or profile == "groundwork":
            return {
                "format": "groundwork_brief",
                "required_structured_keys": [
                    "plan",
                    "risks",
                    "missing_evidence",
                    "recommended_next_lane",
                    "acceptance_checklist",
                ],
            }
        return {}

    def _review_desired_output_json(self, *, profile_name: str) -> dict[str, object]:
        return {
            "format": "review_packet",
            "review_profile": str(profile_name or "review_light").strip() or "review_light",
            "required_structured_keys": [
                "recommendation",
                "risks",
                "disagreements",
                "roles",
                "audit_scope",
            ],
        }

    def _artifact_desired_output_json(self, *, contract: TaskContract, deliverable_type: str) -> dict[str, object]:
        template = self._artifact_output_template_key(contract)
        if template == "groundwork_brief":
            return {"format": "groundwork_brief"}
        if str(deliverable_type or "").strip() == "review_packet":
            return {"format": "review_packet"}
        return {}

    def _build_browseract_extract_step(
        self,
        *,
        contract: TaskContract,
        principal_id: str,
        depends_on: tuple[str, ...],
        tool_name: str,
        route: CapabilityRoute | None = None,
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
            **self._step_brain_metadata(contract=contract, route=route, principal_id=principal_id),
        )

    def _build_browseract_inventory_step(
        self,
        *,
        contract: TaskContract,
        principal_id: str,
        depends_on: tuple[str, ...],
        tool_name: str,
        route: CapabilityRoute | None = None,
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
            **self._step_brain_metadata(contract=contract, route=route, principal_id=principal_id),
        )

    def _resolve_pre_artifact_route(
        self,
        contract: TaskContract,
        *,
        principal_id: str,
        default_tool_name: str = "",
        default_capability_key: str = "",
    ) -> CapabilityRoute:
        policy = contract.runtime_policy()
        capability_key = str(policy.pre_artifact_capability_key or default_capability_key or "").strip()
        tool_name = str(policy.pre_artifact_tool_name or default_tool_name).strip()
        allowed_tools = {str(value or "").strip() for value in contract.allowed_tools if str(value or "").strip()}
        logical_route = self._logical_pre_artifact_route_for_capability(capability_key)
        if logical_route is not None and not tool_name:
            return logical_route
        if capability_key:
            try:
                return self._route_capability(contract=contract, capability_key=capability_key, principal_id=principal_id)
            except PlanValidationError:
                if logical_route is not None:
                    return logical_route
                if not tool_name:
                    raise
                if allowed_tools and tool_name not in allowed_tools:
                    raise
                try:
                    return self._provider_registry.route_tool_with_context(
                        tool_name,
                        principal_id=principal_id,
                    )
                except ToolExecutionError as exc:
                    raise PlanValidationError(str(exc)) from exc
        if not tool_name:
            raise PlanValidationError("pre_artifact_tool_name_required")
        if allowed_tools and tool_name not in allowed_tools:
            raise PlanValidationError(f"pre_artifact_tool_not_allowed:{tool_name}")
        try:
            return self._provider_registry.route_tool_with_context(
                tool_name,
                principal_id=principal_id,
            )
        except ToolExecutionError as exc:
            raise PlanValidationError(str(exc)) from exc

    def _logical_pre_artifact_route_for_capability(self, capability_key: str) -> CapabilityRoute | None:
        normalized = str(capability_key or "").strip().lower()
        if normalized == "structured_generate":
            return CapabilityRoute(
                provider_key="brain_router",
                capability_key="structured_generate",
                tool_name="provider.brain_router.structured_generate",
                executable=True,
            )
        if normalized == "reasoned_patch_review":
            return CapabilityRoute(
                provider_key="brain_router",
                capability_key="reasoned_patch_review",
                tool_name="provider.brain_router.reasoned_patch_review",
                executable=True,
            )
        return None

    def _build_supported_pre_artifact_tool_step(
        self,
        *,
        contract: TaskContract,
        principal_id: str,
        route: CapabilityRoute,
        depends_on: tuple[str, ...],
    ) -> PlanStepSpec:
        capability = str(route.capability_key or "").strip()
        if capability == "account_facts":
            return self._build_browseract_extract_step(contract=contract, principal_id=principal_id, depends_on=depends_on, tool_name=route.tool_name, route=route)
        if capability == "account_inventory":
            return self._build_browseract_inventory_step(contract=contract, principal_id=principal_id, depends_on=depends_on, tool_name=route.tool_name, route=route)
        if capability == "workflow_spec_build":
            return self._build_browseract_workflow_spec_step(contract=contract, principal_id=principal_id, depends_on=depends_on, tool_name=route.tool_name, route=route)
        if capability == "workflow_spec_repair":
            return self._build_browseract_workflow_repair_step(contract=contract, principal_id=principal_id, depends_on=depends_on, tool_name=route.tool_name, route=route)
        if capability == "crezlo_property_tour":
            return self._build_browseract_crezlo_property_tour_step(
                contract=contract,
                principal_id=principal_id,
                depends_on=depends_on,
                tool_name=route.tool_name,
                route=route,
            )
        ui_service = browseract_ui_service_by_capability(capability)
        if ui_service is not None:
            return self._build_browseract_ui_service_step(
                contract=contract,
                principal_id=principal_id,
                depends_on=depends_on,
                tool_name=route.tool_name,
                service=ui_service,
                route=route,
            )
        if capability == "structured_generate":
            return self._build_structured_generate_step(
                contract=contract,
                principal_id=principal_id,
                depends_on=depends_on,
                tool_name=route.tool_name,
                route=route,
            )
        if capability == "code_generate":
            return self._build_code_generate_step(
                contract=contract,
                principal_id=principal_id,
                depends_on=depends_on,
                tool_name=route.tool_name,
                route=route,
            )
        if capability == "image_generate":
            return self._build_image_generate_step(
                contract=contract,
                principal_id=principal_id,
                depends_on=depends_on,
                tool_name=route.tool_name,
                route=route,
            )
        if capability == "media_transform":
            return self._build_media_transform_step(
                contract=contract,
                principal_id=principal_id,
                depends_on=depends_on,
                tool_name=route.tool_name,
                route=route,
            )
        if capability == "reasoned_patch_review":
            return self._build_reasoned_patch_review_step(
                contract=contract,
                principal_id=principal_id,
                depends_on=depends_on,
                tool_name=route.tool_name,
                route=route,
                profile_name=self._brain_router.contract_brain_decision(contract, principal_id=principal_id or None).profile,
            )
        raise PlanValidationError(f"unsupported_pre_artifact_capability:{capability or '<empty>'}")

    def _additional_artifact_inputs_for_pre_artifact_capability(self, capability_key: str) -> tuple[str, ...]:
        normalized = str(capability_key or "").strip()
        if browseract_ui_service_by_capability(normalized) is not None:
            return ("structured_output_json", "preview_text", "mime_type")
        if normalized in {
            "account_facts",
            "account_inventory",
            "workflow_spec_build",
            "workflow_spec_repair",
            "crezlo_property_tour",
            "code_generate",
            "image_generate",
            "media_transform",
            "structured_generate",
            "reasoned_patch_review",
        }:
            return ("structured_output_json", "preview_text", "mime_type")
        return ()

    def _build_browseract_crezlo_property_tour_step(
        self,
        *,
        contract: TaskContract,
        principal_id: str,
        depends_on: tuple[str, ...],
        tool_name: str,
        route: CapabilityRoute | None = None,
    ) -> PlanStepSpec:
        failure_strategy, max_attempts, retry_backoff_seconds = self._step_retry_policy(
            contract,
            prefix="browseract",
        )
        timeout_budget_seconds = contract.runtime_policy().browseract_timeout_budget_seconds
        return PlanStepSpec(
            step_key="step_browseract_crezlo_property_tour",
            step_kind="tool_call",
            tool_name=tool_name,
            evidence_required=(),
            approval_required=False,
            reversible=False,
            expected_artifact="property_tour_packet",
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
                "binding_id",
                "tour_title",
                "property_url",
            ),
            output_keys=(
                "tour_title",
                "tour_status",
                "tour_id",
                "slug",
                "share_url",
                "editor_url",
                "public_url",
                "workspace_id",
                "workspace_domain",
                "creation_mode",
                "scene_count",
                "workflow_id",
                "task_id",
                "requested_url",
                "normalized_text",
                "preview_text",
                "mime_type",
                "structured_output_json",
            ),
            **self._step_brain_metadata(contract=contract, route=route, principal_id=principal_id),
        )

    def _build_browseract_ui_service_step(
        self,
        *,
        contract: TaskContract,
        principal_id: str,
        depends_on: tuple[str, ...],
        tool_name: str,
        service: BrowserActUiServiceDefinition,
        route: CapabilityRoute | None = None,
    ) -> PlanStepSpec:
        failure_strategy, max_attempts, retry_backoff_seconds = self._step_retry_policy(
            contract,
            prefix="browseract",
        )
        timeout_budget_seconds = contract.runtime_policy().browseract_timeout_budget_seconds
        input_keys = ("binding_id", *service.required_top_level_inputs)
        output_keys = list(service.output_schema_json().get("properties", {}).keys())
        for key in ("normalized_text", "preview_text", "mime_type"):
            if key not in output_keys:
                output_keys.append(key)
        return PlanStepSpec(
            step_key=f"step_browseract_{service.service_key}",
            step_kind="tool_call",
            tool_name=tool_name,
            evidence_required=(),
            approval_required=False,
            reversible=False,
            expected_artifact=service.deliverable_type,
            fallback="request_human_intervention",
            owner="tool",
            authority_class=_tool_authority_class(tool_name),
            review_class="none",
            failure_strategy=failure_strategy,
            timeout_budget_seconds=timeout_budget_seconds,
            max_attempts=max_attempts,
            retry_backoff_seconds=retry_backoff_seconds,
            depends_on=depends_on,
            input_keys=input_keys,
            output_keys=tuple(output_keys),
            **self._step_brain_metadata(contract=contract, route=route, principal_id=principal_id),
        )

    def _build_browseract_workflow_spec_step(
        self,
        *,
        contract: TaskContract,
        principal_id: str,
        depends_on: tuple[str, ...],
        tool_name: str,
        route: CapabilityRoute | None = None,
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
            **self._step_brain_metadata(contract=contract, route=route, principal_id=principal_id),
        )

    def _build_browseract_workflow_repair_step(
        self,
        *,
        contract: TaskContract,
        principal_id: str,
        depends_on: tuple[str, ...],
        tool_name: str,
        route: CapabilityRoute | None = None,
    ) -> PlanStepSpec:
        failure_strategy, max_attempts, retry_backoff_seconds = self._step_retry_policy(
            contract,
            prefix="browseract",
        )
        timeout_budget_seconds = contract.runtime_policy().browseract_timeout_budget_seconds
        return PlanStepSpec(
            step_key="step_browseract_workflow_spec_repair",
            step_kind="tool_call",
            tool_name=tool_name,
            evidence_required=(),
            approval_required=False,
            reversible=False,
            expected_artifact="browseract_workflow_repair_packet",
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
                "tool_url",
                "failure_summary",
            ),
            output_keys=("normalized_text", "structured_output_json", "preview_text", "mime_type"),
            **self._step_brain_metadata(contract=contract, route=route, principal_id=principal_id),
        )

    def _build_structured_generate_step(
        self,
        *,
        contract: TaskContract,
        principal_id: str,
        depends_on: tuple[str, ...],
        tool_name: str,
        route: CapabilityRoute | None = None,
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
            desired_output_json=self._structured_generate_desired_output_json(contract),
            **self._step_brain_metadata(contract=contract, route=route, principal_id=principal_id),
        )

    def _build_code_generate_step(
        self,
        *,
        contract: TaskContract,
        principal_id: str,
        depends_on: tuple[str, ...],
        tool_name: str,
        route: CapabilityRoute | None = None,
    ) -> PlanStepSpec:
        failure_strategy, max_attempts, retry_backoff_seconds = self._step_retry_policy(
            contract,
            prefix="artifact",
        )
        return PlanStepSpec(
            step_key="step_code_generate",
            step_kind="tool_call",
            tool_name=tool_name,
            evidence_required=(),
            approval_required=False,
            reversible=False,
            expected_artifact="code_generation_packet",
            fallback="request_human_intervention",
            owner="tool",
            authority_class=_tool_authority_class(tool_name),
            review_class="none",
            failure_strategy=failure_strategy,
            timeout_budget_seconds=180,
            max_attempts=max_attempts,
            retry_backoff_seconds=retry_backoff_seconds,
            depends_on=depends_on,
            input_keys=("source_text",),
            output_keys=("normalized_text", "structured_output_json", "preview_text", "mime_type"),
            **self._step_brain_metadata(contract=contract, route=route, principal_id=principal_id),
        )

    def _build_image_generate_step(
        self,
        *,
        contract: TaskContract,
        principal_id: str,
        depends_on: tuple[str, ...],
        tool_name: str,
        route: CapabilityRoute | None = None,
    ) -> PlanStepSpec:
        failure_strategy, max_attempts, retry_backoff_seconds = self._step_retry_policy(
            contract,
            prefix="artifact",
        )
        return PlanStepSpec(
            step_key="step_image_generate",
            step_kind="tool_call",
            tool_name=tool_name,
            evidence_required=(),
            approval_required=False,
            reversible=False,
            expected_artifact="image_generation_packet",
            fallback="request_human_intervention",
            owner="tool",
            authority_class=_tool_authority_class(tool_name),
            review_class="none",
            failure_strategy=failure_strategy,
            timeout_budget_seconds=180,
            max_attempts=max_attempts,
            retry_backoff_seconds=retry_backoff_seconds,
            depends_on=depends_on,
            input_keys=("source_text",),
            output_keys=("normalized_text", "structured_output_json", "preview_text", "mime_type", "asset_urls"),
            **self._step_brain_metadata(contract=contract, route=route, principal_id=principal_id),
        )

    def _build_media_transform_step(
        self,
        *,
        contract: TaskContract,
        principal_id: str,
        depends_on: tuple[str, ...],
        tool_name: str,
        route: CapabilityRoute | None = None,
    ) -> PlanStepSpec:
        failure_strategy, max_attempts, retry_backoff_seconds = self._step_retry_policy(
            contract,
            prefix="artifact",
        )
        return PlanStepSpec(
            step_key="step_media_transform",
            step_kind="tool_call",
            tool_name=tool_name,
            evidence_required=(),
            approval_required=False,
            reversible=False,
            expected_artifact="media_transform_packet",
            fallback="request_human_intervention",
            owner="tool",
            authority_class=_tool_authority_class(tool_name),
            review_class="none",
            failure_strategy=failure_strategy,
            timeout_budget_seconds=180,
            max_attempts=max_attempts,
            retry_backoff_seconds=retry_backoff_seconds,
            depends_on=depends_on,
            input_keys=("feature_type",),
            output_keys=("normalized_text", "structured_output_json", "preview_text", "mime_type", "asset_urls"),
            **self._step_brain_metadata(contract=contract, route=route, principal_id=principal_id),
        )

    def _build_reasoned_patch_review_step(
        self,
        *,
        contract: TaskContract,
        principal_id: str,
        depends_on: tuple[str, ...],
        tool_name: str,
        route: CapabilityRoute | None = None,
        profile_name: str = "",
    ) -> PlanStepSpec:
        effective_profile = str(profile_name or "").strip()
        browseract_review = effective_profile in {"review_light", "audit"} or (
            route is not None and route.provider_key == "browseract"
        )
        retry_prefix = "browseract" if browseract_review else "artifact"
        failure_strategy, max_attempts, retry_backoff_seconds = self._step_retry_policy(
            contract,
            prefix=retry_prefix,
        )
        timeout_budget_seconds = (
            contract.runtime_policy().browseract_timeout_budget_seconds
            if browseract_review
            else 180
        )
        return PlanStepSpec(
            step_key="step_reasoned_patch_review",
            step_kind="tool_call",
            tool_name=tool_name,
            evidence_required=(),
            approval_required=False,
            reversible=False,
            expected_artifact="review_packet",
            fallback="request_human_intervention",
            owner="tool",
            authority_class=_tool_authority_class(tool_name),
            review_class="none",
            failure_strategy=failure_strategy,
            timeout_budget_seconds=timeout_budget_seconds,
            max_attempts=max_attempts,
            retry_backoff_seconds=retry_backoff_seconds,
            depends_on=depends_on,
            input_keys=("normalized_text", "source_text", "diff_text"),
            output_keys=("normalized_text", "structured_output_json", "preview_text", "mime_type"),
            desired_output_json=self._review_desired_output_json(profile_name=effective_profile),
            **self._step_brain_metadata(
                contract=contract,
                route=route,
                principal_id=principal_id,
                profile_name=profile_name,
            ),
        )

    def _posthoc_review_step(
        self,
        *,
        contract: TaskContract,
        principal_id: str,
        depends_on: tuple[str, ...],
    ) -> PlanStepSpec | None:
        review_profile = self._brain_router.posthoc_review_profile_for_contract(contract)
        if not review_profile:
            return None
        review_required = bool(contract.runtime_policy().posthoc_review_required)
        if not self._contract_allows_capability(contract, "reasoned_patch_review"):
            return None
        try:
            _ = self._provider_registry.route_brain_profile_capability_with_context(
                profile_name=review_profile,
                capability_key="reasoned_patch_review",
                principal_id=principal_id,
                allowed_tools=tuple(contract.allowed_tools or ()),
                require_executable=True,
            )
        except ToolExecutionError as exc:
            if review_required:
                raise PlanValidationError(str(exc)) from exc
            return None
        return self._build_reasoned_patch_review_step(
            contract=contract,
            principal_id=principal_id,
            depends_on=depends_on,
            tool_name="provider.brain_router.reasoned_patch_review",
            profile_name=review_profile,
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

    def _prepare_input_keys_for_pre_artifact_capability(
        self,
        capability_key: str,
        *,
        default_input_keys: tuple[str, ...],
    ) -> tuple[str, ...]:
        normalized = str(capability_key or "").strip()
        if normalized == "structured_generate":
            return ("normalized_text",)
        if normalized == "code_generate":
            return ("source_text",)
        if normalized == "image_generate":
            return ("source_text",)
        if normalized == "media_transform":
            return ("feature_type",)
        return default_input_keys

    def _build_pre_artifact_tool_then_artifact_steps(
        self,
        intent: IntentSpecV3,
        *,
        contract: TaskContract,
        principal_id: str,
        default_tool_name: str = "",
        default_capability_key: str = "",
    ) -> tuple[PlanStepSpec, ...]:
        route = self._resolve_pre_artifact_route(
            contract,
            principal_id=principal_id,
            default_tool_name=default_tool_name,
            default_capability_key=default_capability_key,
        )
        tool_step = self._build_supported_pre_artifact_tool_step(
            contract=contract,
            principal_id=principal_id,
            route=route,
            depends_on=("step_input_prepare",),
        )
        prepare_input_keys = self._prepare_input_keys_for_pre_artifact_capability(
            route.capability_key,
            default_input_keys=tuple(tool_step.input_keys or ("source_text",)),
        )
        prepare_output_keys, prepare_desired_output_json = self._prepare_step_artifact_envelope(contract)
        prepare_step = self._build_prepare_step(
            input_keys=prepare_input_keys,
            output_keys=prepare_output_keys,
            desired_output_json=prepare_desired_output_json,
        )
        posthoc_review_step = None
        artifact_depends_on = (tool_step.step_key,)
        if str(route.capability_key or "").strip() == "structured_generate":
            posthoc_review_step = self._posthoc_review_step(
                contract=contract,
                principal_id=principal_id,
                depends_on=(prepare_step.step_key, tool_step.step_key),
            )
            if posthoc_review_step is not None:
                artifact_depends_on = (posthoc_review_step.step_key, tool_step.step_key)
        additional_input_keys = self._additional_artifact_inputs_for_pre_artifact_capability(route.capability_key)
        for value in self._artifact_envelope_input_keys(contract):
            if value not in additional_input_keys:
                additional_input_keys += (value,)
        artifact_step = self._build_artifact_save_step(
            intent,
            contract=contract,
            principal_id=principal_id,
            depends_on=artifact_depends_on,
            approval_required=False,
            additional_input_keys=additional_input_keys,
        )
        steps: list[PlanStepSpec] = [prepare_step, tool_step]
        if posthoc_review_step is not None:
            steps.append(posthoc_review_step)
        steps.append(artifact_step)
        return tuple(steps)

    def _build_dispatch_step(
        self,
        *,
        contract: TaskContract,
        principal_id: str,
        depends_on: tuple[str, ...],
    ) -> PlanStepSpec:
        dispatch_tool_name = self._route_tool_name(contract=contract, capability_key="dispatch", principal_id=principal_id)
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
            **self._step_brain_metadata(contract=contract, principal_id=principal_id),
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

    def _build_rewrite_steps(self, intent: IntentSpecV3, *, contract: TaskContract, principal_id: str) -> tuple[PlanStepSpec, ...]:
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
                principal_id=principal_id,
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
        principal_id: str,
    ) -> tuple[PlanStepSpec, ...]:
        return self._build_pre_artifact_tool_then_artifact_steps(
            intent,
            contract=contract,
            principal_id=principal_id,
            default_tool_name="browseract.extract_account_facts",
            default_capability_key="account_facts",
        )

    def _build_tool_then_artifact_steps(
        self,
        intent: IntentSpecV3,
        *,
        contract: TaskContract,
        principal_id: str,
    ) -> tuple[PlanStepSpec, ...]:
        return self._build_pre_artifact_tool_then_artifact_steps(
            intent,
            contract=contract,
            principal_id=principal_id,
        )

    def _build_artifact_then_packs_steps(
        self,
        intent: IntentSpecV3,
        *,
        contract: TaskContract,
        principal_id: str,
        pack_keys: tuple[str, ...] | None = None,
    ) -> tuple[PlanStepSpec, ...]:
        packs = pack_keys or self._resolve_post_artifact_packs(contract)
        if "dispatch" not in packs and "memory_candidate" in packs:
            return self._build_artifact_then_memory_candidate_steps(
                intent,
                contract=contract,
                principal_id=principal_id,
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
                principal_id=principal_id,
                depends_on=artifact_depends_on,
                approval_required=False,
                additional_input_keys=self._artifact_envelope_input_keys(contract),
            )
        )
        policy_depends_on = ("step_artifact_save",)
        steps.append(self._build_policy_step(depends_on=policy_depends_on))
        if "dispatch" in packs:
            steps.append(self._build_dispatch_step(contract=contract, principal_id=principal_id, depends_on=("step_policy_evaluate",)))
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
        principal_id: str,
    ) -> tuple[PlanStepSpec, ...]:
        return self._build_artifact_then_packs_steps(intent, contract=contract, principal_id=principal_id, pack_keys=("dispatch",))

    def _build_artifact_then_memory_candidate_steps(
        self,
        intent: IntentSpecV3,
        *,
        contract: TaskContract,
        principal_id: str,
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
            principal_id=principal_id,
            depends_on=("step_policy_evaluate",),
            approval_required=False,
            additional_input_keys=self._artifact_envelope_input_keys(contract),
        )
        packs = pack_keys or self._resolve_post_artifact_packs(contract, fallback=("memory_candidate",))
        steps: list[PlanStepSpec] = [prepare_step, policy_step, artifact_step]
        memory_depends_on = ["step_artifact_save", "step_policy_evaluate"]
        additional_input_keys: tuple[str, ...] = self._artifact_evidence_output_keys(contract)
        if "dispatch" in packs:
            steps.append(self._build_dispatch_step(contract=contract, principal_id=principal_id, depends_on=("step_policy_evaluate",)))
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
        principal_id: str,
    ) -> tuple[PlanStepSpec, ...]:
        return self._build_artifact_then_packs_steps(
            intent,
            contract=contract,
            principal_id=principal_id,
            pack_keys=("dispatch", "memory_candidate"),
        )

    def _workflow_template_key(self, contract: TaskContract) -> str:
        return contract.runtime_policy().workflow_template_key

    def _steps_for_contract(self, intent: IntentSpecV3, contract: TaskContract, *, principal_id: str) -> tuple[PlanStepSpec, ...]:
        workflow_template = self._workflow_template_key(contract)
        builder = self._workflow_template_builders.get(workflow_template)
        if builder is None:
            raise PlanValidationError(f"unknown_workflow_template:{workflow_template}")
        return builder(intent, contract=contract, principal_id=principal_id)

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
        steps = self._steps_for_contract(intent, contract, principal_id=principal_id)
        plan = PlanSpec(
            plan_id=str(uuid.uuid4()),
            task_key=intent.task_type,
            principal_id=intent.principal_id,
            created_at=now_utc_iso(),
            steps=steps,
        )
        validate_plan_spec(plan)
        return intent, plan
