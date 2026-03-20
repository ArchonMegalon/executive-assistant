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
                    "workflow_spec_json": {"type": "object"},
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


def register_builtin_browseract_chatplayground_audit(
    *,
    tool_runtime: ToolRuntimeService,
    register_handler: Callable[[str, ToolExecutionHandler], None],
    browseract_adapter: BrowserActToolAdapter,
) -> None:
    if tool_runtime.get_tool("browseract.chatplayground_audit") is None:
        tool_runtime.upsert_tool(
            tool_name="browseract.chatplayground_audit",
            version="v1",
            input_schema_json={
                "type": "object",
                "required": ["roles", "prompt", "run_url"],
                "properties": {
                    "prompt": {"type": "string"},
                    "run_url": {"type": "string"},
                    "roles": {"type": "array", "items": {"type": "string"}},
                    "focus": {"type": "string"},
                    "max_chars": {"type": "integer"},
                    "scope_json": {"type": "object"},
                },
            },
            output_schema_json={
                "type": "object",
                "required": ["tool_name", "action_kind", "normalized_text", "preview_text", "mime_type", "structured_output_json"],
            },
            policy_json={"builtin": True, "action_kind": "chatplayground.audit"},
            approval_default="none",
            enabled=True,
        )
    register_handler("browseract.chatplayground_audit", browseract_adapter.execute_chatplayground_audit)


def register_builtin_browseract_gemini_web_generate(
    *,
    tool_runtime: ToolRuntimeService,
    register_handler: Callable[[str, ToolExecutionHandler], None],
    browseract_adapter: BrowserActToolAdapter,
) -> None:
    if tool_runtime.get_tool("browseract.gemini_web_generate") is None:
        tool_runtime.upsert_tool(
            tool_name="browseract.gemini_web_generate",
            version="v1",
            input_schema_json={
                "type": "object",
                "required": ["binding_id", "packet"],
                "properties": {
                    "binding_id": {"type": "string"},
                    "packet": {"type": "object"},
                    "mode": {"type": "string"},
                    "deep_think": {"type": "boolean"},
                    "timeout_seconds": {"type": "integer"},
                    "run_url": {"type": "string"},
                },
            },
            output_schema_json={
                "type": "object",
                "required": ["text", "tool_name", "action_kind", "provider_backend"],
            },
            policy_json={"builtin": True, "action_kind": "content.generate"},
            approval_default="none",
            enabled=True,
    )
    register_handler("browseract.gemini_web_generate", browseract_adapter.execute_gemini_web_generate)


def register_builtin_browseract_onemin_billing_usage(
    *,
    tool_runtime: ToolRuntimeService,
    register_handler: Callable[[str, ToolExecutionHandler], None],
    browseract_adapter: BrowserActToolAdapter,
) -> None:
    if tool_runtime.get_tool("browseract.onemin_billing_usage") is None:
        tool_runtime.upsert_tool(
            tool_name="browseract.onemin_billing_usage",
            version="v1",
            input_schema_json={
                "type": "object",
                "required": ["binding_id"],
                "properties": {
                    "binding_id": {"type": "string"},
                    "run_url": {"type": "string"},
                    "workflow_id": {"type": "string"},
                    "timeout_seconds": {"type": "integer"},
                    "account_label": {"type": "string"},
                    "page_url": {"type": "string"},
                    "capture_raw_text": {"type": "boolean"},
                },
            },
            output_schema_json={
                "type": "object",
                "required": [
                    "tool_name",
                    "action_kind",
                    "provider_backend",
                    "remaining_credits",
                    "next_topup_at",
                    "basis",
                ],
                "properties": {
                    "remaining_credits": {"type": ["number", "null"]},
                    "max_credits": {"type": ["number", "null"]},
                    "used_percent": {"type": ["number", "null"]},
                    "next_topup_at": {"type": ["string", "null"]},
                    "cycle_start_at": {"type": ["string", "null"]},
                    "cycle_end_at": {"type": ["string", "null"]},
                    "topup_amount": {"type": ["number", "null"]},
                    "rollover_enabled": {"type": ["boolean", "null"]},
                    "plan_name": {"type": ["string", "null"]},
                    "billing_cycle": {"type": ["string", "null"]},
                    "subscription_status": {"type": ["string", "null"]},
                    "daily_bonus_cta_text": {"type": ["string", "null"]},
                    "daily_bonus_available": {"type": ["boolean", "null"]},
                    "daily_bonus_credits": {"type": ["number", "null"]},
                    "usage_history_count": {"type": ["integer", "null"]},
                    "latest_usage_at": {"type": ["string", "null"]},
                    "earliest_usage_at": {"type": ["string", "null"]},
                    "latest_usage_credit": {"type": ["number", "null"]},
                    "observed_usage_credits_total": {"type": ["number", "null"]},
                    "observed_usage_window_hours": {"type": ["number", "null"]},
                    "observed_usage_burn_credits_per_hour": {"type": ["number", "null"]},
                    "source_url": {"type": "string"},
                    "basis": {"type": "string"},
                    "structured_output_json": {"type": "object"},
                },
            },
            policy_json={"builtin": True, "action_kind": "billing.inspect"},
            approval_default="none",
            enabled=True,
        )
    register_handler("browseract.onemin_billing_usage", browseract_adapter.execute_onemin_billing_usage)


def register_builtin_browseract_onemin_member_reconciliation(
    *,
    tool_runtime: ToolRuntimeService,
    register_handler: Callable[[str, ToolExecutionHandler], None],
    browseract_adapter: BrowserActToolAdapter,
) -> None:
    if tool_runtime.get_tool("browseract.onemin_member_reconciliation") is None:
        tool_runtime.upsert_tool(
            tool_name="browseract.onemin_member_reconciliation",
            version="v1",
            input_schema_json={
                "type": "object",
                "required": ["binding_id"],
                "properties": {
                    "binding_id": {"type": "string"},
                    "run_url": {"type": "string"},
                    "workflow_id": {"type": "string"},
                    "timeout_seconds": {"type": "integer"},
                    "account_label": {"type": "string"},
                    "page_url": {"type": "string"},
                    "capture_raw_text": {"type": "boolean"},
                },
            },
            output_schema_json={
                "type": "object",
                "required": [
                    "tool_name",
                    "action_kind",
                    "provider_backend",
                    "member_count",
                    "basis",
                ],
                "properties": {
                    "member_count": {"type": "integer"},
                    "matched_owner_slots": {"type": "integer"},
                    "missing_owner_emails": {"type": "array", "items": {"type": "string"}},
                    "owner_mismatches": {"type": "array", "items": {"type": "object"}},
                    "members_json": {"type": "array", "items": {"type": "object"}},
                    "source_url": {"type": "string"},
                    "basis": {"type": "string"},
                    "structured_output_json": {"type": "object"},
                },
            },
            policy_json={"builtin": True, "action_kind": "billing.reconcile_members"},
            approval_default="none",
            enabled=True,
        )
    register_handler(
        "browseract.onemin_member_reconciliation",
        browseract_adapter.execute_onemin_member_reconciliation,
    )
