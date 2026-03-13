from __future__ import annotations

from typing import Callable

from app.domain.models import ToolInvocationRequest, ToolInvocationResult
from app.services.tool_execution_gemini_vortex_adapter import GeminiVortexToolAdapter
from app.services.tool_runtime import ToolRuntimeService

ToolExecutionHandler = Callable[[ToolInvocationRequest, object], ToolInvocationResult]


def register_builtin_gemini_vortex_structured_generate(
    *,
    tool_runtime: ToolRuntimeService,
    register_handler: Callable[[str, ToolExecutionHandler], None],
    gemini_vortex_adapter: GeminiVortexToolAdapter,
) -> None:
    tool_name = "provider.gemini_vortex.structured_generate"
    if tool_runtime.get_tool(tool_name) is None:
        tool_runtime.upsert_tool(
            tool_name=tool_name,
            version="v1",
            input_schema_json={
                "type": "object",
                "required": ["normalized_text"],
                "properties": {
                    "source_text": {"type": "string"},
                    "normalized_text": {"type": "string"},
                    "goal": {"type": "string"},
                    "generation_instruction": {"type": "string"},
                    "response_schema_json": {"type": "object"},
                    "context_pack": {"type": "object"},
                    "model": {"type": "string"},
                },
            },
            output_schema_json={
                "type": "object",
                "required": ["normalized_text", "structured_output_json", "preview_text", "mime_type", "tool_name", "action_kind"],
            },
            policy_json={"builtin": True, "action_kind": "content.generate"},
            approval_default="none",
            enabled=True,
        )
    register_handler(tool_name, gemini_vortex_adapter.execute)
