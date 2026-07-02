from __future__ import annotations

import os
from types import SimpleNamespace
from unittest.mock import patch

from app.api.routes import responses as responses_route
from app.domain.models import ToolDefinition, ToolInvocationRequest
from app.services import responses_upstream
from app.services.brain_catalog import GEMINI_VORTEX_PUBLIC_MODEL, GROUNDWORK_PUBLIC_MODEL
from app.services.brain_router import BrainRouterService
from app.services.provider_registry import ProviderRegistryService
from app.services.tool_execution_onemin_adapter import OneminToolAdapter


def _provider_env() -> dict[str, str]:
    return {
        "PATH": os.environ.get("PATH", ""),
        "ONEMIN_AI_API_KEY": "onemin-key",
        "AI_MAGICX_API_KEY": "magicx-key",
        "EA_GEMINI_VORTEX_COMMAND": "sh",
    }


def _health(*, onemin_dispatchable: bool = True) -> dict[str, object]:
    return {
        "providers": {
            "onemin": {
                "state": "ready" if onemin_dispatchable else "unavailable",
                "live_dispatchable_slot_count": 1 if onemin_dispatchable else 0,
                "live_ready_slot_count": 1 if onemin_dispatchable else 0,
                "ready_slot_count": 1 if onemin_dispatchable else 0,
            },
            "magixai": {"state": "ready"},
            "gemini_vortex": {"state": "ready"},
        }
    }


def _provider_first_occurrence(candidates: list[tuple[responses_upstream.ProviderConfig, str]]) -> list[str]:
    ordered: list[str] = []
    for config, _model in candidates:
        if config.provider_key not in ordered:
            ordered.append(config.provider_key)
    return ordered


def test_groundwork_profile_prefers_onemin_for_non_urgent_background_work() -> None:
    with patch.dict(os.environ, _provider_env(), clear=True):
        decision = BrainRouterService(ProviderRegistryService()).resolve_profile("groundwork")

    assert decision.provider_hint_order[:3] == ("onemin", "magixai", "gemini_vortex")
    assert decision.backend_key == "onemin"
    assert decision.health_provider_key == "onemin"


def test_groundwork_structured_route_uses_onemin_text_tool() -> None:
    with patch.dict(os.environ, _provider_env(), clear=True):
        route = ProviderRegistryService().route_brain_profile_capability_with_context(
            profile_name="groundwork",
            capability_key="structured_generate",
            allowed_tools=(
                "provider.onemin.code_generate",
                "provider.gemini_vortex.structured_generate",
                "provider.magixai.structured_generate",
            ),
        )

    assert route.provider_key == "onemin"
    assert route.capability_key == "structured_generate"
    assert route.tool_name == "provider.onemin.code_generate"


def test_groundwork_response_candidates_use_onemin_then_magicx_before_gemini() -> None:
    with (
        patch.dict(os.environ, _provider_env(), clear=True),
        patch.object(responses_upstream, "_provider_health_snapshot", return_value=_health(onemin_dispatchable=True)),
    ):
        candidates = responses_upstream._provider_candidates(GROUNDWORK_PUBLIC_MODEL)

    assert _provider_first_occurrence(candidates)[:3] == ["onemin", "magixai", "gemini_vortex"]


def test_groundwork_response_candidates_spill_to_magicx_before_gemini_when_onemin_unavailable() -> None:
    with (
        patch.dict(os.environ, _provider_env(), clear=True),
        patch.object(responses_upstream, "_provider_health_snapshot", return_value=_health(onemin_dispatchable=False)),
    ):
        candidates = responses_upstream._provider_candidates(GROUNDWORK_PUBLIC_MODEL)

    assert _provider_first_occurrence(candidates)[:3] == ["magixai", "gemini_vortex", "onemin"]


def test_explicit_gemini_model_stays_gemini_only() -> None:
    with patch.dict(os.environ, _provider_env(), clear=True):
        candidates = responses_upstream._provider_candidates(GEMINI_VORTEX_PUBLIC_MODEL)

    assert candidates
    assert {config.provider_key for config, _model in candidates} == {"gemini_vortex"}


def test_groundwork_ready_provider_prefers_ready_onemin_over_ready_gemini() -> None:
    provider = responses_route._groundwork_ready_provider(
        {"profile": "groundwork"},
        provider_health=_health(onemin_dispatchable=True),
    )

    assert provider == "onemin"


def test_onemin_groundwork_execution_uses_background_lane_and_model(monkeypatch) -> None:
    adapter = OneminToolAdapter()
    calls: list[dict[str, object]] = []

    def fake_call_text(**kwargs):
        calls.append(dict(kwargs))
        return SimpleNamespace(
            text='{"plan":["check"],"risks":[],"missing_evidence":[],"recommended_next_lane":"review_light","acceptance_checklist":[]}',
            model=str(kwargs.get("model") or ""),
            provider_backend="1min",
            provider_account_name="acct",
            provider_key_slot="primary",
            tokens_in=10,
            tokens_out=20,
        )

    monkeypatch.setenv("EA_ONEMIN_TOOL_GROUNDWORK_MODEL", "deepseek-chat")
    monkeypatch.setattr(adapter, "_call_text", fake_call_text)

    result = adapter.execute_code_generate(
        ToolInvocationRequest(
            session_id="s",
            step_id="step",
            tool_name="provider.onemin.code_generate",
            action_kind="",
            payload_json={
                "brain_profile": "groundwork",
                "normalized_text": "prepare the brief",
                "desired_output_json": {"format": "groundwork_brief"},
            },
            context_json={"principal_id": "operator"},
        ),
        ToolDefinition(
            tool_name="provider.onemin.code_generate",
            version="v1",
            input_schema_json={},
            output_schema_json={},
            policy_json={},
            allowed_channels=(),
            approval_default="none",
            enabled=True,
            updated_at="",
        ),
    )

    assert calls
    assert calls[0]["lane"] == "groundwork"
    assert calls[0]["model"] == "deepseek-chat"
    assert "Desired output" in str(calls[0]["prompt"])
    assert result.model_name == "deepseek-chat"
    assert result.output_json["structured_output_json"]["plan"] == ["check"]
