from __future__ import annotations

from typing import Callable

from app.domain.models import ToolInvocationRequest, ToolInvocationResult
from app.services.tool_execution_comfyui_adapter import ComfyUIToolAdapter
from app.services.tool_runtime import ToolRuntimeService

ToolExecutionHandler = Callable[[ToolInvocationRequest, object], ToolInvocationResult]


def register_builtin_comfyui_image_generate(
    *,
    tool_runtime: ToolRuntimeService,
    register_handler: Callable[[str, ToolExecutionHandler], None],
    comfyui_adapter: ComfyUIToolAdapter,
) -> None:
    tool_name = "provider.comfyui.image_generate"
    if tool_runtime.get_tool(tool_name) is None:
        tool_runtime.upsert_tool(
            tool_name=tool_name,
            version="v1",
            input_schema_json={
                "type": "object",
                "required": ["prompt"],
                "properties": {
                    "prompt": {"type": "string"},
                    "width": {"type": "integer"},
                    "height": {"type": "integer"},
                    "steps": {"type": "integer"},
                },
            },
            output_schema_json={
                "type": "object",
                "required": ["image_path", "filename", "mime_type", "tool_name", "action_kind"],
            },
            policy_json={"builtin": True, "action_kind": "image.generate"},
            approval_default="none",
            enabled=True,
        )
    register_handler(tool_name, comfyui_adapter.execute_image_generate)
