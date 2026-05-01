from __future__ import annotations

from app.repositories.provider_bindings import InMemoryProviderBindingRepository
from app.services.brain_router import BrainRouterService
from app.services.provider_registry import ProviderRegistryService
from app.services.task_contracts import TaskContractService
from app.repositories.task_contracts import InMemoryTaskContractRepository


def test_brain_router_prefers_available_profile_hints(monkeypatch) -> None:
    monkeypatch.setenv("EA_GEMINI_VORTEX_COMMAND", "python3")
    repo = InMemoryProviderBindingRepository()
    repo.upsert(principal_id="exec-1", provider_key="magixai", status="disabled")
    router = BrainRouterService(provider_registry=ProviderRegistryService(provider_binding_repo=repo))

    decision = router.resolve_profile("easy", principal_id="exec-1")

    assert decision.profile == "easy"
    assert decision.provider_hint_order == ("gemini_vortex",)
    assert decision.backend_key == "gemini_vortex"
    assert decision.health_provider_key == "gemini_vortex"


def test_brain_router_falls_through_to_magixai_when_gemini_is_unavailable(monkeypatch) -> None:
    monkeypatch.setenv("AI_MAGICX_API_KEY", "magicx-key")
    repo = InMemoryProviderBindingRepository()
    repo.upsert(principal_id="exec-1", provider_key="gemini_vortex", status="disabled")
    router = BrainRouterService(provider_registry=ProviderRegistryService(provider_binding_repo=repo))

    decision = router.resolve_profile("easy", principal_id="exec-1")

    assert decision.profile == "easy"
    assert decision.provider_hint_order == ("magixai",)
    assert decision.backend_key == "magixai"
    assert decision.health_provider_key == "magixai"


def test_brain_router_repair_falls_through_to_onemin_when_cheap_providers_are_unavailable(monkeypatch) -> None:
    monkeypatch.setenv("ONEMIN_AI_API_KEY", "onemin-key")
    monkeypatch.delenv("AI_MAGICX_API_KEY", raising=False)
    repo = InMemoryProviderBindingRepository()
    repo.upsert(principal_id="exec-1", provider_key="gemini_vortex", status="disabled")
    repo.upsert(principal_id="exec-1", provider_key="magixai", status="disabled")
    router = BrainRouterService(provider_registry=ProviderRegistryService(provider_binding_repo=repo))

    decision = router.resolve_profile("repair", principal_id="exec-1")

    assert decision.profile == "repair"
    assert decision.provider_hint_order == ("onemin",)
    assert decision.backend_key == "onemin"
    assert decision.health_provider_key == "onemin"


def test_brain_router_merges_contract_profile_and_provider_hints(monkeypatch) -> None:
    contracts = TaskContractService(InMemoryTaskContractRepository())
    bindings = InMemoryProviderBindingRepository()
    monkeypatch.setenv("BROWSERACT_API_KEY", "browseract-key")
    bindings.upsert(principal_id="exec-2", provider_key="browseract", status="enabled")
    contract = contracts.upsert_contract(
        task_key="guide_refresh",
        deliverable_type="guide_packet",
        default_risk_class="low",
        default_approval_class="none",
        allowed_tools=("provider.gemini_vortex.structured_generate", "artifact_repository"),
        memory_write_policy="none",
        runtime_policy_json={
            "workflow_template": "tool_then_artifact",
            "skill_catalog_json": {
                "model_policy_json": {"brain_profile": "groundwork"},
                "provider_hints_json": {"research": ["BrowserAct"]},
            },
        },
    )

    router = BrainRouterService(provider_registry=ProviderRegistryService(provider_binding_repo=bindings))
    hints = router.provider_hints_for_contract(contract, principal_id="exec-2")

    assert hints[0] == "gemini_vortex"
    assert "browseract" in hints


def test_brain_router_falls_back_to_browseract_review_metadata_when_onemin_is_unavailable(monkeypatch) -> None:
    monkeypatch.setenv("BROWSERACT_API_KEY", "browseract-key")
    monkeypatch.setenv("ONEMIN_AI_API_KEY", "")
    monkeypatch.setenv("ONEMIN_AI_API_KEY_FALLBACK_1", "")
    monkeypatch.setenv("ONEMIN_AI_API_KEY_FALLBACK_2", "")
    monkeypatch.setenv("ONEMIN_AI_API_KEY_FALLBACK_3", "")
    monkeypatch.setenv("ONEMIN_AI_API_KEY_FALLBACK_4", "")
    monkeypatch.setenv("ONEMIN_AI_API_KEY_FALLBACK_5", "")
    monkeypatch.setenv("ONEMIN_AI_API_KEY_FALLBACK_6", "")
    monkeypatch.setenv("ONEMIN_AI_API_KEY_FALLBACK_7", "")
    monkeypatch.setenv("ONEMIN_AI_API_KEY_FALLBACK_8", "")
    monkeypatch.setenv("ONEMIN_AI_API_KEY_FALLBACK_9", "")
    monkeypatch.setenv("ONEMIN_AI_API_KEY_FALLBACK_10", "")

    repo = InMemoryProviderBindingRepository()
    repo.upsert(principal_id="exec-1", provider_key="gemini_vortex", status="disabled")
    router = BrainRouterService(provider_registry=ProviderRegistryService(provider_binding_repo=repo))
    decision = router.resolve_profile("review_light", principal_id="exec-1")

    assert decision.provider_hint_order == ("browseract",)
    assert decision.backend_key == "browseract"
    assert decision.health_provider_key == "browseract"


def test_brain_router_prefers_onemin_for_review_light_when_available(monkeypatch) -> None:
    monkeypatch.setenv("EA_GEMINI_VORTEX_COMMAND", "python3")
    monkeypatch.setenv("ONEMIN_AI_API_KEY", "onemin-key")
    monkeypatch.setenv("BROWSERACT_API_KEY", "browseract-key")

    router = BrainRouterService(provider_registry=ProviderRegistryService())
    decision = router.resolve_profile("review_light")

    assert decision.provider_hint_order[0] == "onemin"
    assert decision.backend_key == "onemin"
    assert decision.health_provider_key == "onemin"
