from __future__ import annotations

import pytest

from app.domain.models import ToolInvocationRequest
from app.repositories.artifacts import InMemoryArtifactRepository
from app.repositories.connector_bindings import InMemoryConnectorBindingRepository
from app.repositories.tool_registry import InMemoryToolRegistryRepository
from app.services.tool_execution import ToolExecutionError, ToolExecutionService
from app.services.tool_runtime import ToolRuntimeService


def test_tool_execution_service_executes_builtin_artifact_repository_handler() -> None:
    artifacts = InMemoryArtifactRepository()
    tool_runtime = ToolRuntimeService(
        tool_registry=InMemoryToolRegistryRepository(),
        connector_bindings=InMemoryConnectorBindingRepository(),
    )
    service = ToolExecutionService(tool_runtime=tool_runtime, artifacts=artifacts)

    result = service.execute_invocation(
        ToolInvocationRequest(
            session_id="session-1",
            step_id="step-1",
            tool_name="artifact_repository",
            action_kind="artifact.save",
            payload_json={
                "source_text": "draft note",
                "expected_artifact": "rewrite_note",
                "plan_id": "plan-1",
                "plan_step_key": "step_artifact_save",
            },
        )
    )

    assert result.tool_name == "artifact_repository"
    assert result.action_kind == "artifact.save"
    assert result.receipt_json["handler_key"] == "artifact_repository"
    assert result.receipt_json["invocation_contract"] == "tool.v1"
    assert result.output_json["artifact_kind"] == "rewrite_note"
    assert len(result.artifacts) == 1
    saved = artifacts.get(result.target_ref)
    assert saved is not None
    assert saved.content == "draft note"


def test_tool_execution_service_rejects_disabled_tools() -> None:
    tool_runtime = ToolRuntimeService(
        tool_registry=InMemoryToolRegistryRepository(),
        connector_bindings=InMemoryConnectorBindingRepository(),
    )
    service = ToolExecutionService(
        tool_runtime=tool_runtime,
        artifacts=InMemoryArtifactRepository(),
    )
    tool_runtime.upsert_tool(
        tool_name="artifact_repository",
        version="v2",
        enabled=False,
    )

    with pytest.raises(ToolExecutionError, match="tool_disabled:artifact_repository"):
        service.execute_invocation(
            ToolInvocationRequest(
                session_id="session-1",
                step_id="step-1",
                tool_name="artifact_repository",
                action_kind="artifact.save",
                payload_json={"source_text": "draft note"},
            )
        )
