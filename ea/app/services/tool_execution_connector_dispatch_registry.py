from __future__ import annotations

from typing import Callable

from app.domain.models import ToolInvocationRequest, ToolInvocationResult
from app.services.tool_execution_common import (
    CONNECTOR_DISPATCH_ALLOWED_CHANNELS,
    CONNECTOR_DISPATCH_IDEMPOTENCY_POLICY,
    CONNECTOR_DISPATCH_REQUIRED_INPUT_FIELDS,
)
from app.services.tool_execution_connector_dispatch_adapter import ConnectorDispatchToolAdapter
from app.services.tool_runtime import ToolRuntimeService

ToolExecutionHandler = Callable[[ToolInvocationRequest, object], ToolInvocationResult]


def register_builtin_connector_dispatch(
    *,
    tool_runtime: ToolRuntimeService,
    register_handler: Callable[[str, ToolExecutionHandler], None],
    connector_dispatch_adapter: ConnectorDispatchToolAdapter,
) -> None:
    if connector_dispatch_adapter.channel_runtime is None:
        return
    if tool_runtime.get_tool("connector.dispatch") is None:
        tool_runtime.upsert_tool(
            tool_name="connector.dispatch",
            version="v1",
            input_schema_json={
                "type": "object",
                "required": list(CONNECTOR_DISPATCH_REQUIRED_INPUT_FIELDS),
                "properties": {
                    "binding_id": {"type": "string"},
                    "channel": {"type": "string"},
                    "recipient": {"type": "string"},
                    "content": {"type": "string"},
                    "metadata": {"type": "object"},
                    "idempotency_key": {"type": "string"},
                },
            },
            output_schema_json={
                "type": "object",
                "required": ["delivery_id", "status", "tool_name", "action_kind"],
            },
            policy_json={
                "builtin": True,
                "action_kind": "delivery.send",
                "idempotency_key_policy": CONNECTOR_DISPATCH_IDEMPOTENCY_POLICY,
            },
            allowed_channels=CONNECTOR_DISPATCH_ALLOWED_CHANNELS,
            approval_default="manager",
            enabled=True,
        )
    register_handler("connector.dispatch", connector_dispatch_adapter.execute)
