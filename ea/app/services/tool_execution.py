from __future__ import annotations

from typing import Callable

from app.domain.models import ToolDefinition, ToolInvocationRequest, ToolInvocationResult
from app.repositories.artifacts import ArtifactRepository
from app.services.channel_runtime import ChannelRuntimeService
from app.services.evidence_runtime import EvidenceRuntimeService
from app.services.tool_execution_artifact_adapter import ArtifactRepositoryToolAdapter
from app.services.tool_execution_browseract_adapter import BrowserActToolAdapter
from app.services.tool_execution_common import (
    CONNECTOR_DISPATCH_ALLOWED_CHANNELS,
    CONNECTOR_DISPATCH_IDEMPOTENCY_POLICY,
    CONNECTOR_DISPATCH_OPTIONAL_INPUT_FIELDS,
    CONNECTOR_DISPATCH_REQUIRED_INPUT_FIELDS,
    ToolExecutionError,
)
from app.services.tool_execution_connector_dispatch_adapter import ConnectorDispatchToolAdapter
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
    ) -> None:
        self._tool_runtime = tool_runtime
        self._handlers: dict[str, ToolExecutionHandler] = {}
        self._artifact_adapter = ArtifactRepositoryToolAdapter(
            artifacts=artifacts,
            evidence_runtime=evidence_runtime,
        )
        self._connector_dispatch_adapter = ConnectorDispatchToolAdapter(
            tool_runtime=tool_runtime,
            channel_runtime=channel_runtime,
        )
        self._browseract_adapter = BrowserActToolAdapter(
            connector_dispatch=self._connector_dispatch_adapter,
        )
        self._register_builtin_artifact_repository()
        self._register_builtin_browseract_extract()
        self._register_builtin_browseract_inventory()
        self._register_builtin_connector_dispatch()

    def register_handler(self, tool_name: str, handler: ToolExecutionHandler) -> None:
        key = str(tool_name or "").strip()
        if not key:
            raise ValueError("tool_name is required")
        self._handlers[key] = handler

    def execute_invocation(self, request: ToolInvocationRequest) -> ToolInvocationResult:
        tool_name = str(request.tool_name or "").strip()
        if not tool_name:
            raise ToolExecutionError("tool_name_required")
        definition = self._tool_runtime.get_tool(tool_name)
        if definition is None:
            self._ensure_builtin_tool_registered(tool_name)
            definition = self._tool_runtime.get_tool(tool_name)
        if definition is None:
            raise ToolExecutionError(f"tool_not_registered:{tool_name}")
        if not definition.enabled:
            raise ToolExecutionError(f"tool_disabled:{tool_name}")
        handler = self._handlers.get(tool_name)
        if handler is None:
            raise ToolExecutionError(f"tool_handler_missing:{tool_name}")
        return handler(request, definition)

    def _ensure_builtin_tool_registered(self, tool_name: str) -> None:
        key = str(tool_name or "").strip()
        if key == "artifact_repository":
            self._register_builtin_artifact_repository()
            return
        if key == "browseract.extract_account_facts":
            self._register_builtin_browseract_extract()
            return
        if key == "browseract.extract_account_inventory":
            self._register_builtin_browseract_inventory()
            return
        if key == "connector.dispatch":
            self._register_builtin_connector_dispatch()

    def _register_builtin_artifact_repository(self) -> None:
        if self._tool_runtime.get_tool("artifact_repository") is None:
            self._tool_runtime.upsert_tool(
                tool_name="artifact_repository",
                version="v1",
                input_schema_json={
                    "type": "object",
                    "required": ["source_text"],
                    "properties": {
                        "source_text": {"type": "string"},
                        "expected_artifact": {"type": "string"},
                        "plan_id": {"type": "string"},
                        "plan_step_key": {"type": "string"},
                    },
                },
                output_schema_json={
                    "type": "object",
                    "required": ["artifact_id", "artifact_kind", "tool_name", "action_kind"],
                },
                policy_json={"builtin": True, "action_kind": "artifact.save"},
                approval_default="none",
                enabled=True,
            )
        self.register_handler("artifact_repository", self._artifact_adapter.execute)

    def _register_builtin_browseract_extract(self) -> None:
        if self._tool_runtime.get_tool("browseract.extract_account_facts") is None:
            self._tool_runtime.upsert_tool(
                tool_name="browseract.extract_account_facts",
                version="v1",
                input_schema_json={
                    "type": "object",
                    "required": ["binding_id", "service_name"],
                    "properties": {
                        "binding_id": {"type": "string"},
                        "service_name": {"type": "string"},
                        "requested_fields": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                        "run_url": {"type": "string"},
                        "instructions": {"type": "string"},
                        "account_hints_json": {"type": "object"},
                    },
                },
                output_schema_json={
                    "type": "object",
                    "required": ["service_name", "facts_json", "missing_fields", "tool_name", "action_kind"],
                },
                policy_json={"builtin": True, "action_kind": "account.extract"},
                approval_default="none",
                enabled=True,
            )
        self.register_handler("browseract.extract_account_facts", self._browseract_adapter.execute_extract)

    def _register_builtin_browseract_inventory(self) -> None:
        if self._tool_runtime.get_tool("browseract.extract_account_inventory") is None:
            self._tool_runtime.upsert_tool(
                tool_name="browseract.extract_account_inventory",
                version="v1",
                input_schema_json={
                    "type": "object",
                    "required": ["binding_id"],
                    "properties": {
                        "binding_id": {"type": "string"},
                        "service_names": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                        "requested_fields": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                        "run_url": {"type": "string"},
                        "instructions": {"type": "string"},
                        "account_hints_json": {"type": "object"},
                    },
                },
                output_schema_json={
                    "type": "object",
                    "required": ["service_names", "services_json", "tool_name", "action_kind"],
                },
                policy_json={"builtin": True, "action_kind": "account.extract_inventory"},
                approval_default="none",
                enabled=True,
            )
        self.register_handler("browseract.extract_account_inventory", self._browseract_adapter.execute_inventory)

    def _register_builtin_connector_dispatch(self) -> None:
        if self._connector_dispatch_adapter.channel_runtime is None:
            return
        if self._tool_runtime.get_tool("connector.dispatch") is None:
            self._tool_runtime.upsert_tool(
                tool_name="connector.dispatch",
                version="v1",
                input_schema_json={
                    "type": "object",
                    "required": list(CONNECTOR_DISPATCH_REQUIRED_INPUT_FIELDS),
                    "properties": {
                        "binding_id": {"type": "string"},
                        "channel": {"type": "string"},
                        "recipient": {"type": "string"},
                        "content": {"type": "string"},
                        "metadata": {"type": "object"},
                        "idempotency_key": {"type": "string"},
                    },
                },
                output_schema_json={
                    "type": "object",
                    "required": ["delivery_id", "status", "tool_name", "action_kind"],
                },
                policy_json={
                    "builtin": True,
                    "action_kind": "delivery.send",
                    "idempotency_key_policy": CONNECTOR_DISPATCH_IDEMPOTENCY_POLICY,
                },
                allowed_channels=CONNECTOR_DISPATCH_ALLOWED_CHANNELS,
                approval_default="manager",
                enabled=True,
            )
        self.register_handler("connector.dispatch", self._connector_dispatch_adapter.execute)
