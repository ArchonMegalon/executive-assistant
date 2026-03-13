from __future__ import annotations

from typing import Callable

from app.domain.models import ToolDefinition, ToolInvocationRequest, ToolInvocationResult
from app.services.tool_execution_browseract_adapter import BrowserActToolAdapter
from app.services.tool_execution_browseract_registry import (
    register_builtin_browseract_extract,
    register_builtin_browseract_inventory,
    register_builtin_browseract_workflow_spec,
)
from app.services.tool_execution_connector_dispatch_adapter import ConnectorDispatchToolAdapter
from app.services.tool_runtime import ToolRuntimeService

ToolExecutionHandler = Callable[[ToolInvocationRequest, ToolDefinition], ToolInvocationResult]


class BrowserActToolExecutionModule:
    def __init__(
        self,
        *,
        tool_runtime: ToolRuntimeService,
        connector_dispatch: ConnectorDispatchToolAdapter,
    ) -> None:
        self._tool_runtime = tool_runtime
        self._adapter = BrowserActToolAdapter(
            connector_dispatch=connector_dispatch,
        )

    @property
    def live_extract(self):
        return self._adapter._live_extract

    @live_extract.setter
    def live_extract(self, handler) -> None:
        self._adapter._live_extract = handler

    def register_extract(self, register_handler: Callable[[str, ToolExecutionHandler], None]) -> None:
        register_builtin_browseract_extract(
            tool_runtime=self._tool_runtime,
            register_handler=register_handler,
            browseract_adapter=self._adapter,
        )

    def register_inventory(self, register_handler: Callable[[str, ToolExecutionHandler], None]) -> None:
        register_builtin_browseract_inventory(
            tool_runtime=self._tool_runtime,
            register_handler=register_handler,
            browseract_adapter=self._adapter,
        )

    def register_workflow_spec(self, register_handler: Callable[[str, ToolExecutionHandler], None]) -> None:
        register_builtin_browseract_workflow_spec(
            tool_runtime=self._tool_runtime,
            register_handler=register_handler,
            browseract_adapter=self._adapter,
        )
