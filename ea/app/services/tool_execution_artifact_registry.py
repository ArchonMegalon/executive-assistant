from __future__ import annotations

from typing import Callable

from app.domain.models import ToolInvocationRequest, ToolInvocationResult
from app.services.tool_execution_artifact_adapter import ArtifactRepositoryToolAdapter
from app.services.tool_runtime import ToolRuntimeService

ToolExecutionHandler = Callable[[ToolInvocationRequest, object], ToolInvocationResult]


def register_builtin_artifact_repository(
    *,
    tool_runtime: ToolRuntimeService,
    register_handler: Callable[[str, ToolExecutionHandler], None],
    artifact_adapter: ArtifactRepositoryToolAdapter,
) -> None:
    if tool_runtime.get_tool("artifact_repository") is None:
        tool_runtime.upsert_tool(
            tool_name="artifact_repository",
            version="v1",
            input_schema_json={
                "type": "object",
                "required": ["source_text"],
                "properties": {
                    "source_text": {"type": "string"},
                    "expected_artifact": {"type": "string"},
                    "plan_id": {"type": "string"},
                    "plan_step_key": {"type": "string"},
                },
            },
            output_schema_json={
                "type": "object",
                "required": ["artifact_id", "artifact_kind", "tool_name", "action_kind"],
            },
            policy_json={"builtin": True, "action_kind": "artifact.save"},
            approval_default="none",
            enabled=True,
        )
    register_handler("artifact_repository", artifact_adapter.execute)
