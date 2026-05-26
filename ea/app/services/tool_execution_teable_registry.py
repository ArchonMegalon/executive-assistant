from __future__ import annotations

from typing import Callable

from app.domain.models import ToolInvocationRequest, ToolInvocationResult
from app.services.tool_execution_teable_adapter import TeableToolAdapter
from app.services.tool_runtime import ToolRuntimeService

ToolExecutionHandler = Callable[[ToolInvocationRequest, object], ToolInvocationResult]


def register_builtin_teable_table_sync(
    *,
    tool_runtime: ToolRuntimeService,
    register_handler: Callable[[str, ToolExecutionHandler], None],
    teable_adapter: TeableToolAdapter,
) -> None:
    tool_name = "provider.teable.table_sync"
    if tool_runtime.get_tool(tool_name) is None:
        tool_runtime.upsert_tool(
            tool_name=tool_name,
            version="v1",
            input_schema_json={
                "type": "object",
                "required": ["projection_scope", "tables_json"],
                "properties": {
                    "projection_scope": {"type": "string"},
                    "person_id": {"type": "string"},
                    "tables_json": {"type": "object"},
                    "table_config_json": {"type": "object"},
                    "base_url": {"type": "string"},
                },
            },
            output_schema_json={
                "type": "object",
                "required": ["projection_scope", "synced_tables", "table_results_json", "created_count", "updated_count"],
            },
            policy_json={"builtin": True, "action_kind": "table.sync"},
            approval_default="none",
            enabled=True,
        )
    register_handler(tool_name, teable_adapter.execute_table_sync)
