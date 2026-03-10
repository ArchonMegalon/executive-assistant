from __future__ import annotations

from typing import Callable

from app.domain.models import ToolInvocationRequest, ToolInvocationResult
from app.services.tool_execution_browseract_adapter import BrowserActToolAdapter
from app.services.tool_runtime import ToolRuntimeService

ToolExecutionHandler = Callable[[ToolInvocationRequest, object], ToolInvocationResult]


def register_builtin_browseract_extract(
    *,
    tool_runtime: ToolRuntimeService,
    register_handler: Callable[[str, ToolExecutionHandler], None],
    browseract_adapter: BrowserActToolAdapter,
) -> None:
    if tool_runtime.get_tool("browseract.extract_account_facts") is None:
        tool_runtime.upsert_tool(
            tool_name="browseract.extract_account_facts",
            version="v1",
            input_schema_json={
                "type": "object",
                "required": ["binding_id", "service_name"],
                "properties": {
                    "binding_id": {"type": "string"},
                    "service_name": {"type": "string"},
                    "requested_fields": {"type": "array", "items": {"type": "string"}},
                    "run_url": {"type": "string"},
                    "instructions": {"type": "string"},
                    "account_hints_json": {"type": "object"},
                },
            },
            output_schema_json={
                "type": "object",
                "required": ["service_name", "facts_json", "missing_fields", "tool_name", "action_kind"],
            },
            policy_json={"builtin": True, "action_kind": "account.extract"},
            approval_default="none",
            enabled=True,
        )
    register_handler("browseract.extract_account_facts", browseract_adapter.execute_extract)


def register_builtin_browseract_inventory(
    *,
    tool_runtime: ToolRuntimeService,
    register_handler: Callable[[str, ToolExecutionHandler], None],
    browseract_adapter: BrowserActToolAdapter,
) -> None:
    if tool_runtime.get_tool("browseract.extract_account_inventory") is None:
        tool_runtime.upsert_tool(
            tool_name="browseract.extract_account_inventory",
            version="v1",
            input_schema_json={
                "type": "object",
                "required": ["binding_id"],
                "properties": {
                    "binding_id": {"type": "string"},
                    "service_names": {"type": "array", "items": {"type": "string"}},
                    "requested_fields": {"type": "array", "items": {"type": "string"}},
                    "run_url": {"type": "string"},
                    "instructions": {"type": "string"},
                    "account_hints_json": {"type": "object"},
                },
            },
            output_schema_json={
                "type": "object",
                "required": ["service_names", "services_json", "tool_name", "action_kind"],
            },
            policy_json={"builtin": True, "action_kind": "account.extract_inventory"},
            approval_default="none",
            enabled=True,
        )
    register_handler("browseract.extract_account_inventory", browseract_adapter.execute_inventory)
