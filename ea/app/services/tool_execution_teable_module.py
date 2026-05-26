from __future__ import annotations

from typing import Callable

from app.domain.models import ToolDefinition, ToolInvocationRequest, ToolInvocationResult
from app.services.tool_execution_teable_adapter import TeableToolAdapter
from app.services.tool_execution_teable_registry import register_builtin_teable_table_sync
from app.services.tool_runtime import ToolRuntimeService

ToolExecutionHandler = Callable[[ToolInvocationRequest, ToolDefinition], ToolInvocationResult]


class TeableToolExecutionModule:
    def __init__(
        self,
        *,
        tool_runtime: ToolRuntimeService,
    ) -> None:
        self._tool_runtime = tool_runtime
        self._adapter = TeableToolAdapter()

    def register_table_sync(self, register_handler: Callable[[str, ToolExecutionHandler], None]) -> None:
        register_builtin_teable_table_sync(
            tool_runtime=self._tool_runtime,
            register_handler=register_handler,
            teable_adapter=self._adapter,
        )
