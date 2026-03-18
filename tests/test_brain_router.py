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
