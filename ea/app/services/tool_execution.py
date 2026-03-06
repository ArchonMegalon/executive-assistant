from __future__ import annotations

import uuid
from typing import Callable

from app.domain.models import Artifact, ToolDefinition, ToolInvocationRequest, ToolInvocationResult
from app.repositories.artifacts import ArtifactRepository, InMemoryArtifactRepository
from app.repositories.connector_bindings import InMemoryConnectorBindingRepository
from app.repositories.tool_registry import InMemoryToolRegistryRepository
from app.services.channel_runtime import ChannelRuntimeService
from app.services.tool_runtime import ToolRuntimeService

ToolExecutionHandler = Callable[[ToolInvocationRequest, ToolDefinition], ToolInvocationResult]


class ToolExecutionError(RuntimeError):
    pass


class ToolExecutionService:
    def __init__(
        self,
        *,
        tool_runtime: ToolRuntimeService | None = None,
        artifacts: ArtifactRepository | None = None,
        channel_runtime: ChannelRuntimeService | None = None,
    ) -> None:
        self._artifacts = artifacts or InMemoryArtifactRepository()
        self._channel_runtime = channel_runtime
        self._tool_runtime = tool_runtime or ToolRuntimeService(
            tool_registry=InMemoryToolRegistryRepository(),
            connector_bindings=InMemoryConnectorBindingRepository(),
        )
        self._handlers: dict[str, ToolExecutionHandler] = {}
        self._register_builtin_artifact_repository()
        self._register_builtin_connector_dispatch()

    def register_handler(self, tool_name: str, handler: ToolExecutionHandler) -> None:
        key = str(tool_name or "").strip()
        if not key:
            raise ValueError("tool_name is required")
        self._handlers[key] = handler

    def execute_invocation(self, request: ToolInvocationRequest) -> ToolInvocationResult:
        tool_name = str(request.tool_name or "").strip()
        if not tool_name:
            raise ToolExecutionError("tool_name_required")
        definition = self._tool_runtime.get_tool(tool_name)
        if definition is None:
            raise ToolExecutionError(f"tool_not_registered:{tool_name}")
        if not definition.enabled:
            raise ToolExecutionError(f"tool_disabled:{tool_name}")
        handler = self._handlers.get(tool_name)
        if handler is None:
            raise ToolExecutionError(f"tool_handler_missing:{tool_name}")
        return handler(request, definition)

    def _register_builtin_artifact_repository(self) -> None:
        if self._tool_runtime.get_tool("artifact_repository") is None:
            self._tool_runtime.upsert_tool(
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
        self.register_handler("artifact_repository", self._execute_artifact_repository)

    def _register_builtin_connector_dispatch(self) -> None:
        if self._channel_runtime is None:
            return
        if self._tool_runtime.get_tool("connector.dispatch") is None:
            self._tool_runtime.upsert_tool(
                tool_name="connector.dispatch",
                version="v1",
                input_schema_json={
                    "type": "object",
                    "required": ["channel", "recipient", "content"],
                    "properties": {
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
                policy_json={"builtin": True, "action_kind": "delivery.send"},
                allowed_channels=("email", "slack", "telegram"),
                approval_default="manager",
                enabled=True,
            )
        self.register_handler("connector.dispatch", self._execute_connector_dispatch)

    def _execute_artifact_repository(
        self,
        request: ToolInvocationRequest,
        definition: ToolDefinition,
    ) -> ToolInvocationResult:
        payload = dict(request.payload_json or {})
        source_text = str(payload.get("source_text") or "").strip()
        artifact_kind = str(payload.get("expected_artifact") or "rewrite_note")
        plan_id = str(payload.get("plan_id") or "")
        plan_step_key = str(payload.get("plan_step_key") or "")
        artifact = Artifact(
            artifact_id=str(uuid.uuid4()),
            kind=artifact_kind,
            content=source_text,
            execution_session_id=request.session_id,
        )
        self._artifacts.save(artifact)
        return ToolInvocationResult(
            tool_name=definition.tool_name,
            action_kind=str(request.action_kind or "artifact.save") or "artifact.save",
            target_ref=artifact.artifact_id,
            output_json={
                "artifact_id": artifact.artifact_id,
                "artifact_kind": artifact.kind,
                "content_length": len(source_text),
                "plan_id": plan_id,
                "plan_step_key": plan_step_key,
                "tool_name": definition.tool_name,
                "action_kind": str(request.action_kind or "artifact.save") or "artifact.save",
            },
            receipt_json={
                "artifact_kind": artifact.kind,
                "content_length": len(source_text),
                "handler_key": definition.tool_name,
                "invocation_contract": "tool.v1",
                "plan_id": plan_id,
                "plan_step_key": plan_step_key,
                "tool_version": definition.version,
            },
            artifacts=(artifact,),
        )

    def _execute_connector_dispatch(
        self,
        request: ToolInvocationRequest,
        definition: ToolDefinition,
    ) -> ToolInvocationResult:
        if self._channel_runtime is None:
            raise ToolExecutionError("channel_runtime_unavailable:connector.dispatch")
        payload = dict(request.payload_json or {})
        binding_id = str(payload.get("binding_id") or "").strip()
        if not binding_id:
            raise ToolExecutionError("connector_binding_required:connector.dispatch")
        binding = self._tool_runtime.get_connector_binding(binding_id)
        if binding is None:
            raise ToolExecutionError(f"connector_binding_not_found:{binding_id}")
        if str(binding.status or "").strip().lower() != "enabled":
            raise ToolExecutionError(f"connector_binding_disabled:{binding_id}")
        principal_id = str((request.context_json or {}).get("principal_id") or "").strip()
        if principal_id and binding.principal_id != principal_id:
            raise ToolExecutionError("principal_scope_mismatch")
        channel = str(payload.get("channel") or "").strip()
        recipient = str(payload.get("recipient") or "").strip()
        content = str(payload.get("content") or "")
        metadata = dict(payload.get("metadata") or {})
        idempotency_key = str(payload.get("idempotency_key") or "").strip()
        delivery = self._channel_runtime.queue_delivery(
            channel=channel,
            recipient=recipient,
            content=content,
            metadata=metadata,
            idempotency_key=idempotency_key,
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
