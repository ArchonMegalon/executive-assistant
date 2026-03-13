from __future__ import annotations

import pytest

from app.domain.models import PlanValidationError, SkillContract
from app.repositories.task_contracts import InMemoryTaskContractRepository
from app.services.planner import PlannerService
from app.services.provider_registry import ProviderRegistryService
from app.services.task_contracts import TaskContractService
from app.services.tool_execution_common import ToolExecutionError


def test_provider_registry_matches_allowed_tools_and_provider_hints() -> None:
    registry = ProviderRegistryService()
    skill = SkillContract(
        skill_key="inventory_refresh",
        task_key="inventory_refresh",
        name="Inventory Refresh",
        description="refresh inventory",
        deliverable_type="inventory",
        default_risk_class="low",
        default_approval_class="none",
        workflow_template="tool_then_artifact",
        allowed_tools=("browseract.extract_account_inventory", "artifact_repository"),
        evidence_requirements=(),
        memory_write_policy="none",
        memory_reads=(),
        memory_writes=(),
        tags=("inventory",),
        input_schema_json={},
        output_schema_json={},
        authority_profile_json={},
        model_policy_json={},
        provider_hints_json={"preferred": ["browseract"], "research": ["browserly"]},
        tool_policy_json={},
        human_policy_json={},
        evaluation_cases_json=(),
        updated_at="2026-03-12T00:00:00Z",
    )
    bindings = registry.bindings_for_skill(skill)
    keys = {binding.provider_key for binding in bindings}
    assert "browseract" in keys
    assert "browserly" in keys
    assert "artifact_repository" in keys


def test_provider_registry_routes_capability_with_provider_hints() -> None:
    registry = ProviderRegistryService()
    route = registry.route_tool_by_capability(
        capability_key="account_inventory",
        provider_hints=("BrowserAct",),
        allowed_tools=("browseract.extract_account_inventory", "artifact_repository"),
    )
    assert route.provider_key == "browseract"
    assert route.tool_name == "browseract.extract_account_inventory"
    assert route.executable is True


def test_provider_registry_routes_gemini_vortex_structured_generate_with_alias_hints() -> None:
    registry = ProviderRegistryService()
    route = registry.route_tool_by_capability(
        capability_key="generate_json",
        provider_hints=("Gemini", "Vortex"),
        allowed_tools=("provider.gemini_vortex.structured_generate", "artifact_repository"),
    )
    assert route.provider_key == "gemini_vortex"
    assert route.capability_key == "structured_generate"
    assert route.tool_name == "provider.gemini_vortex.structured_generate"
    assert route.executable is True


def test_provider_registry_routes_browseract_workflow_spec_build_with_alias_hints() -> None:
    registry = ProviderRegistryService()
    route = registry.route_tool_by_capability(
        capability_key="build_workflow_spec",
        provider_hints=("BrowserAct",),
        allowed_tools=("browseract.build_workflow_spec", "artifact_repository"),
    )
    assert route.provider_key == "browseract"
    assert route.capability_key == "workflow_spec_build"
    assert route.tool_name == "browseract.build_workflow_spec"
    assert route.executable is True


def test_provider_registry_rejects_non_executable_capability_route() -> None:
    registry = ProviderRegistryService()
    with pytest.raises(ToolExecutionError, match="provider_capability_unavailable:prompt_refine"):
        registry.route_tool_by_capability(
            capability_key="prompt_refine",
            provider_hints=("prompting_systems",),
            allowed_tools=("provider.prompting_systems.prompt_refine",),
        )


def test_planner_rejects_non_executable_provider_capability_routes() -> None:
    contracts = TaskContractService(InMemoryTaskContractRepository())
    contracts.upsert_contract(
        task_key="prompt_refine_attempt",
        deliverable_type="refined_prompt",
        default_risk_class="low",
        default_approval_class="none",
        allowed_tools=("provider.prompting_systems.prompt_refine", "artifact_repository"),
        memory_write_policy="none",
        budget_policy_json={
            "class": "low",
            "workflow_template": "tool_then_artifact",
            "pre_artifact_capability_key": "prompt_refine",
            "skill_catalog_json": {"provider_hints_json": {"preferred": ["prompting_systems"]}},
        },
    )
    planner = PlannerService(contracts)

    with pytest.raises(PlanValidationError, match="provider_capability_unavailable:prompt_refine"):
        planner.build_plan(
            task_key="prompt_refine_attempt",
            principal_id="exec-1",
            goal="try a non-executable provider capability",
        )
