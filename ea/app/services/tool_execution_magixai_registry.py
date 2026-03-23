from __future__ import annotations

from typing import Callable

from app.domain.models import ToolInvocationRequest, ToolInvocationResult
from app.services.tool_execution_magixai_adapter import MagixaiToolAdapter
from app.services.tool_runtime import ToolRuntimeService

ToolExecutionHandler = Callable[[ToolInvocationRequest, object], ToolInvocationResult]


def register_builtin_magixai_structured_generate(
    *,
    tool_runtime: ToolRuntimeService,
    register_handler: Callable[[str, ToolExecutionHandler], None],
    magixai_adapter: MagixaiToolAdapter,
) -> None:
    tool_name = "provider.magixai.structured_generate"
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
                    "lane": {"type": "string"},
                    "brain_profile": {"type": "string"},
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
    register_handler(tool_name, magixai_adapter.execute_structured_generate)
