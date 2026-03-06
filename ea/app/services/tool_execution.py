from __future__ import annotations

import uuid
from typing import Callable

from app.domain.models import Artifact, ToolDefinition, ToolInvocationRequest, ToolInvocationResult
from app.repositories.artifacts import ArtifactRepository, InMemoryArtifactRepository
from app.repositories.connector_bindings import InMemoryConnectorBindingRepository
from app.repositories.tool_registry import InMemoryToolRegistryRepository
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
    ) -> None:
        self._artifacts = artifacts or InMemoryArtifactRepository()
        self._tool_runtime = tool_runtime or ToolRuntimeService(
            tool_registry=InMemoryToolRegistryRepository(),
            connector_bindings=InMemoryConnectorBindingRepository(),
        )
        self._handlers: dict[str, ToolExecutionHandler] = {}
        self._register_builtin_artifact_repository()

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
