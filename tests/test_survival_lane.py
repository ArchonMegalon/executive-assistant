from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.domain.models import ToolInvocationResult
from app.services import survival_lane
from app.services.survival_lane import SurvivalLaneService, _test_reset_survival_state
from app.services.tool_execution_common import ToolExecutionError


class _FakeToolExecution:
    def __init__(self, handlers: dict[str, object]) -> None:
        self._handlers = handlers
        self.calls: list[str] = []

    def execute_invocation(self, invocation):
        self.calls.append(invocation.tool_name)
        handler = self._handlers[invocation.tool_name]
        return handler(invocation)


class _FakeToolRuntime:
    def __init__(self, *, binding_id: str = "binding-browseract-1") -> None:
        self._binding = SimpleNamespace(
            binding_id=binding_id,
            connector_name="browseract",
            status="enabled",
        )

    def list_connector_bindings(self, _principal_id: str, limit: int = 100):
        assert limit >= 1
        return [self._binding]


def _result(*, tool_name: str, output_json: dict[str, object], model_name: str = "") -> ToolInvocationResult:
    return ToolInvocationResult(
        tool_name=tool_name,
        action_kind="content.generate",
        target_ref=f"test:{tool_name}",
        output_json=output_json,
        receipt_json={"handler_key": tool_name, "invocation_contract": "tool.v1"},
        model_name=model_name,
    )


@pytest.fixture(autouse=True)
def _reset_survival_state(monkeypatch: pytest.MonkeyPatch) -> None:
    _test_reset_survival_state()
    monkeypatch.setenv("EA_SURVIVAL_ENABLED", "1")
    monkeypatch.setenv("EA_SURVIVAL_CACHE_TTL_SECONDS", "86400")
    monkeypatch.setenv("EA_UI_CHALLENGE_COOLDOWN_SECONDS", "1800")
    monkeypatch.setenv("EA_UI_CHALLENGE_MAX_CONSECUTIVE", "2")


def test_survival_falls_back_from_gemini_vortex_to_gemini_web(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EA_SURVIVAL_ROUTE_ORDER", "gemini_vortex,gemini_web")

    def _gemini_vortex(_invocation) -> ToolInvocationResult:
        raise ToolExecutionError("gemini_vortex_failed")

    def _gemini_web(_invocation) -> ToolInvocationResult:
        return _result(
            tool_name="browseract.gemini_web_generate",
            output_json={"text": "from gemini web", "mode_used": "thinking"},
        )

    service = SurvivalLaneService(
        tool_execution=_FakeToolExecution(
            {
                "provider.gemini_vortex.structured_generate": _gemini_vortex,
                "browseract.gemini_web_generate": _gemini_web,
            }
        ),
        tool_runtime=_FakeToolRuntime(),
        principal_id="survival-test",
    )

    result = service.execute(
        instructions="stay concise",
        history_items=[{"type": "message", "role": "user", "content": [{"type": "input_text", "text": "prior"}]}],
        current_input="what now",
        desired_format="plain_text",
    )

    assert result.text == "from gemini web"
    assert result.provider_backend == "gemini_web"
    assert [item.backend for item in result.attempts] == ["gemini_vortex", "gemini_web"]
    assert result.attempts[0].status == "failed"
    assert result.attempts[1].status == "completed"


def test_survival_falls_back_from_gemini_web_to_chatplayground_on_challenge(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EA_SURVIVAL_ROUTE_ORDER", "gemini_web,chatplayground")

    def _gemini_web(_invocation) -> ToolInvocationResult:
        raise ToolExecutionError("ui_lane_failure:gemini_web:challenge_required")

    def _chatplayground(_invocation) -> ToolInvocationResult:
        return _result(
            tool_name="browseract.chatplayground_audit",
            output_json={"consensus": "tie-break answer", "structured_output_json": {"status": "ok"}},
        )

    service = SurvivalLaneService(
        tool_execution=_FakeToolExecution(
            {
                "browseract.gemini_web_generate": _gemini_web,
                "browseract.chatplayground_audit": _chatplayground,
            }
        ),
        tool_runtime=_FakeToolRuntime(),
        principal_id="survival-test",
    )

    result = service.execute(
        instructions=None,
        history_items=[],
        current_input="fallback please",
        desired_format="plain_text",
    )

    assert result.text == "tie-break answer"
    assert result.provider_backend == "chatplayground"
    assert [item.backend for item in result.attempts] == ["gemini_web", "chatplayground"]
    assert result.attempts[0].detail == "challenge_required"
    assert result.attempts[1].status == "completed"


def test_survival_skips_backend_during_challenge_cooldown(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EA_SURVIVAL_ROUTE_ORDER", "gemini_web,chatplayground")
    gemini_calls = {"count": 0}
    chatplayground_calls = {"count": 0}

    def _gemini_web(_invocation) -> ToolInvocationResult:
        gemini_calls["count"] += 1
        raise ToolExecutionError("ui_lane_failure:gemini_web:challenge_required")

    def _chatplayground(_invocation) -> ToolInvocationResult:
        chatplayground_calls["count"] += 1
        return _result(
            tool_name="browseract.chatplayground_audit",
            output_json={"consensus": f"chatplayground-{chatplayground_calls['count']}", "structured_output_json": {"status": "ok"}},
        )

    service = SurvivalLaneService(
        tool_execution=_FakeToolExecution(
            {
                "browseract.gemini_web_generate": _gemini_web,
                "browseract.chatplayground_audit": _chatplayground,
            }
        ),
        tool_runtime=_FakeToolRuntime(),
        principal_id="survival-test",
    )

    first = service.execute(instructions=None, history_items=[], current_input="first request", desired_format="plain_text")
    second = service.execute(instructions=None, history_items=[], current_input="second request", desired_format="plain_text")

    assert first.provider_backend == "chatplayground"
    assert second.provider_backend == "chatplayground"
    assert gemini_calls["count"] == 1
    assert chatplayground_calls["count"] == 2
    assert second.attempts[0].backend == "gemini_web"
    assert second.attempts[0].status == "skipped"
    assert second.attempts[0].detail == "cooldown_active:challenge_required"


def test_survival_cache_hit_short_circuits_backends(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EA_SURVIVAL_ROUTE_ORDER", "gemini_web")
    gemini_calls = {"count": 0}

    def _gemini_web(_invocation) -> ToolInvocationResult:
        gemini_calls["count"] += 1
        return _result(
            tool_name="browseract.gemini_web_generate",
            output_json={"text": "cached answer", "mode_used": "thinking"},
        )

    service = SurvivalLaneService(
        tool_execution=_FakeToolExecution({"browseract.gemini_web_generate": _gemini_web}),
        tool_runtime=_FakeToolRuntime(),
        principal_id="survival-test",
    )

    first = service.execute(instructions=None, history_items=[], current_input="same input", desired_format="plain_text")
    second = service.execute(instructions=None, history_items=[], current_input="same input", desired_format="plain_text")

    assert first.cache_hit is False
    assert second.cache_hit is True
    assert gemini_calls["count"] == 1
    assert second.attempts[-1].backend == "cache"


def test_survival_queue_timeout_raises_runtime_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(survival_lane, "_acquire_survival_slot", lambda: False)
    service = SurvivalLaneService(
        tool_execution=None,
        tool_runtime=None,
        principal_id="survival-test",
    )

    with pytest.raises(RuntimeError, match="survival_queue_timeout"):
        service.execute(
            instructions=None,
            history_items=[],
            current_input="queue me",
            desired_format="plain_text",
        )
