from __future__ import annotations

from typing import Callable

from app.domain.models import ToolInvocationRequest, ToolInvocationResult
from app.services.tool_execution_onemin_adapter import OneminToolAdapter
from app.services.tool_runtime import ToolRuntimeService

ToolExecutionHandler = Callable[[ToolInvocationRequest, object], ToolInvocationResult]


def register_builtin_onemin_code_generate(
    *,
    tool_runtime: ToolRuntimeService,
    register_handler: Callable[[str, ToolExecutionHandler], None],
    onemin_adapter: OneminToolAdapter,
) -> None:
    tool_name = "provider.onemin.code_generate"
    if tool_runtime.get_tool(tool_name) is None:
        tool_runtime.upsert_tool(
            tool_name=tool_name,
            version="v1",
            input_schema_json={
                "type": "object",
                "properties": {
                    "prompt": {"type": "string"},
                    "source_text": {"type": "string"},
                    "normalized_text": {"type": "string"},
                    "instructions": {"type": "string"},
                    "goal": {"type": "string"},
                    "context_pack": {"type": "object"},
                    "model": {"type": "string"},
                },
            },
            output_schema_json={
                "type": "object",
                "required": ["normalized_text", "preview_text", "mime_type", "tool_name", "action_kind"],
            },
            policy_json={"builtin": True, "action_kind": "code.generate"},
            approval_default="none",
            enabled=True,
        )
    register_handler(tool_name, onemin_adapter.execute_code_generate)


def register_builtin_onemin_reasoned_patch_review(
    *,
    tool_runtime: ToolRuntimeService,
    register_handler: Callable[[str, ToolExecutionHandler], None],
    onemin_adapter: OneminToolAdapter,
) -> None:
    tool_name = "provider.onemin.reasoned_patch_review"
    if tool_runtime.get_tool(tool_name) is None:
        tool_runtime.upsert_tool(
            tool_name=tool_name,
            version="v1",
            input_schema_json={
                "type": "object",
                "properties": {
                    "prompt": {"type": "string"},
                    "source_text": {"type": "string"},
                    "normalized_text": {"type": "string"},
                    "diff_text": {"type": "string"},
                    "instructions": {"type": "string"},
                    "goal": {"type": "string"},
                    "review_focus": {"type": "string"},
                    "model": {"type": "string"},
                },
            },
            output_schema_json={
                "type": "object",
                "required": ["normalized_text", "preview_text", "mime_type", "tool_name", "action_kind"],
            },
            policy_json={"builtin": True, "action_kind": "code.review"},
            approval_default="none",
            enabled=True,
        )
    register_handler(tool_name, onemin_adapter.execute_reasoned_patch_review)


def register_builtin_onemin_image_generate(
    *,
    tool_runtime: ToolRuntimeService,
    register_handler: Callable[[str, ToolExecutionHandler], None],
    onemin_adapter: OneminToolAdapter,
) -> None:
    tool_name = "provider.onemin.image_generate"
    if tool_runtime.get_tool(tool_name) is None:
        tool_runtime.upsert_tool(
            tool_name=tool_name,
            version="v1",
            input_schema_json={
                "type": "object",
                "required": ["prompt"],
                "properties": {
                    "prompt": {"type": "string"},
                    "model": {"type": "string"},
                    "n": {"type": "integer"},
                    "size": {"type": "string"},
                    "aspect_ratio": {"type": "string"},
                    "quality": {"type": "string"},
                    "output_format": {"type": "string"},
                },
            },
            output_schema_json={
                "type": "object",
                "required": ["normalized_text", "preview_text", "mime_type", "tool_name", "action_kind"],
            },
            policy_json={"builtin": True, "action_kind": "image.generate"},
            approval_default="none",
            enabled=True,
        )
    register_handler(tool_name, onemin_adapter.execute_image_generate)


def register_builtin_onemin_media_transform(
    *,
    tool_runtime: ToolRuntimeService,
    register_handler: Callable[[str, ToolExecutionHandler], None],
    onemin_adapter: OneminToolAdapter,
) -> None:
    tool_name = "provider.onemin.media_transform"
    if tool_runtime.get_tool(tool_name) is None:
        tool_runtime.upsert_tool(
            tool_name=tool_name,
            version="v1",
            input_schema_json={
                "type": "object",
                "required": ["feature_type", "prompt"],
                "properties": {
                    "feature_type": {"type": "string"},
                    "prompt": {"type": "string"},
                    "source_text": {"type": "string"},
                    "prompt_object": {"type": "object"},
                    "model": {"type": "string"},
                },
            },
            output_schema_json={
                "type": "object",
                "required": ["normalized_text", "preview_text", "mime_type", "tool_name", "action_kind"],
            },
            policy_json={"builtin": True, "action_kind": "media.transform"},
            approval_default="none",
            enabled=True,
        )
    register_handler(tool_name, onemin_adapter.execute_media_transform)
