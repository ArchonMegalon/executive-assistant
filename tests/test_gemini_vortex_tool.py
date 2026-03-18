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
                            "gemini-2.5-flash": {
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
    assert result.model_name == "gemini-2.5-flash"
    assert result.tokens_in == 123
    assert result.tokens_out == 45
    assert result.output_json["mime_type"] == "application/json"
    assert result.output_json["provider_key_slot"] == "default"
    assert result.output_json["provider_account_name"] == "EA_GEMINI_VORTEX_DEFAULT_AUTH"
    assert result.output_json["lease_holder"] == "exec-1"
    assert result.output_json["structured_output_json"]["ok"] is True
    assert result.output_json["structured_output_json"]["title"] == "Chummer6"


def test_gemini_vortex_tool_falls_back_to_vertex_key_slot(monkeypatch, tmp_path) -> None:
    calls: list[dict[str, str]] = []

    def fake_run(*args, **kwargs):
        env = dict(kwargs.get("env") or {})
        calls.append(env)
        if len(calls) == 1:
            raise subprocess.CalledProcessError(
                returncode=1,
                cmd=args[0],
                stderr="default auth unavailable",
            )
        assert env.get("GOOGLE_API_KEY") == "vertex-fallback-key"
        assert env.get("GOOGLE_GENAI_USE_VERTEXAI") == "true"
        return subprocess.CompletedProcess(
            args=args[0],
            returncode=0,
            stdout=json.dumps(
                {
                    "response": "{\"ok\": true}",
                    "stats": {"models": {"gemini-2.5-flash": {"tokens": {"input": 5, "candidates": 3}}}},
                }
            ),
            stderr="",
        )

    monkeypatch.setenv("GOOGLE_API_KEY_FALLBACK_1", "vertex-fallback-key")
    monkeypatch.setenv("EA_RESPONSES_PROVIDER_LEDGER_DIR", str(tmp_path))
    monkeypatch.setenv("EA_GEMINI_VORTEX_SELECTION_MODE", "fallback")
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
            session_id="session-fallback",
            step_id="step-fallback",
            tool_name="provider.gemini_vortex.structured_generate",
            action_kind="content.generate",
            payload_json={"normalized_text": "Return JSON only.", "goal": "fallback to vertex slot"},
            context_json={"principal_id": "exec-1"},
        )
    )

    assert len(calls) == 2
    assert "GOOGLE_API_KEY" not in calls[0]
    assert result.output_json["provider_key_slot"] == "fallback_1"
    assert result.output_json["provider_account_name"] == "GOOGLE_API_KEY_FALLBACK_1"
    assert result.output_json["lease_holder"] == "exec-1"


def test_gemini_vortex_tool_reuses_principal_slot_lease(monkeypatch, tmp_path) -> None:
    seen_slots: list[str] = []

    def fake_run(*args, **kwargs):
        env = dict(kwargs.get("env") or {})
        seen_slots.append("fallback_1" if env.get("GOOGLE_API_KEY") else "default")
        return subprocess.CompletedProcess(
            args=args[0],
            returncode=0,
            stdout=json.dumps({"response": "{\"ok\": true}", "stats": {"models": {"gemini-2.5-flash": {"tokens": {"input": 1, "candidates": 1}}}}}),
            stderr="",
        )

    monkeypatch.setenv("GOOGLE_API_KEY_FALLBACK_1", "vertex-fallback-key")
    monkeypatch.setenv("EA_RESPONSES_PROVIDER_LEDGER_DIR", str(tmp_path))
    monkeypatch.setenv("EA_GEMINI_VORTEX_SELECTION_MODE", "round_robin")
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

    for step_id in ("step-1", "step-2"):
        result = service.execute_invocation(
            ToolInvocationRequest(
                session_id="session-round-robin",
                step_id=step_id,
                tool_name="provider.gemini_vortex.structured_generate",
                action_kind="content.generate",
                payload_json={"normalized_text": "Return JSON only.", "goal": "keep slot sticky"},
                context_json={"principal_id": "fleet-shadow"},
            )
        )
        assert result.output_json["lease_holder"] == "fleet-shadow"

    assert seen_slots == ["default", "default"]
