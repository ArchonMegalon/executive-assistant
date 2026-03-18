from __future__ import annotations

from typing import Callable

from app.domain.models import ToolDefinition, ToolInvocationRequest, ToolInvocationResult
from app.services.tool_execution_onemin_adapter import OneminToolAdapter
from app.services.tool_execution_onemin_registry import (
    register_builtin_onemin_code_generate,
    register_builtin_onemin_image_generate,
    register_builtin_onemin_media_transform,
    register_builtin_onemin_reasoned_patch_review,
)
from app.services.tool_runtime import ToolRuntimeService

ToolExecutionHandler = Callable[[ToolInvocationRequest, ToolDefinition], ToolInvocationResult]


class OneminToolExecutionModule:
    def __init__(
        self,
        *,
        tool_runtime: ToolRuntimeService,
    ) -> None:
        self._tool_runtime = tool_runtime
        self._adapter = OneminToolAdapter()

    def register_code_generate(self, register_handler: Callable[[str, ToolExecutionHandler], None]) -> None:
        register_builtin_onemin_code_generate(
            tool_runtime=self._tool_runtime,
            register_handler=register_handler,
            onemin_adapter=self._adapter,
        )

    def register_reasoned_patch_review(self, register_handler: Callable[[str, ToolExecutionHandler], None]) -> None:
        register_builtin_onemin_reasoned_patch_review(
            tool_runtime=self._tool_runtime,
            register_handler=register_handler,
            onemin_adapter=self._adapter,
        )

    def register_image_generate(self, register_handler: Callable[[str, ToolExecutionHandler], None]) -> None:
        register_builtin_onemin_image_generate(
            tool_runtime=self._tool_runtime,
            register_handler=register_handler,
            onemin_adapter=self._adapter,
        )

    def register_media_transform(self, register_handler: Callable[[str, ToolExecutionHandler], None]) -> None:
        register_builtin_onemin_media_transform(
            tool_runtime=self._tool_runtime,
            register_handler=register_handler,
            onemin_adapter=self._adapter,
        )
