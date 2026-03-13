from __future__ import annotations

from typing import Callable

from app.domain.models import ToolDefinition, ToolInvocationRequest, ToolInvocationResult
from app.services.tool_execution_gemini_vortex_adapter import GeminiVortexToolAdapter
from app.services.tool_execution_gemini_vortex_registry import register_builtin_gemini_vortex_structured_generate
from app.services.tool_runtime import ToolRuntimeService

ToolExecutionHandler = Callable[[ToolInvocationRequest, ToolDefinition], ToolInvocationResult]


class GeminiVortexToolExecutionModule:
    def __init__(
        self,
        *,
        tool_runtime: ToolRuntimeService,
    ) -> None:
        self._tool_runtime = tool_runtime
        self._adapter = GeminiVortexToolAdapter()

    def register_structured_generate(self, register_handler: Callable[[str, ToolExecutionHandler], None]) -> None:
        register_builtin_gemini_vortex_structured_generate(
            tool_runtime=self._tool_runtime,
            register_handler=register_handler,
            gemini_vortex_adapter=self._adapter,
        )
