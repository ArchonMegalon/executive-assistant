from __future__ import annotations

import errno
import json
import subprocess
import pytest

from app.domain.models import ToolInvocationRequest
from app.repositories.artifacts import InMemoryArtifactRepository
from app.repositories.connector_bindings import InMemoryConnectorBindingRepository
from app.services.tool_execution import ToolExecutionService
from app.services.tool_runtime import ToolRuntimeService
from app.repositories.tool_registry import InMemoryToolRegistryRepository


def _enable_fake_gemini_cli(monkeypatch) -> None:
    monkeypatch.setenv("EA_GEMINI_VORTEX_COMMAND", "sh")


def test_gemini_vortex_tool_executes_and_returns_structured_output(monkeypatch) -> None:
    _enable_fake_gemini_cli(monkeypatch)

    def fake_run(*args, **kwargs):
        return subprocess.CompletedProcess(
            args=args[0],
            returncode=0,
            stdout=json.dumps(
                {
                    "response": "{\"ok\": true, \"title\": \"Chummer6\"}",
                    "stats": {
                        "models": {
                            "gemini-3.5-flash": {
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
    assert result.model_name == "gemini-3.5-flash"
    assert result.tokens_in == 123
    assert result.tokens_out == 45
    assert result.output_json["mime_type"] == "application/json"
    assert result.output_json["provider_key_slot"] == "default"
    assert result.output_json["provider_account_name"] == "EA_GEMINI_VORTEX_DEFAULT_AUTH"
    assert result.output_json["lease_holder"] == "exec-1"
    assert result.output_json["structured_output_json"]["ok"] is True
    assert result.output_json["structured_output_json"]["title"] == "Chummer6"


def test_gemini_vortex_tool_prefers_direct_api_key_and_skips_trust(monkeypatch, tmp_path) -> None:
    _enable_fake_gemini_cli(monkeypatch)
    calls: list[tuple[list[str], dict[str, str]]] = []

    def fake_run(*args, **kwargs):
        command = list(args[0])
        env = dict(kwargs.get("env") or {})
        calls.append((command, env))
        assert "--skip-trust" in command
        assert env.get("GEMINI_API_KEY") == "direct-gemini-key"
        assert "GOOGLE_API_KEY" not in env
        return subprocess.CompletedProcess(
            args=command,
            returncode=0,
            stdout=json.dumps(
                {
                    "response": "{\"ok\": true}",
                    "stats": {"models": {"gemini-3.5-flash": {"tokens": {"input": 2, "candidates": 1}}}},
                }
            ),
            stderr="",
        )

    monkeypatch.setenv("EA_GEMINI_VORTEX_API_KEY", "direct-gemini-key")
    monkeypatch.setenv("EA_RESPONSES_PROVIDER_LEDGER_DIR", str(tmp_path))
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
            session_id="session-direct-key",
            step_id="step-direct-key",
            tool_name="provider.gemini_vortex.structured_generate",
            action_kind="content.generate",
            payload_json={"normalized_text": "Return JSON only.", "model": "gemini-3.5-flash"},
            context_json={"principal_id": "exec-1"},
        )
    )

    assert len(calls) == 1
    assert result.output_json["provider_key_slot"] == "default"
    assert result.output_json["provider_account_name"] == "EA_GEMINI_VORTEX_API_KEY"
    assert result.model_name == "gemini-3.5-flash"


def test_gemini_vortex_tool_uses_clean_home_for_vertex_adc(monkeypatch, tmp_path) -> None:
    _enable_fake_gemini_cli(monkeypatch)
    credentials = tmp_path / "adc.json"
    credentials.write_text("{}", encoding="utf-8")
    seen_env: dict[str, str] = {}

    def fake_run(*args, **kwargs):
        seen_env.update(dict(kwargs.get("env") or {}))
        return subprocess.CompletedProcess(
            args=args[0],
            returncode=0,
            stdout=json.dumps({"response": "{\"ok\": true}", "stats": {"models": {"gemini-3.5-flash": {"tokens": {"input": 1, "candidates": 1}}}}}),
            stderr="",
        )

    monkeypatch.setenv("GOOGLE_GENAI_USE_VERTEXAI", "true")
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "openclaw-concierge")
    monkeypatch.setenv("GOOGLE_CLOUD_LOCATION", "global")
    monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", str(credentials))
    monkeypatch.setenv("EA_GEMINI_VORTEX_HOME_ROOT", str(tmp_path / "homes"))
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

    service.execute_invocation(
        ToolInvocationRequest(
            session_id="session-vertex-adc",
            step_id="step-vertex-adc",
            tool_name="provider.gemini_vortex.structured_generate",
            action_kind="content.generate",
            payload_json={"normalized_text": "Return JSON only.", "model": "gemini-3.5-flash"},
            context_json={"principal_id": "exec-1"},
        )
    )

    assert seen_env["HOME"].endswith("/env_default")
    assert not (tmp_path / "homes" / "env_default" / ".gemini" / "settings.json").exists()


def test_gemini_vortex_tool_uses_clean_home_for_default_auth_without_detected_config(
    monkeypatch,
    tmp_path,
) -> None:
    _enable_fake_gemini_cli(monkeypatch)
    seen_env: dict[str, str] = {}

    def fake_run(*args, **kwargs):
        seen_env.update(dict(kwargs.get("env") or {}))
        return subprocess.CompletedProcess(
            args=args[0],
            returncode=0,
            stdout=json.dumps({"response": "{\"ok\": true}", "stats": {"models": {"gemini-3.5-flash": {"tokens": {"input": 1, "candidates": 1}}}}}),
            stderr="",
        )

    monkeypatch.delenv("EA_GEMINI_VORTEX_CONFIG_DIR", raising=False)
    monkeypatch.delenv("GOOGLE_GENAI_USE_VERTEXAI", raising=False)
    monkeypatch.delenv("GOOGLE_CLOUD_PROJECT", raising=False)
    monkeypatch.delenv("GOOGLE_CLOUD_LOCATION", raising=False)
    monkeypatch.delenv("GOOGLE_APPLICATION_CREDENTIALS", raising=False)
    monkeypatch.setenv("EA_GEMINI_VORTEX_HOME_ROOT", str(tmp_path / "homes"))
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

    service.execute_invocation(
        ToolInvocationRequest(
            session_id="session-default-auth-home",
            step_id="step-default-auth-home",
            tool_name="provider.gemini_vortex.structured_generate",
            action_kind="content.generate",
            payload_json={"normalized_text": "Return JSON only.", "model": "gemini-3.5-flash"},
            context_json={"principal_id": "exec-1"},
        )
    )

    assert seen_env["HOME"].endswith("/default")
    assert seen_env["XDG_CONFIG_HOME"].endswith("/default/.config")
    assert seen_env["XDG_CACHE_HOME"].endswith("/default/.cache")
    assert seen_env["XDG_DATA_HOME"].endswith("/default/.local/share")
    assert (tmp_path / "homes" / "default" / ".gemini" / "tmp").is_dir()


def test_gemini_vortex_tool_falls_back_to_vertex_key_slot(monkeypatch, tmp_path) -> None:
    _enable_fake_gemini_cli(monkeypatch)
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
    _enable_fake_gemini_cli(monkeypatch)
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


def test_gemini_vortex_tool_retries_transient_spawn_eagain(monkeypatch, tmp_path) -> None:
    _enable_fake_gemini_cli(monkeypatch)
    calls = {"count": 0}

    def fake_run(*args, **kwargs):
        calls["count"] += 1
        if calls["count"] == 1:
            raise OSError(errno.EAGAIN, "spawn /usr/bin/node EAGAIN")
        return subprocess.CompletedProcess(
            args=args[0],
            returncode=0,
            stdout=json.dumps(
                {
                    "response": "{\"ok\": true}",
                    "stats": {"models": {"gemini-3.5-flash": {"tokens": {"input": 3, "candidates": 2}}}},
                }
            ),
            stderr="",
        )

    monkeypatch.setenv("EA_RESPONSES_PROVIDER_LEDGER_DIR", str(tmp_path))
    monkeypatch.setenv("EA_GEMINI_VORTEX_SPAWN_RETRIES", "2")
    monkeypatch.setenv("EA_GEMINI_VORTEX_API_KEY", "direct-gemini-key")
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
            session_id="session-eagain",
            step_id="step-eagain",
            tool_name="provider.gemini_vortex.structured_generate",
            action_kind="content.generate",
            payload_json={"normalized_text": "Return JSON only."},
            context_json={"principal_id": "exec-1"},
        )
    )

    assert calls["count"] == 2
    assert result.output_json["structured_output_json"]["ok"] is True


def test_gemini_vortex_tool_sets_spawn_pressure_cooldown_after_terminal_eagain(monkeypatch, tmp_path) -> None:
    _enable_fake_gemini_cli(monkeypatch)
    calls = {"count": 0}

    def fake_run(*args, **kwargs):
        calls["count"] += 1
        raise OSError(errno.EAGAIN, "spawn /usr/bin/node EAGAIN")

    monkeypatch.setenv("EA_RESPONSES_PROVIDER_LEDGER_DIR", str(tmp_path))
    monkeypatch.setenv("EA_GEMINI_VORTEX_SPAWN_RETRIES", "0")
    monkeypatch.setenv("EA_GEMINI_VORTEX_SPAWN_PRESSURE_COOLDOWN_SECONDS", "30")
    monkeypatch.setenv("EA_GEMINI_VORTEX_API_KEY", "direct-gemini-key")
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

    with pytest.raises(Exception) as excinfo:
        service.execute_invocation(
            ToolInvocationRequest(
                session_id="session-eagain-terminal",
                step_id="step-eagain-terminal",
                tool_name="provider.gemini_vortex.structured_generate",
                action_kind="content.generate",
                payload_json={"normalized_text": "Return JSON only."},
                context_json={"principal_id": "exec-1"},
            )
        )

    assert "gemini_vortex_failed" in str(excinfo.value)
    assert calls["count"] == 1

    from app.services.tool_execution_gemini_vortex_adapter import _spawn_pressure_active

    active, detail = _spawn_pressure_active()
    assert active is True
    assert "spawn_pressure_cooldown" in detail


def test_gemini_vortex_tool_short_circuits_while_spawn_pressure_cooldown_active(monkeypatch, tmp_path) -> None:
    _enable_fake_gemini_cli(monkeypatch)
    calls = {"count": 0}

    def fake_run(*args, **kwargs):
        calls["count"] += 1
        return subprocess.CompletedProcess(
            args=args[0],
            returncode=0,
            stdout=json.dumps(
                {
                    "response": "{\"ok\": true}",
                    "stats": {"models": {"gemini-3.5-flash": {"tokens": {"input": 1, "candidates": 1}}}},
                }
            ),
            stderr="",
        )

    monkeypatch.setenv("EA_RESPONSES_PROVIDER_LEDGER_DIR", str(tmp_path))
    monkeypatch.setenv("EA_GEMINI_VORTEX_API_KEY", "direct-gemini-key")
    monkeypatch.setattr(
        "app.services.tool_execution_gemini_vortex_adapter.subprocess.run",
        fake_run,
    )

    from app.services.tool_execution_gemini_vortex_adapter import _record_spawn_pressure

    _record_spawn_pressure("spawn /usr/bin/node EAGAIN")

    tool_runtime = ToolRuntimeService(
        tool_registry=InMemoryToolRegistryRepository(),
        connector_bindings=InMemoryConnectorBindingRepository(),
    )
    service = ToolExecutionService(
        tool_runtime=tool_runtime,
        artifacts=InMemoryArtifactRepository(),
    )

    with pytest.raises(Exception) as excinfo:
        service.execute_invocation(
            ToolInvocationRequest(
                session_id="session-eagain-cooldown",
                step_id="step-eagain-cooldown",
                tool_name="provider.gemini_vortex.structured_generate",
                action_kind="content.generate",
                payload_json={"normalized_text": "Return JSON only."},
                context_json={"principal_id": "exec-1"},
            )
        )

    assert "spawn_pressure_cooldown" in str(excinfo.value)
    assert calls["count"] == 0


def test_gemini_vortex_tool_sets_low_uv_threadpool_by_default(monkeypatch, tmp_path) -> None:
    _enable_fake_gemini_cli(monkeypatch)
    seen_env: dict[str, str] = {}

    def fake_run(*args, **kwargs):
        seen_env.update(dict(kwargs.get("env") or {}))
        return subprocess.CompletedProcess(
            args=args[0],
            returncode=0,
            stdout=json.dumps(
                {
                    "response": "{\"ok\": true}",
                    "stats": {"models": {"gemini-3.5-flash": {"tokens": {"input": 1, "candidates": 1}}}},
                }
            ),
            stderr="",
        )

    monkeypatch.setenv("EA_RESPONSES_PROVIDER_LEDGER_DIR", str(tmp_path))
    monkeypatch.setenv("EA_GEMINI_VORTEX_API_KEY", "direct-gemini-key")
    monkeypatch.delenv("UV_THREADPOOL_SIZE", raising=False)
    monkeypatch.delenv("EA_GEMINI_VORTEX_UV_THREADPOOL_SIZE", raising=False)
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

    service.execute_invocation(
        ToolInvocationRequest(
            session_id="session-threadpool",
            step_id="step-threadpool",
            tool_name="provider.gemini_vortex.structured_generate",
            action_kind="content.generate",
            payload_json={"normalized_text": "Return JSON only."},
            context_json={"principal_id": "exec-1"},
        )
    )

    assert seen_env["UV_THREADPOOL_SIZE"] == "1"


def test_gemini_vortex_tool_rejects_missing_default_auth(monkeypatch) -> None:
    _enable_fake_gemini_cli(monkeypatch)
    for name in (
        "EA_GEMINI_VORTEX_API_KEY",
        "GEMINI_API_KEY",
        "GOOGLE_API_KEY",
        "GOOGLE_API_KEY_FALLBACK_1",
        "GOOGLE_APPLICATION_CREDENTIALS",
        "GOOGLE_CLOUD_PROJECT",
        "GOOGLE_CLOUD_LOCATION",
        "GOOGLE_GENAI_USE_VERTEXAI",
        "EA_GEMINI_VORTEX_CONFIG_DIR",
    ):
        monkeypatch.delenv(name, raising=False)

    tool_runtime = ToolRuntimeService(
        tool_registry=InMemoryToolRegistryRepository(),
        connector_bindings=InMemoryConnectorBindingRepository(),
    )
    service = ToolExecutionService(
        tool_runtime=tool_runtime,
        artifacts=InMemoryArtifactRepository(),
    )

    with pytest.raises(Exception, match="gemini_vortex_auth_missing:missing:auth_config_dir_missing"):
        service.execute_invocation(
            ToolInvocationRequest(
                session_id="session-missing-auth",
                step_id="step-missing-auth",
                tool_name="provider.gemini_vortex.structured_generate",
                action_kind="content.generate",
                payload_json={"normalized_text": "Return JSON only."},
                context_json={"principal_id": "exec-1"},
            )
        )
