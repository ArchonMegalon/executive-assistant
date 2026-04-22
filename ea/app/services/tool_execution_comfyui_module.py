from __future__ import annotations

from typing import Callable

from app.domain.models import ToolDefinition, ToolInvocationRequest, ToolInvocationResult
from app.services.tool_execution_comfyui_adapter import ComfyUIToolAdapter
from app.services.tool_execution_comfyui_registry import register_builtin_comfyui_image_generate
from app.services.tool_runtime import ToolRuntimeService

ToolExecutionHandler = Callable[[ToolInvocationRequest, ToolDefinition], ToolInvocationResult]


class ComfyUIToolExecutionModule:
    def __init__(
        self,
        *,
        tool_runtime: ToolRuntimeService,
    ) -> None:
        self._tool_runtime = tool_runtime
        self._adapter = ComfyUIToolAdapter()

    def register_image_generate(self, register_handler: Callable[[str, ToolExecutionHandler], None]) -> None:
        register_builtin_comfyui_image_generate(
            tool_runtime=self._tool_runtime,
            register_handler=register_handler,
            comfyui_adapter=self._adapter,
        )
