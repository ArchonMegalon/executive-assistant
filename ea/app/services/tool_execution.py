from __future__ import annotations

from typing import Callable

from app.domain.models import ToolDefinition, ToolInvocationRequest, ToolInvocationResult
from app.repositories.artifacts import ArtifactRepository
from app.services.channel_runtime import ChannelRuntimeService
from app.services.evidence_runtime import EvidenceRuntimeService
from app.services.tool_execution_artifact_adapter import ArtifactRepositoryToolAdapter
from app.services.tool_execution_browseract_adapter import BrowserActToolAdapter
from app.services.tool_execution_artifact_registry import register_builtin_artifact_repository
from app.services.tool_execution_browseract_registry import (
    register_builtin_browseract_extract,
    register_builtin_browseract_inventory,
)
from app.services.tool_execution_common import (
    CONNECTOR_DISPATCH_ALLOWED_CHANNELS,
    CONNECTOR_DISPATCH_IDEMPOTENCY_POLICY,
    CONNECTOR_DISPATCH_OPTIONAL_INPUT_FIELDS,
    CONNECTOR_DISPATCH_REQUIRED_INPUT_FIELDS,
    ToolExecutionError,
)
from app.services.tool_execution_connector_dispatch_adapter import ConnectorDispatchToolAdapter
from app.services.tool_execution_connector_dispatch_registry import register_builtin_connector_dispatch
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
        # Artifact tool outputs preserve evidence_object_id and citation_handle when materialized.
        register_builtin_artifact_repository(
            tool_runtime=self._tool_runtime,
            register_handler=self.register_handler,
            artifact_adapter=self._artifact_adapter,
        )

    def _register_builtin_browseract_extract(self) -> None:
        register_builtin_browseract_extract(
            tool_runtime=self._tool_runtime,
            register_handler=self.register_handler,
            browseract_adapter=self._browseract_adapter,
        )

    def _register_builtin_browseract_inventory(self) -> None:
        register_builtin_browseract_inventory(
            tool_runtime=self._tool_runtime,
            register_handler=self.register_handler,
            browseract_adapter=self._browseract_adapter,
        )

    def _register_builtin_connector_dispatch(self) -> None:
        register_builtin_connector_dispatch(
            tool_runtime=self._tool_runtime,
            register_handler=self.register_handler,
            connector_dispatch_adapter=self._connector_dispatch_adapter,
        )
