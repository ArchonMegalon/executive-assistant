from __future__ import annotations

from typing import Callable

from app.domain.models import ToolDefinition, ToolInvocationRequest, ToolInvocationResult
from app.repositories.artifacts import ArtifactRepository
from app.services.browseract_ui_service_catalog import browseract_ui_service_definitions
from app.services.channel_runtime import ChannelRuntimeService
from app.services.evidence_runtime import EvidenceRuntimeService
from app.services.provider_registry import ProviderRegistryService
from app.services.tool_execution_artifact_module import ArtifactToolExecutionModule
from app.services.tool_execution_browseract_module import BrowserActToolExecutionModule
from app.services.tool_execution_common import (
    CONNECTOR_DISPATCH_IDEMPOTENCY_POLICY,
    CONNECTOR_DISPATCH_OPTIONAL_INPUT_FIELDS,
    CONNECTOR_DISPATCH_REQUIRED_INPUT_FIELDS,
    ToolExecutionError,
)
from app.services.tool_execution_connector_dispatch_module import ConnectorDispatchToolExecutionModule
from app.services.tool_execution_gemini_vortex_module import GeminiVortexToolExecutionModule
from app.services.tool_execution_magixai_module import MagixaiToolExecutionModule
from app.services.tool_execution_onemin_module import OneminToolExecutionModule
from app.services.tool_runtime import ToolRuntimeService

ToolExecutionHandler = Callable[[ToolInvocationRequest, ToolDefinition], ToolInvocationResult]


class ToolExecutionService:
    def __init__(
        self,
        *,
        tool_runtime: ToolRuntimeService,
        artifacts: ArtifactRepository,
        channel_runtime: ChannelRuntimeService | None = None,
        evidence_runtime: EvidenceRuntimeService | None = None,
        provider_registry: ProviderRegistryService | None = None,
    ) -> None:
        self._tool_runtime = tool_runtime
        self._provider_registry = provider_registry or ProviderRegistryService()
        self._handlers: dict[str, ToolExecutionHandler] = {}
        self._connector_dispatch_module = ConnectorDispatchToolExecutionModule(
            tool_runtime=tool_runtime,
            channel_runtime=channel_runtime,
        )
        self._browseract_module = BrowserActToolExecutionModule(
            tool_runtime=tool_runtime,
            connector_dispatch=self._connector_dispatch_module.adapter,
        )
        self._gemini_vortex_module = GeminiVortexToolExecutionModule(
            tool_runtime=tool_runtime,
        )
        self._magixai_module = MagixaiToolExecutionModule(
            tool_runtime=tool_runtime,
        )
        self._onemin_module = OneminToolExecutionModule(
            tool_runtime=tool_runtime,
        )
        self._artifact_module = ArtifactToolExecutionModule(
            tool_runtime=tool_runtime,
            artifacts=artifacts,
            evidence_runtime=evidence_runtime,
        )
        self._builtin_capability_registrars: dict[tuple[str, str], Callable[[], None]] = {
            ("artifact_repository", "artifact_save"): self._register_builtin_artifact_repository,
            ("browseract", "account_facts"): self._register_builtin_browseract_extract,
            ("browseract", "account_inventory"): self._register_builtin_browseract_inventory,
            ("browseract", "workflow_spec_build"): self._register_builtin_browseract_workflow_spec,
            ("browseract", "workflow_spec_repair"): self._register_builtin_browseract_workflow_repair,
            ("browseract", "chatplayground_audit"): self._register_builtin_browseract_chatplayground_audit,
            ("browseract", "reasoned_patch_review"): self._register_builtin_browseract_chatplayground_audit,
            ("browseract", "gemini_web_generate"): self._register_builtin_browseract_gemini_web_generate,
            ("browseract", "onemin_billing_usage"): self._register_builtin_browseract_onemin_billing_usage,
            ("browseract", "onemin_member_reconciliation"): self._register_builtin_browseract_onemin_member_reconciliation,
            ("browseract", "crezlo_property_tour"): self._register_builtin_browseract_crezlo_property_tour,
            ("connector_dispatch", "dispatch"): self._register_builtin_connector_dispatch,
            ("gemini_vortex", "structured_generate"): self._register_builtin_gemini_vortex_structured_generate,
            ("magixai", "structured_generate"): self._register_builtin_magixai_structured_generate,
            ("onemin", "code_generate"): self._register_builtin_onemin_code_generate,
            ("onemin", "reasoned_patch_review"): self._register_builtin_onemin_reasoned_patch_review,
            ("onemin", "image_generate"): self._register_builtin_onemin_image_generate,
            ("onemin", "media_transform"): self._register_builtin_onemin_media_transform,
        }
        for ui_service in browseract_ui_service_definitions():
            self._builtin_capability_registrars[("browseract", ui_service.capability_key)] = (
                lambda capability_key=ui_service.capability_key: self._register_builtin_browseract_ui_service(capability_key)
            )
        self._register_executable_provider_bindings()
        self._register_builtin_brain_router_structured_generate()
        self._register_builtin_brain_router_reasoned_patch_review()

    def register_handler(self, tool_name: str, handler: ToolExecutionHandler) -> None:
        key = str(tool_name or "").strip()
        if not key:
            raise ValueError("tool_name is required")
        self._handlers[key] = handler

    def execute_invocation(self, request: ToolInvocationRequest) -> ToolInvocationResult:
        requested_tool_name = str(request.tool_name or "").strip()
        tool_name = requested_tool_name
        context_json = dict(request.context_json or {})
        requested_principal_id = str(context_json.get("principal_id") or "").strip() or None
        try:
            route = self._provider_registry.route_tool_with_context(requested_tool_name, principal_id=requested_principal_id)
        except ToolExecutionError as exc:
            if (
                str(exc or "") != f"provider_tool_unavailable:{requested_tool_name}"
                or self._provider_registry.knows_tool(requested_tool_name)
            ):
                raise
        else:
            tool_name = route.tool_name
        if not tool_name:
            raise ToolExecutionError("tool_name_required")
        definition = self._tool_runtime.get_tool(tool_name)
        if definition is None:
            self._ensure_builtin_tool_registered(tool_name, principal_id=requested_principal_id)
            definition = self._tool_runtime.get_tool(tool_name)
        if definition is None:
            raise ToolExecutionError(f"tool_not_registered:{tool_name}")
        if not definition.enabled:
            raise ToolExecutionError(f"tool_disabled:{tool_name}")
        handler = self._handlers.get(tool_name)
        if handler is None:
            raise ToolExecutionError(f"tool_handler_missing:{tool_name}")
        if tool_name != requested_tool_name:
            request = ToolInvocationRequest(
                session_id=request.session_id,
                step_id=request.step_id,
                tool_name=tool_name,
                action_kind=request.action_kind,
                payload_json=dict(request.payload_json or {}),
                context_json=context_json,
            )
        return handler(request, definition)

    def _ensure_builtin_tool_registered(self, tool_name: str, *, principal_id: str | None = None) -> None:
        key = str(tool_name or "").strip()
        if not key:
            return
        try:
            route = self._provider_registry.route_tool_with_context(key, principal_id=principal_id)
        except ToolExecutionError:
            return
        registrar = self._builtin_capability_registrars.get((route.provider_key, route.capability_key))
        if registrar is not None:
            registrar()

    def _register_executable_provider_bindings(self) -> None:
        for binding in self._provider_registry.list_bindings():
            if not binding.executable:
                continue
            for capability in binding.capabilities:
                if not capability.executable:
                    continue
                registrar = self._builtin_capability_registrars.get((binding.provider_key, capability.capability_key))
                if registrar is not None:
                    registrar()

    def _register_builtin_artifact_repository(self) -> None:
        self._artifact_module.register_builtin(self.register_handler)

    def _register_builtin_browseract_extract(self) -> None:
        self._browseract_module.register_extract(self.register_handler)

    def _register_builtin_browseract_inventory(self) -> None:
        self._browseract_module.register_inventory(self.register_handler)

    def _register_builtin_browseract_workflow_spec(self) -> None:
        self._browseract_module.register_workflow_spec(self.register_handler)

    def _register_builtin_browseract_workflow_repair(self) -> None:
        self._browseract_module.register_workflow_repair(self.register_handler)

    def _register_builtin_browseract_chatplayground_audit(self) -> None:
        self._browseract_module.register_chatplayground_audit(self.register_handler)

    def _register_builtin_browseract_gemini_web_generate(self) -> None:
        self._browseract_module.register_gemini_web_generate(self.register_handler)

    def _register_builtin_browseract_onemin_billing_usage(self) -> None:
        self._browseract_module.register_onemin_billing_usage(self.register_handler)

    def _register_builtin_browseract_onemin_member_reconciliation(self) -> None:
        self._browseract_module.register_onemin_member_reconciliation(self.register_handler)

    def _register_builtin_browseract_crezlo_property_tour(self) -> None:
        self._browseract_module.register_crezlo_property_tour(self.register_handler)

    def _register_builtin_browseract_ui_service(self, capability_key: str) -> None:
        self._browseract_module.register_ui_service(
            self.register_handler,
            capability_key=capability_key,
        )

    def _register_builtin_connector_dispatch(self) -> None:
        self._connector_dispatch_module.register_builtin(self.register_handler)

    def _register_builtin_gemini_vortex_structured_generate(self) -> None:
        self._gemini_vortex_module.register_structured_generate(self.register_handler)

    def _register_builtin_magixai_structured_generate(self) -> None:
        self._magixai_module.register_structured_generate(self.register_handler)

    def _register_builtin_onemin_code_generate(self) -> None:
        self._onemin_module.register_code_generate(self.register_handler)

    def _register_builtin_onemin_reasoned_patch_review(self) -> None:
        self._onemin_module.register_reasoned_patch_review(self.register_handler)

    def _register_builtin_onemin_image_generate(self) -> None:
        self._onemin_module.register_image_generate(self.register_handler)

    def _register_builtin_onemin_media_transform(self) -> None:
        self._onemin_module.register_media_transform(self.register_handler)

    def _register_builtin_brain_router_structured_generate(self) -> None:
        self._register_builtin_brain_router_tool(
            tool_name="provider.brain_router.structured_generate",
            action_kind="content.generate",
            capability_key="structured_generate",
        )

    def _register_builtin_brain_router_reasoned_patch_review(self) -> None:
        self._register_builtin_brain_router_tool(
            tool_name="provider.brain_router.reasoned_patch_review",
            action_kind="audit.review_light",
            capability_key="reasoned_patch_review",
        )

    def _register_builtin_brain_router_tool(
        self,
        *,
        tool_name: str,
        action_kind: str,
        capability_key: str,
    ) -> None:
        self._tool_runtime.upsert_tool(
            tool_name=tool_name,
            version="builtin-brain-router-v1",
            input_schema_json={"type": "object"},
            output_schema_json={"type": "object"},
            policy_json={
                "logical_tool": True,
                "brain_router": True,
                "capability_key": capability_key,
                "action_kind": action_kind,
            },
            approval_default="none",
            enabled=True,
        )

        def _handler(request: ToolInvocationRequest, definition: ToolDefinition) -> ToolInvocationResult:
            return self._execute_brain_router_capability(
                request=request,
                definition=definition,
                capability_key=capability_key,
            )

        self.register_handler(tool_name, _handler)

    def _execute_brain_router_capability(
        self,
        *,
        request: ToolInvocationRequest,
        definition: ToolDefinition,
        capability_key: str,
    ) -> ToolInvocationResult:
        payload_json = dict(request.payload_json or {})
        context_json = dict(request.context_json or {})
        principal_id = str(context_json.get("principal_id") or "").strip() or None
        provider_hints = tuple(
            str(value or "").strip()
            for value in (payload_json.get("provider_hint_order") or ())
            if str(value or "").strip()
        )
        allowed_tools = tuple(
            str(value or "").strip()
            for value in (payload_json.get("allowed_tools") or ())
            if str(value or "").strip()
        )
        profile_name = str(payload_json.get("brain_profile") or "").strip()
        if not profile_name and capability_key == "reasoned_patch_review":
            profile_name = str(payload_json.get("posthoc_review_profile") or "").strip()
        if not profile_name:
            profile_name = "review_light" if capability_key == "reasoned_patch_review" else "easy"
        effective_action_kind = str(request.action_kind or "").strip()
        if capability_key == "reasoned_patch_review":
            inferred_review_action = "audit.jury" if profile_name == "audit" else "audit.review_light"
            if not effective_action_kind or effective_action_kind == "audit.review_light":
                effective_action_kind = inferred_review_action
        elif not effective_action_kind:
            effective_action_kind = str((definition.policy_json or {}).get("action_kind") or "").strip()
        route = self._provider_registry.route_brain_profile_capability_with_context(
            profile_name=profile_name,
            capability_key=capability_key,
            principal_id=principal_id,
            allowed_tools=allowed_tools,
            require_executable=True,
            provider_hints=provider_hints,
        )
        self._ensure_builtin_tool_registered(route.tool_name, principal_id=principal_id)
        routed_definition = self._tool_runtime.get_tool(route.tool_name)
        if routed_definition is None:
            raise ToolExecutionError(f"tool_not_registered:{route.tool_name}")
        if not routed_definition.enabled:
            raise ToolExecutionError(f"tool_disabled:{route.tool_name}")
        routed_handler = self._handlers.get(route.tool_name)
        if routed_handler is None:
            raise ToolExecutionError(f"tool_handler_missing:{route.tool_name}")
        routed_payload_json = dict(payload_json)
        routed_payload_json.setdefault("brain_profile", profile_name)
        routed_payload_json["routed_provider_key"] = route.provider_key
        routed_payload_json["routed_capability_key"] = route.capability_key
        result = routed_handler(
            ToolInvocationRequest(
                session_id=request.session_id,
                step_id=request.step_id,
                tool_name=route.tool_name,
                action_kind=effective_action_kind,
                payload_json=routed_payload_json,
                context_json=context_json,
            ),
            routed_definition,
        )
        output_json = self._normalize_brain_router_output(
            capability_key=capability_key,
            profile_name=profile_name,
            output_json=dict(result.output_json or {}),
        )
        route_fallback_used = bool(provider_hints and route.provider_key != provider_hints[0])
        output_json.setdefault("brain_profile", profile_name)
        output_json.setdefault("posthoc_review_profile", str(payload_json.get("posthoc_review_profile") or "").strip())
        output_json.setdefault("fallback_brain_profile", str(payload_json.get("fallback_brain_profile") or "").strip())
        output_json.setdefault("routed_provider_key", route.provider_key)
        output_json.setdefault("routed_capability_key", route.capability_key)
        output_json.setdefault("route_fallback_used", route_fallback_used)
        receipt_json = dict(result.receipt_json or {})
        receipt_json.setdefault("logical_tool_name", definition.tool_name)
        receipt_json.setdefault("brain_profile", profile_name)
        receipt_json.setdefault("posthoc_review_profile", str(payload_json.get("posthoc_review_profile") or "").strip())
        receipt_json.setdefault("fallback_brain_profile", str(payload_json.get("fallback_brain_profile") or "").strip())
        receipt_json.setdefault("routed_provider_key", route.provider_key)
        receipt_json.setdefault("routed_capability_key", route.capability_key)
        receipt_json.setdefault("route_fallback_used", route_fallback_used)
        return ToolInvocationResult(
            tool_name=result.tool_name,
            action_kind=result.action_kind,
            target_ref=result.target_ref,
            output_json=output_json,
            receipt_json=receipt_json,
            artifacts=tuple(result.artifacts or ()),
            model_name=result.model_name,
            tokens_in=result.tokens_in,
            tokens_out=result.tokens_out,
            cost_usd=result.cost_usd,
        )

    def _normalize_brain_router_output(
        self,
        *,
        capability_key: str,
        profile_name: str,
        output_json: dict[str, object],
    ) -> dict[str, object]:
        normalized = dict(output_json or {})
        structured = dict(normalized.get("structured_output_json") or {})
        text = str(normalized.get("normalized_text") or "").strip()
        if capability_key == "structured_generate" and str(profile_name or "").strip() == "groundwork":
            structured["format"] = "groundwork_brief"
            structured["plan"] = self._normalize_brain_router_list(structured.get("plan"), fallback=text)
            structured["risks"] = self._normalize_brain_router_list(structured.get("risks"))
            structured["missing_evidence"] = self._normalize_brain_router_list(structured.get("missing_evidence"))
            structured["recommended_next_lane"] = str(
                structured.get("recommended_next_lane") or "review_light"
            ).strip() or "review_light"
            structured["acceptance_checklist"] = self._normalize_brain_router_list(
                structured.get("acceptance_checklist")
            )
            normalized["structured_output_json"] = structured
            return normalized
        if capability_key == "reasoned_patch_review":
            structured["format"] = "review_packet"
            structured["recommendation"] = str(
                structured.get("recommendation") or structured.get("consensus") or text
            ).strip()
            structured["disagreements"] = self._normalize_brain_router_list(structured.get("disagreements"))
            structured["risks"] = self._normalize_brain_router_list(structured.get("risks"))
            structured["roles"] = self._normalize_brain_router_list(structured.get("roles")) or [
                "factuality",
                "adversarial",
                "completeness",
                "risk",
            ]
            structured["audit_scope"] = str(
                structured.get("audit_scope") or ("jury" if profile_name == "audit" else "review_light")
            ).strip() or ("jury" if profile_name == "audit" else "review_light")
            normalized["structured_output_json"] = structured
        return normalized

    def _normalize_brain_router_list(self, value: object, *, fallback: str = "") -> list[str]:
        if isinstance(value, list):
            values = [str(item or "").strip() for item in value if str(item or "").strip()]
            if values:
                return values
        if isinstance(value, tuple):
            values = [str(item or "").strip() for item in value if str(item or "").strip()]
            if values:
                return values
        text = str(value or "").strip()
        if text:
            return [text]
        fallback_text = str(fallback or "").strip()
        if fallback_text:
            return [fallback_text]
        return []

    @property
    def _browseract_live_extract(self):
        return self._browseract_module.live_extract

    @_browseract_live_extract.setter
    def _browseract_live_extract(self, handler) -> None:
        self._browseract_module.live_extract = handler

    @property
    def _browseract_chatplayground_audit(self):
        return self._browseract_module.chatplayground_audit

    @_browseract_chatplayground_audit.setter
    def _browseract_chatplayground_audit(self, handler) -> None:
        self._browseract_module.chatplayground_audit = handler

    @property
    def _browseract_gemini_web_generate(self):
        return self._browseract_module.gemini_web_generate

    @_browseract_gemini_web_generate.setter
    def _browseract_gemini_web_generate(self, handler) -> None:
        self._browseract_module.gemini_web_generate = handler

    @property
    def _browseract_onemin_billing_usage(self):
        return self._browseract_module.onemin_billing_usage

    @_browseract_onemin_billing_usage.setter
    def _browseract_onemin_billing_usage(self, handler) -> None:
        self._browseract_module.onemin_billing_usage = handler

    @property
    def _browseract_onemin_member_reconciliation(self):
        return self._browseract_module.onemin_member_reconciliation

    @_browseract_onemin_member_reconciliation.setter
    def _browseract_onemin_member_reconciliation(self, handler) -> None:
        self._browseract_module.onemin_member_reconciliation = handler

    @property
    def _browseract_crezlo_property_tour(self):
        return self._browseract_module.crezlo_property_tour

    @_browseract_crezlo_property_tour.setter
    def _browseract_crezlo_property_tour(self, handler) -> None:
        self._browseract_module.crezlo_property_tour = handler

    @property
    def _browseract_ui_service_callbacks(self) -> dict[str, object]:
        return self._browseract_module.ui_service_callbacks
