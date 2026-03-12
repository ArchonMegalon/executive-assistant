from __future__ import annotations

from app.domain.models import SkillContract
from app.services.provider_registry import ProviderRegistryService


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
        provider_hints_json={"preferred": ["browseract"]},
        tool_policy_json={},
        human_policy_json={},
        evaluation_cases_json=(),
        updated_at="2026-03-12T00:00:00Z",
    )
    bindings = registry.bindings_for_skill(skill)
    keys = {binding.provider_key for binding in bindings}
    assert "browseract" in keys
    assert "artifact_repository" in keys
