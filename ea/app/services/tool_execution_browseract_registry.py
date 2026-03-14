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


def register_builtin_browseract_workflow_spec(
    *,
    tool_runtime: ToolRuntimeService,
    register_handler: Callable[[str, ToolExecutionHandler], None],
    browseract_adapter: BrowserActToolAdapter,
) -> None:
    if tool_runtime.get_tool("browseract.build_workflow_spec") is None:
        tool_runtime.upsert_tool(
            tool_name="browseract.build_workflow_spec",
            version="v1",
            input_schema_json={
                "type": "object",
                "required": ["workflow_name", "purpose", "login_url", "tool_url"],
                "properties": {
                    "workflow_name": {"type": "string"},
                    "purpose": {"type": "string"},
                    "login_url": {"type": "string"},
                    "tool_url": {"type": "string"},
                    "workflow_kind": {"type": "string", "enum": ["prompt_tool", "page_extract"]},
                    "runtime_input_name": {"type": "string"},
                    "prompt_selector": {"type": "string"},
                    "submit_selector": {"type": "string"},
                    "result_selector": {"type": "string"},
                    "wait_selector": {"type": "string"},
                    "title_selector": {"type": "string"},
                    "dismiss_selectors": {"type": "array", "items": {"type": "string"}},
                    "output_dir": {"type": "string"},
                },
            },
            output_schema_json={
                "type": "object",
                "required": ["normalized_text", "structured_output_json", "preview_text", "mime_type", "tool_name", "action_kind"],
            },
            policy_json={"builtin": True, "action_kind": "workflow.spec_build"},
            approval_default="none",
            enabled=True,
    )
    register_handler("browseract.build_workflow_spec", browseract_adapter.execute_build_workflow_spec)


def register_builtin_browseract_workflow_repair(
    *,
    tool_runtime: ToolRuntimeService,
    register_handler: Callable[[str, ToolExecutionHandler], None],
    browseract_adapter: BrowserActToolAdapter,
) -> None:
    if tool_runtime.get_tool("browseract.repair_workflow_spec") is None:
        tool_runtime.upsert_tool(
            tool_name="browseract.repair_workflow_spec",
            version="v1",
            input_schema_json={
                "type": "object",
                "required": ["workflow_name", "purpose", "tool_url", "failure_summary"],
                "properties": {
                    "workflow_name": {"type": "string"},
                    "purpose": {"type": "string"},
                    "login_url": {"type": "string"},
                    "tool_url": {"type": "string"},
                    "failure_summary": {"type": "string"},
                    "failing_step_goals": {"type": "array", "items": {"type": "string"}},
                    "current_workflow_spec_json": {"type": "object"},
                    "prompt_selector": {"type": "string"},
                    "submit_selector": {"type": "string"},
                    "result_selector": {"type": "string"},
                    "output_dir": {"type": "string"},
                },
            },
            output_schema_json={
                "type": "object",
                "required": ["normalized_text", "structured_output_json", "preview_text", "mime_type", "tool_name", "action_kind"],
            },
            policy_json={"builtin": True, "action_kind": "workflow.spec_repair"},
            approval_default="none",
            enabled=True,
        )
    register_handler("browseract.repair_workflow_spec", browseract_adapter.execute_repair_workflow_spec)
