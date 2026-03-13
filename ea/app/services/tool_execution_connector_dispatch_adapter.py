from __future__ import annotations

from app.domain.models import ToolDefinition, ToolInvocationRequest, ToolInvocationResult
from app.services.channel_runtime import ChannelRuntimeService
from app.services.tool_execution_common import (
    CONNECTOR_CHANNEL_SCOPE_REQUIREMENTS,
    CONNECTOR_DISPATCH_ALLOWED_CHANNELS,
    ToolExecutionError,
)
from app.services.tool_runtime import ToolRuntimeService


class ConnectorDispatchToolAdapter:
    def __init__(
        self,
        *,
        tool_runtime: ToolRuntimeService,
        channel_runtime: ChannelRuntimeService | None,
    ) -> None:
        self._tool_runtime = tool_runtime
        self.channel_runtime = channel_runtime

    def execute(self, request: ToolInvocationRequest, definition: ToolDefinition) -> ToolInvocationResult:
        if self.channel_runtime is None:
            raise ToolExecutionError("channel_runtime_unavailable:connector.dispatch")
        payload = dict(request.payload_json or {})
        channel = str(payload.get("channel") or "").strip()
        normalized_channel = channel.lower()
        allowed_channels = self._normalized_allowed_channels(definition)
        if not allowed_channels:
            allowed_channels = tuple(sorted(CONNECTOR_DISPATCH_ALLOWED_CHANNELS))
        if not normalized_channel:
            raise ToolExecutionError("connector_dispatch_channel_required")
        if allowed_channels and normalized_channel not in allowed_channels:
            raise ToolExecutionError(
                f"connector_dispatch_channel_not_allowed:{normalized_channel}:{','.join(allowed_channels)}"
            )
        _, binding = self.resolve_connector_binding(
            request=request,
            payload=payload,
            required_input_error="connector_binding_required:connector.dispatch",
            required_scopes=self._channel_dispatch_scopes(normalized_channel),
        )
        delivery = self.channel_runtime.queue_delivery(
            channel=normalized_channel,
            recipient=str(payload.get("recipient") or "").strip(),
            content=str(payload.get("content") or ""),
            metadata=dict(payload.get("metadata") or {}),
            idempotency_key=str(payload.get("idempotency_key") or "").strip(),
        )
        action_kind = str(request.action_kind or "delivery.send") or "delivery.send"
        return ToolInvocationResult(
            tool_name=definition.tool_name,
            action_kind=action_kind,
            target_ref=delivery.delivery_id,
            output_json={
                "delivery_id": delivery.delivery_id,
                "status": delivery.status,
                "channel": delivery.channel,
                "recipient": delivery.recipient,
                "binding_id": binding.binding_id,
                "connector_name": binding.connector_name,
                "principal_id": binding.principal_id,
                "idempotency_key": delivery.idempotency_key,
                "tool_name": definition.tool_name,
                "action_kind": action_kind,
            },
            receipt_json={
                "binding_id": binding.binding_id,
                "channel": delivery.channel,
                "connector_name": binding.connector_name,
                "delivery_id": delivery.delivery_id,
                "handler_key": definition.tool_name,
                "idempotency_key": delivery.idempotency_key,
                "invocation_contract": "tool.v1",
                "principal_id": binding.principal_id,
                "status": delivery.status,
                "tool_version": definition.version,
            },
        )

    def resolve_connector_binding(
        self,
        request: ToolInvocationRequest,
        payload: dict[str, object],
        *,
        required_connector_name: str | None = None,
        required_input_error: str = "connector_binding_required:connector.dispatch",
        required_scopes: tuple[str, ...] | None = None,
    ):
        principal_id = self._resolve_connector_binding_principal(request, payload)
        binding_id = str(payload.get("binding_id") or "").strip()
        if not binding_id:
            raise ToolExecutionError(required_input_error)
        binding = self._tool_runtime.get_connector_binding(binding_id)
        if binding is None:
            raise ToolExecutionError(f"connector_binding_not_found:{binding_id}")
        if str(binding.status or "").strip().lower() != "enabled":
            raise ToolExecutionError(f"connector_binding_disabled:{binding_id}")
        if str(binding.principal_id or "").strip() != principal_id:
            raise ToolExecutionError("principal_scope_mismatch")
        if required_connector_name:
            expected = str(required_connector_name or "").strip().lower()
            if str(binding.connector_name or "").strip().lower() != expected:
                raise ToolExecutionError(f"connector_binding_connector_mismatch:{binding_id}")
        requested_scopes = self._normalized_connector_scopes(required_scopes or ())
        if requested_scopes:
            configured_scopes = self.normalised_scopes(tuple(str(value or "").strip() for value in (dict(binding.scope_json or {}).get("scopes") or ())))
            if not set(requested_scopes).intersection(configured_scopes):
                raise ToolExecutionError(
                    f"connector_binding_scope_mismatch:{binding_id}:{','.join(requested_scopes)}"
                )
        return principal_id, binding

    def _resolve_connector_binding_principal(self, request: ToolInvocationRequest, payload: dict[str, object]) -> str:
        request_principal_id = str((request.context_json or {}).get("principal_id") or "").strip()
        if not request_principal_id:
            raise ToolExecutionError("principal_id_required")
        supplied_principal_id = str(payload.get("principal_id") or "").strip()
        if not supplied_principal_id:
            return request_principal_id
        if supplied_principal_id != request_principal_id:
            raise ToolExecutionError("principal_scope_mismatch")
        return request_principal_id

    def _normalized_connector_scopes(self, scopes: tuple[str, ...] | list[str] | set[str]) -> tuple[str, ...]:
        normalized = {str(scope or "").strip().lower() for scope in scopes}
        return tuple(sorted(value for value in normalized if value))

    def _channel_dispatch_scopes(self, channel: str) -> tuple[str, ...]:
        normalized_channel = str(channel or "").strip().lower()
        return self.normalised_scopes(
            CONNECTOR_CHANNEL_SCOPE_REQUIREMENTS.get(normalized_channel, (normalized_channel + ".send",))
        )

    def normalised_scopes(self, scopes: tuple[str, ...] | list[str] | set[str]) -> tuple[str, ...]:
        normalized: set[str] = set()
        for scope in scopes:
            value = str(scope or "").strip().lower()
            if not value:
                continue
            normalized.add(value)
            if value.startswith("channel:"):
                normalized.add(value.split(":", 1)[-1])
            if value == "mail.send":
                normalized.update(("email", "email.send"))
            if value == "chat.post":
                normalized.update(("slack", "chat.write"))
            if value == "telegram.send":
                normalized.add("telegram")
            if value.endswith(".send"):
                normalized.add(value.rsplit(".", 1)[0])
        return tuple(sorted(normalized))

    def _normalized_allowed_channels(self, definition: ToolDefinition) -> tuple[str, ...]:
        values = {str(raw or "").strip().lower() for raw in definition.allowed_channels}
        return tuple(sorted(value for value in values if value))
