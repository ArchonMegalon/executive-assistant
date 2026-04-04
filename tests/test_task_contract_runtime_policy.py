from __future__ import annotations

import pytest

from app.domain.models import TaskContract, now_utc_iso
from app.repositories.task_contracts import InMemoryTaskContractRepository
from app.services.task_contracts import TaskContractService


def test_task_contract_runtime_policy_parses_typed_metadata() -> None:
    contract = TaskContract(
        task_key="stakeholder_review_dispatch",
        deliverable_type="stakeholder_briefing",
        default_risk_class="low",
        default_approval_class="none",
        allowed_tools=("artifact_repository", "connector.dispatch"),
        evidence_requirements=("stakeholder_context",),
        memory_write_policy="reviewed_only",
        budget_policy_json={
            "class": "medium",
            "workflow_template": "artifact_then_dispatch_then_memory_candidate",
            "pre_artifact_tool_name": "browseract.extract_account_inventory",
            "browseract_timeout_budget_seconds": "75",
            "post_artifact_packs": ["dispatch", "memory_candidate"],
            "artifact_failure_strategy": "retry",
            "artifact_max_attempts": "3",
            "artifact_retry_backoff_seconds": "20",
            "dispatch_failure_strategy": "fallback_human",
            "dispatch_max_attempts": 2,
            "dispatch_retry_backoff_seconds": 5,
            "human_review_role": "briefing_reviewer",
            "human_review_task_type": "briefing_review",
            "human_review_sla_minutes": "45",
            "human_review_auto_assign_if_unique": "true",
            "memory_candidate_category": "stakeholder_fact",
            "memory_candidate_confidence": "0.8",
            "memory_candidate_sensitivity": "internal",
            "artifact_output_template": "evidence_pack",
            "evidence_pack_confidence": "0.7",
            "skill_catalog_json": {
                "skill_key": "stakeholder_dispatch",
                "name": "Stakeholder Dispatch",
                "memory_reads": ["stakeholders", "commitments"],
                "memory_writes": ["stakeholder_fact"],
                "tags": ["stakeholder", "dispatch"],
                "provider_hints_json": {"primary": ["BrowserAct"]},
                "evaluation_cases_json": [{"case_key": "golden", "priority": "high"}],
            },
        },
        updated_at=now_utc_iso(),
    )

    policy = contract.runtime_policy()

    assert policy.budget_class == "medium"
    assert policy.workflow_template_key == "artifact_then_dispatch_then_memory_candidate"
    assert policy.pre_artifact_tool_name == "browseract.extract_account_inventory"
    assert policy.browseract_timeout_budget_seconds == 75
    assert policy.post_artifact_packs == ("dispatch", "memory_candidate")
    assert policy.artifact_retry.failure_strategy == "retry"
    assert policy.artifact_retry.max_attempts == 3
    assert policy.dispatch_retry.failure_strategy == "fallback_human"
    assert policy.human_review.role == "briefing_reviewer"
    assert policy.human_review.auto_assign_if_unique is True
    assert policy.memory_candidate.category == "stakeholder_fact"
    assert policy.memory_candidate.confidence == 0.8
    assert policy.artifact_output.template == "evidence_pack"
    assert policy.artifact_output.default_confidence == 0.7
    assert policy.skill_catalog.skill_key == "stakeholder_dispatch"
    assert policy.skill_catalog.memory_reads == ("stakeholders", "commitments")
    assert policy.skill_catalog.provider_hints_json["primary"] == ["BrowserAct"]


def test_task_contract_runtime_policy_applies_safe_defaults_for_invalid_values() -> None:
    contract = TaskContract(
        task_key="rewrite_text",
        deliverable_type="rewrite_note",
        default_risk_class="low",
        default_approval_class="none",
        allowed_tools=("artifact_repository",),
        evidence_requirements=(),
        memory_write_policy="reviewed_only",
        budget_policy_json={
            "artifact_failure_strategy": "not_real",
            "artifact_max_attempts": -4,
            "artifact_retry_backoff_seconds": -10,
            "browseract_timeout_budget_seconds": -3,
            "memory_candidate_confidence": 9.5,
            "human_review_desired_output_json": {"extra": "value"},
            "skill_catalog_json": {
                "memory_reads": "not-a-list",
                "evaluation_cases_json": "not-a-list",
            },
        },
        updated_at=now_utc_iso(),
    )

    policy = contract.runtime_policy()

    assert policy.artifact_retry.failure_strategy == "fail"
    assert policy.artifact_retry.max_attempts == 1
    assert policy.artifact_retry.retry_backoff_seconds == 0
    assert policy.browseract_timeout_budget_seconds == 120
    assert policy.memory_candidate.confidence == 1.0
    assert policy.human_review.desired_output_json["format"] == "review_packet"
    assert policy.skill_catalog.memory_reads == ()
    assert policy.skill_catalog.evaluation_cases_json == ()


def test_task_contract_runtime_policy_prefers_typed_runtime_policy_json() -> None:
    contract = TaskContract(
        task_key="rewrite_text",
        deliverable_type="rewrite_note",
        default_risk_class="low",
        default_approval_class="none",
        allowed_tools=("artifact_repository",),
        evidence_requirements=(),
        memory_write_policy="reviewed_only",
        budget_policy_json={"class": "low", "workflow_template": "rewrite"},
        runtime_policy_json={"class": "medium", "workflow_template": "artifact_then_packs"},
        updated_at=now_utc_iso(),
    )

    policy = contract.runtime_policy()

    assert policy.budget_class == "medium"
    assert policy.workflow_template_key == "artifact_then_packs"


def test_task_contract_service_persists_runtime_policy_separately_from_budget_policy() -> None:
    service = TaskContractService(InMemoryTaskContractRepository())

    contract = service.upsert_contract(
        task_key="rewrite_text",
        deliverable_type="rewrite_note",
        default_risk_class="low",
        default_approval_class="none",
        allowed_tools=("artifact_repository",),
        memory_write_policy="reviewed_only",
        budget_policy_json={"class": "low", "legacy_only": True},
        runtime_policy_json={"workflow_template": "artifact_then_dispatch", "class": "medium"},
    )

    assert contract.budget_policy_json == {"class": "low", "legacy_only": True}
    assert contract.runtime_policy_json["workflow_template"] == "artifact_then_dispatch"
    assert contract.runtime_policy().budget_class == "medium"


def test_task_contract_runtime_policy_deep_merges_nested_skill_catalog_fields() -> None:
    contract = TaskContract(
        task_key="rewrite_text",
        deliverable_type="rewrite_note",
        default_risk_class="low",
        default_approval_class="none",
        allowed_tools=("artifact_repository",),
        evidence_requirements=(),
        memory_write_policy="reviewed_only",
        budget_policy_json={
            "skill_catalog_json": {
                "skill_key": "rewrite_text",
                "provider_hints_json": {"primary": ["BrowserAct"]},
                "model_policy_json": {"brain_profile": "groundwork"},
            }
        },
        runtime_policy_json={
            "skill_catalog_json": {
                "provider_hints_json": {"secondary": ["gemini_vortex"]},
            }
        },
        updated_at=now_utc_iso(),
    )

    policy = contract.runtime_policy()

    assert policy.skill_catalog.skill_key == "rewrite_text"
    assert policy.skill_catalog.model_policy_json["brain_profile"] == "groundwork"
    assert policy.skill_catalog.provider_hints_json["primary"] == ["BrowserAct"]
    assert policy.skill_catalog.provider_hints_json["secondary"] == ["gemini_vortex"]


@pytest.mark.parametrize(
    ("task_key", "deliverable_type"),
    [
        ("gm_ops_briefing", "gm_ops_brief"),
        ("opposition_packet", "opposition_packet"),
        ("roster_movement_plan", "roster_movement_plan"),
        ("prep_library_packet", "prep_library_packet"),
        ("event_control_brief", "event_control_brief"),
        ("campaign_downtime_plan", "campaign_downtime_plan"),
        ("campaign_diary_packet", "campaign_diary_packet"),
        ("campaign_contacts_update", "campaign_contacts_update"),
        ("campaign_heat_brief", "campaign_heat_brief"),
        ("campaign_aftermath_packet", "campaign_aftermath_packet"),
        ("campaign_return_loop_brief", "campaign_return_loop_brief"),
        ("campaign_safehouse_readiness_brief", "campaign_safehouse_readiness_brief"),
        ("campaign_travel_continuity_packet", "campaign_travel_continuity_packet"),
        ("campaign_offline_continuity_brief", "campaign_offline_continuity_brief"),
        ("campaign_mobile_companion_brief", "campaign_mobile_companion_brief"),
    ],
)
def test_builtin_w3_campaign_and_gm_contracts_resolve_with_groundwork_runtime_policy(
    task_key: str,
    deliverable_type: str,
) -> None:
    service = TaskContractService(InMemoryTaskContractRepository())

    contract = service.get_contract_or_raise(task_key)

    assert contract.task_key == task_key
    assert contract.deliverable_type == deliverable_type
    assert "provider.gemini_vortex.structured_generate" in contract.allowed_tools
    assert "artifact_repository" in contract.allowed_tools

    runtime_policy = contract.runtime_policy()
    assert runtime_policy.workflow_template_key == "tool_then_artifact"
    assert runtime_policy.pre_artifact_capability_key == "structured_generate"
    assert runtime_policy.brain_profile == "groundwork"
    assert runtime_policy.posthoc_review_profile == "review_light"
    assert runtime_policy.artifact_output.template == "groundwork_brief"
