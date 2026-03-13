from __future__ import annotations

import json
import subprocess

from app.domain.models import ToolInvocationRequest
from app.repositories.artifacts import InMemoryArtifactRepository
from app.repositories.connector_bindings import InMemoryConnectorBindingRepository
from app.services.tool_execution import ToolExecutionService
from app.services.tool_runtime import ToolRuntimeService
from app.repositories.tool_registry import InMemoryToolRegistryRepository


def test_gemini_vortex_tool_executes_and_returns_structured_output(monkeypatch) -> None:
    def fake_run(*args, **kwargs):
        return subprocess.CompletedProcess(
            args=args[0],
            returncode=0,
            stdout=json.dumps(
                {
                    "response": "{\"ok\": true, \"title\": \"Chummer6\"}",
                    "stats": {
                        "models": {
                            "gemini-3-flash-preview": {
                                "tokens": {"input": 123, "candidates": 45}
                            }
                        }
                    },
                }
            ),
            stderr="",
        )

    monkeypatch.setattr(
        "app.services.tool_execution_gemini_vortex_adapter.subprocess.run",
        fake_run,
    )

    tool_runtime = ToolRuntimeService(
        tool_registry=InMemoryToolRegistryRepository(),
        connector_bindings=InMemoryConnectorBindingRepository(),
    )
    service = ToolExecutionService(
        tool_runtime=tool_runtime,
        artifacts=InMemoryArtifactRepository(),
    )

    result = service.execute_invocation(
        ToolInvocationRequest(
            session_id="session-1",
            step_id="step-1",
            tool_name="provider.gemini_vortex.structured_generate",
            action_kind="content.generate",
            payload_json={
                "normalized_text": "Return JSON only.",
                "goal": "produce structured guide JSON",
            },
            context_json={"principal_id": "exec-1"},
        )
    )

    assert result.tool_name == "provider.gemini_vortex.structured_generate"
    assert result.model_name == "gemini-3-flash-preview"
    assert result.tokens_in == 123
    assert result.tokens_out == 45
    assert result.output_json["mime_type"] == "application/json"
    assert result.output_json["structured_output_json"]["ok"] is True
    assert result.output_json["structured_output_json"]["title"] == "Chummer6"
