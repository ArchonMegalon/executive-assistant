from __future__ import annotations

from typing import Callable

from app.domain.models import ToolDefinition, ToolInvocationRequest, ToolInvocationResult
from app.services.channel_runtime import ChannelRuntimeService
from app.services.tool_execution_connector_dispatch_adapter import ConnectorDispatchToolAdapter
from app.services.tool_execution_connector_dispatch_registry import register_builtin_connector_dispatch
from app.services.tool_runtime import ToolRuntimeService

ToolExecutionHandler = Callable[[ToolInvocationRequest, ToolDefinition], ToolInvocationResult]


class ConnectorDispatchToolExecutionModule:
    def __init__(
        self,
        *,
        tool_runtime: ToolRuntimeService,
        channel_runtime: ChannelRuntimeService | None = None,
    ) -> None:
        self._tool_runtime = tool_runtime
        self.adapter = ConnectorDispatchToolAdapter(
            tool_runtime=tool_runtime,
            channel_runtime=channel_runtime,
        )

    def register_builtin(self, register_handler: Callable[[str, ToolExecutionHandler], None]) -> None:
        register_builtin_connector_dispatch(
            tool_runtime=self._tool_runtime,
            register_handler=register_handler,
            connector_dispatch_adapter=self.adapter,
        )
