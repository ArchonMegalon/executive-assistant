from __future__ import annotations

from typing import Callable

from app.domain.models import ToolDefinition, ToolInvocationRequest, ToolInvocationResult
from app.repositories.artifacts import ArtifactRepository
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
            ("browseract", "gemini_web_generate"): self._register_builtin_browseract_gemini_web_generate,
            ("browseract", "onemin_billing_usage"): self._register_builtin_browseract_onemin_billing_usage,
            ("browseract", "onemin_member_reconciliation"): self._register_builtin_browseract_onemin_member_reconciliation,
            ("connector_dispatch", "dispatch"): self._register_builtin_connector_dispatch,
            ("gemini_vortex", "structured_generate"): self._register_builtin_gemini_vortex_structured_generate,
            ("onemin", "code_generate"): self._register_builtin_onemin_code_generate,
            ("onemin", "reasoned_patch_review"): self._register_builtin_onemin_reasoned_patch_review,
            ("onemin", "image_generate"): self._register_builtin_onemin_image_generate,
            ("onemin", "media_transform"): self._register_builtin_onemin_media_transform,
        }
        self._register_executable_provider_bindings()

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

    def _register_builtin_connector_dispatch(self) -> None:
        self._connector_dispatch_module.register_builtin(self.register_handler)

    def _register_builtin_gemini_vortex_structured_generate(self) -> None:
        self._gemini_vortex_module.register_structured_generate(self.register_handler)

    def _register_builtin_onemin_code_generate(self) -> None:
        self._onemin_module.register_code_generate(self.register_handler)

    def _register_builtin_onemin_reasoned_patch_review(self) -> None:
        self._onemin_module.register_reasoned_patch_review(self.register_handler)

    def _register_builtin_onemin_image_generate(self) -> None:
        self._onemin_module.register_image_generate(self.register_handler)

    def _register_builtin_onemin_media_transform(self) -> None:
        self._onemin_module.register_media_transform(self.register_handler)

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
