from __future__ import annotations

import pytest

from app.domain.models import PlanValidationError
from app.repositories.provider_bindings import InMemoryProviderBindingRepository
from app.services.planner import PlannerService
from app.services.provider_registry import ProviderRegistryService
from app.services.task_contracts import TaskContractService
from app.repositories.task_contracts import InMemoryTaskContractRepository


def test_planner_uses_task_contract_defaults() -> None:
    contracts = TaskContractService(InMemoryTaskContractRepository())
    contracts.upsert_contract(
        task_key="rewrite_text",
        deliverable_type="rewrite_note",
        default_risk_class="low",
        default_approval_class="manager",
        allowed_tools=("artifact_repository",),
        memory_write_policy="reviewed_only",
        budget_policy_json={"class": "low"},
    )
    planner = PlannerService(contracts)
    intent, plan = planner.build_plan(task_key="rewrite_text", principal_id="exec-1", goal="rewrite")
    assert intent.task_type == "rewrite_text"
    assert intent.approval_class == "manager"
    assert intent.allowed_tools == ("artifact_repository",)
    assert len(plan.steps) == 3
    assert plan.steps[0].step_key == "step_input_prepare"
    assert plan.steps[0].tool_name == ""
    assert plan.steps[0].owner == "system"
    assert plan.steps[0].authority_class == "observe"
    assert plan.steps[0].review_class == "none"
    assert plan.steps[0].failure_strategy == "fail"
    assert plan.steps[0].timeout_budget_seconds == 30
    assert plan.steps[0].max_attempts == 1
    assert plan.steps[0].retry_backoff_seconds == 0
    assert plan.steps[0].output_keys == ("normalized_text", "text_length")
    assert plan.steps[0].approval_required is False
    assert plan.steps[1].step_key == "step_policy_evaluate"
    assert plan.steps[1].step_kind == "policy_check"
    assert plan.steps[1].depends_on == ("step_input_prepare",)
    assert plan.steps[1].owner == "system"
    assert plan.steps[1].authority_class == "observe"
    assert plan.steps[1].timeout_budget_seconds == 30
    assert plan.steps[2].tool_name == "artifact_repository"
    assert plan.steps[2].depends_on == ("step_policy_evaluate",)
    assert plan.steps[2].owner == "tool"
    assert plan.steps[2].authority_class == "draft"
    assert plan.steps[2].review_class == "none"
    assert plan.steps[2].failure_strategy == "fail"
    assert plan.steps[2].timeout_budget_seconds == 60
    assert plan.steps[2].approval_required is True


def test_planner_can_compile_human_review_branch_from_task_contract_metadata() -> None:
    contracts = TaskContractService(InMemoryTaskContractRepository())
    contracts.upsert_contract(
        task_key="rewrite_review",
        deliverable_type="rewrite_note",
        default_risk_class="low",
        default_approval_class="none",
        allowed_tools=("artifact_repository",),
        memory_write_policy="reviewed_only",
        budget_policy_json={
            "class": "low",
            "human_review_role": "communications_reviewer",
            "human_review_task_type": "communications_review",
            "human_review_brief": "Review the rewrite before finalizing it.",
            "human_review_priority": "high",
            "human_review_sla_minutes": 45,
            "human_review_auto_assign_if_unique": True,
            "human_review_desired_output_json": {
                "format": "review_packet",
                "escalation_policy": "manager_review",
            },
            "human_review_authority_required": "send_on_behalf_review",
            "human_review_why_human": "Executive-facing rewrite needs human judgment before finalization.",
            "human_review_quality_rubric_json": {
                "checks": ["tone", "accuracy", "stakeholder_sensitivity"]
            },
        },
    )
    planner = PlannerService(contracts)
    _, plan = planner.build_plan(task_key="rewrite_review", principal_id="exec-1", goal="review this rewrite")

    assert len(plan.steps) == 4
    assert plan.steps[2].step_key == "step_human_review"
    assert plan.steps[2].step_kind == "human_task"
    assert plan.steps[2].depends_on == ("step_policy_evaluate",)
    assert plan.steps[2].owner == "human"
    assert plan.steps[2].authority_class == "draft"
    assert plan.steps[2].review_class == "operator"
    assert plan.steps[2].failure_strategy == "fail"
    assert plan.steps[2].timeout_budget_seconds == 3600
    assert plan.steps[2].max_attempts == 1
    assert plan.steps[2].retry_backoff_seconds == 0
    assert plan.steps[2].task_type == "communications_review"
    assert plan.steps[2].role_required == "communications_reviewer"
    assert plan.steps[2].priority == "high"
    assert plan.steps[2].sla_minutes == 45
    assert plan.steps[2].auto_assign_if_unique is True
    assert plan.steps[2].desired_output_json["escalation_policy"] == "manager_review"
    assert plan.steps[2].authority_required == "send_on_behalf_review"
    assert plan.steps[2].why_human == "Executive-facing rewrite needs human judgment before finalization."
    assert plan.steps[2].quality_rubric_json["checks"][0] == "tone"
    assert plan.steps[3].step_key == "step_artifact_save"
    assert plan.steps[3].depends_on == ("step_human_review",)


def test_planner_can_compile_artifact_retry_policy_from_task_contract_metadata() -> None:
    contracts = TaskContractService(InMemoryTaskContractRepository())
    contracts.upsert_contract(
        task_key="rewrite_retry",
        deliverable_type="rewrite_note",
        default_risk_class="low",
        default_approval_class="none",
        allowed_tools=("artifact_repository",),
        memory_write_policy="reviewed_only",
        budget_policy_json={
            "class": "low",
            "artifact_failure_strategy": "retry",
            "artifact_max_attempts": 3,
            "artifact_retry_backoff_seconds": 15,
        },
    )
    planner = PlannerService(contracts)

    _, plan = planner.build_plan(task_key="rewrite_retry", principal_id="exec-1", goal="retry this rewrite")

    artifact_step = plan.steps[-1]
    assert artifact_step.step_key == "step_artifact_save"
    assert artifact_step.failure_strategy == "retry"
    assert artifact_step.max_attempts == 3
    assert artifact_step.retry_backoff_seconds == 15


def test_planner_inserts_posthoc_review_light_step_after_structured_generate(monkeypatch) -> None:
    monkeypatch.setenv("EA_GEMINI_VORTEX_COMMAND", "python3")
    monkeypatch.setenv("BROWSERACT_API_KEY", "browseract-key")
    contracts = TaskContractService(InMemoryTaskContractRepository())
    contracts.upsert_contract(
        task_key="groundwork_review",
        deliverable_type="rewrite_note",
        default_risk_class="low",
        default_approval_class="none",
        allowed_tools=("provider.gemini_vortex.structured_generate", "browseract.chatplayground_audit", "artifact_repository"),
        memory_write_policy="reviewed_only",
        runtime_policy_json={
            "workflow_template": "tool_then_artifact",
            "pre_artifact_capability_key": "structured_generate",
            "brain_profile": "groundwork",
            "posthoc_review_profile": "review_light",
        },
    )
    planner = PlannerService(contracts)

    _, plan = planner.build_plan(task_key="groundwork_review", principal_id="exec-1", goal="review this synthesis")

    assert [step.step_key for step in plan.steps] == [
        "step_input_prepare",
        "step_structured_generate",
        "step_reasoned_patch_review",
        "step_artifact_save",
    ]
    assert plan.steps[1].tool_name == "provider.brain_router.structured_generate"
    review_step = plan.steps[2]
    artifact_step = plan.steps[3]
    assert review_step.tool_name == "provider.brain_router.reasoned_patch_review"
    assert review_step.brain_profile == "review_light"
    assert artifact_step.depends_on == ("step_reasoned_patch_review", "step_structured_generate")


def test_planner_skips_posthoc_review_light_when_not_allowed(monkeypatch) -> None:
    monkeypatch.setenv("EA_GEMINI_VORTEX_COMMAND", "python3")
    monkeypatch.setenv("BROWSERACT_API_KEY", "browseract-key")
    contracts = TaskContractService(InMemoryTaskContractRepository())
    contracts.upsert_contract(
        task_key="groundwork_review_disallowed",
        deliverable_type="rewrite_note",
        default_risk_class="low",
        default_approval_class="none",
        allowed_tools=("provider.gemini_vortex.structured_generate", "artifact_repository"),
        memory_write_policy="reviewed_only",
        runtime_policy_json={
            "workflow_template": "tool_then_artifact",
            "pre_artifact_capability_key": "structured_generate",
            "brain_profile": "groundwork",
            "posthoc_review_profile": "review_light",
        },
    )
    planner = PlannerService(contracts)

    _, plan = planner.build_plan(task_key="groundwork_review_disallowed", principal_id="exec-1", goal="review this synthesis")

    assert [step.step_key for step in plan.steps] == [
        "step_input_prepare",
        "step_structured_generate",
        "step_artifact_save",
    ]


def test_planner_explicit_posthoc_review_profile_fails_closed_when_unavailable(monkeypatch) -> None:
    monkeypatch.setenv("EA_GEMINI_VORTEX_COMMAND", "python3")
    monkeypatch.delenv("BROWSERACT_API_KEY", raising=False)
    contracts = TaskContractService(InMemoryTaskContractRepository())
    contracts.upsert_contract(
        task_key="groundwork_review_required",
        deliverable_type="rewrite_note",
        default_risk_class="low",
        default_approval_class="none",
        allowed_tools=("provider.gemini_vortex.structured_generate", "browseract.chatplayground_audit", "artifact_repository"),
        memory_write_policy="reviewed_only",
        runtime_policy_json={
            "workflow_template": "tool_then_artifact",
            "pre_artifact_capability_key": "structured_generate",
            "brain_profile": "groundwork",
            "posthoc_review_profile": "review_light",
        },
    )
    planner = PlannerService(contracts)

    with pytest.raises(PlanValidationError, match="brain_profile_provider_unavailable:review_light:reasoned_patch_review"):
        planner.build_plan(task_key="groundwork_review_required", principal_id="exec-1", goal="review this synthesis")


def test_planner_explicit_pre_artifact_tool_honors_principal_provider_state() -> None:
    bindings = InMemoryProviderBindingRepository()
    bindings.upsert(principal_id="exec-1", provider_key="browseract", status="disabled")
    contracts = TaskContractService(InMemoryTaskContractRepository())
    contracts.upsert_contract(
        task_key="explicit_browseract_extract",
        deliverable_type="rewrite_note",
        default_risk_class="low",
        default_approval_class="none",
        allowed_tools=("browseract.extract_account_facts", "artifact_repository"),
        memory_write_policy="none",
        runtime_policy_json={
            "workflow_template": "tool_then_artifact",
            "pre_artifact_tool_name": "browseract.extract_account_facts",
        },
    )
    planner = PlannerService(
        contracts,
        provider_registry=ProviderRegistryService(provider_binding_repo=bindings),
    )

    with pytest.raises(PlanValidationError, match="provider_tool_unavailable:browseract.extract_account_facts"):
        planner.build_plan(task_key="explicit_browseract_extract", principal_id="exec-1", goal="collect facts")


def test_builtin_groundwork_contract_builds_tool_then_artifact_plan(monkeypatch) -> None:
    monkeypatch.setenv("EA_GEMINI_VORTEX_COMMAND", "python3")
    monkeypatch.setenv("BROWSERACT_API_KEY", "browseract-key")
    planner = PlannerService(TaskContractService(InMemoryTaskContractRepository()))

    _, plan = planner.build_plan(task_key="meeting_prep", principal_id="exec-1", goal="prepare a meeting brief")

    assert [step.step_key for step in plan.steps] == [
        "step_input_prepare",
        "step_structured_generate",
        "step_reasoned_patch_review",
        "step_artifact_save",
    ]
    assert plan.steps[1].tool_name == "provider.brain_router.structured_generate"
    assert plan.steps[2].tool_name == "provider.brain_router.reasoned_patch_review"


def test_builtin_groundwork_contract_skips_optional_review_when_unavailable(monkeypatch) -> None:
    monkeypatch.setenv("EA_GEMINI_VORTEX_COMMAND", "python3")
    monkeypatch.delenv("BROWSERACT_API_KEY", raising=False)
    planner = PlannerService(TaskContractService(InMemoryTaskContractRepository()))

    _, plan = planner.build_plan(task_key="meeting_prep", principal_id="exec-1", goal="prepare a meeting brief")

    assert [step.step_key for step in plan.steps] == [
        "step_input_prepare",
        "step_structured_generate",
        "step_artifact_save",
    ]
    assert plan.steps[1].tool_name == "provider.brain_router.structured_generate"


def test_builtin_gm_ops_contract_builds_tool_then_artifact_plan(monkeypatch) -> None:
    monkeypatch.setenv("EA_GEMINI_VORTEX_COMMAND", "python3")
    monkeypatch.setenv("BROWSERACT_API_KEY", "browseract-key")
    planner = PlannerService(TaskContractService(InMemoryTaskContractRepository()))

    intent, plan = planner.build_plan(
        task_key="opposition_packet",
        principal_id="exec-1",
        goal="prepare the next opposition packet and roster movement notes",
    )

    assert intent.task_type == "opposition_packet"
    assert intent.deliverable_type == "opposition_packet"
    assert [step.step_key for step in plan.steps] == [
        "step_input_prepare",
        "step_structured_generate",
        "step_reasoned_patch_review",
        "step_artifact_save",
    ]
    assert plan.steps[1].tool_name == "provider.brain_router.structured_generate"
    assert plan.steps[2].tool_name == "provider.brain_router.reasoned_patch_review"


def test_builtin_campaign_return_loop_contract_builds_tool_then_artifact_plan(monkeypatch) -> None:
    monkeypatch.setenv("EA_GEMINI_VORTEX_COMMAND", "python3")
    monkeypatch.setenv("BROWSERACT_API_KEY", "browseract-key")
    planner = PlannerService(TaskContractService(InMemoryTaskContractRepository()))

    intent, plan = planner.build_plan(
        task_key="campaign_return_loop_brief",
        principal_id="exec-1",
        goal="prepare downtime, diary, contacts, heat, aftermath, and return continuity notes",
    )

    assert intent.task_type == "campaign_return_loop_brief"
    assert intent.deliverable_type == "campaign_return_loop_brief"
    assert [step.step_key for step in plan.steps] == [
        "step_input_prepare",
        "step_structured_generate",
        "step_reasoned_patch_review",
        "step_artifact_save",
    ]
    assert plan.steps[1].tool_name == "provider.brain_router.structured_generate"
    assert plan.steps[2].tool_name == "provider.brain_router.reasoned_patch_review"


@pytest.mark.parametrize(
    ("task_key", "goal"),
    [
        ("campaign_safehouse_readiness_brief", "prepare safehouse readiness continuity notes"),
        ("campaign_travel_continuity_packet", "prepare travel continuity packet notes"),
        ("campaign_offline_continuity_brief", "prepare offline continuity notes"),
        ("campaign_mobile_companion_brief", "prepare mobile companion continuity notes"),
    ],
)
def test_builtin_campaign_mobile_continuity_contracts_build_tool_then_artifact_plan(
    monkeypatch,
    task_key: str,
    goal: str,
) -> None:
    monkeypatch.setenv("EA_GEMINI_VORTEX_COMMAND", "python3")
    monkeypatch.setenv("BROWSERACT_API_KEY", "browseract-key")
    planner = PlannerService(TaskContractService(InMemoryTaskContractRepository()))

    intent, plan = planner.build_plan(
        task_key=task_key,
        principal_id="exec-1",
        goal=goal,
    )

    assert intent.task_type == task_key
    assert intent.deliverable_type == task_key
    assert [step.step_key for step in plan.steps] == [
        "step_input_prepare",
        "step_structured_generate",
        "step_reasoned_patch_review",
        "step_artifact_save",
    ]
    assert plan.steps[1].tool_name == "provider.brain_router.structured_generate"
    assert plan.steps[2].tool_name == "provider.brain_router.reasoned_patch_review"


@pytest.mark.parametrize(
    ("task_key", "goal", "deliverable_type"),
    [
        ("gm_ops_briefing", "prepare gm operations briefing notes", "gm_ops_brief"),
        ("opposition_packet", "prepare opposition packet notes", "opposition_packet"),
        ("roster_movement_plan", "prepare roster movement plan notes", "roster_movement_plan"),
        ("prep_library_packet", "prepare prep library packet notes", "prep_library_packet"),
        ("event_control_brief", "prepare event control briefing notes", "event_control_brief"),
        ("campaign_downtime_plan", "prepare campaign downtime plan notes", "campaign_downtime_plan"),
        ("campaign_diary_packet", "prepare campaign diary packet notes", "campaign_diary_packet"),
        ("campaign_contacts_update", "prepare campaign contacts update notes", "campaign_contacts_update"),
        ("campaign_heat_brief", "prepare campaign heat brief notes", "campaign_heat_brief"),
        ("campaign_aftermath_packet", "prepare campaign aftermath packet notes", "campaign_aftermath_packet"),
        ("campaign_return_loop_brief", "prepare campaign return loop notes", "campaign_return_loop_brief"),
        ("campaign_safehouse_readiness_brief", "prepare safehouse readiness continuity notes", "campaign_safehouse_readiness_brief"),
        ("campaign_travel_continuity_packet", "prepare travel continuity packet notes", "campaign_travel_continuity_packet"),
        ("campaign_offline_continuity_brief", "prepare offline continuity notes", "campaign_offline_continuity_brief"),
        ("campaign_mobile_companion_brief", "prepare mobile companion continuity notes", "campaign_mobile_companion_brief"),
    ],
)
def test_builtin_campaign_and_gm_ops_contracts_compile_tool_then_artifact_plan(
    monkeypatch,
    task_key: str,
    goal: str,
    deliverable_type: str,
) -> None:
    monkeypatch.setenv("EA_GEMINI_VORTEX_COMMAND", "python3")
    monkeypatch.setenv("BROWSERACT_API_KEY", "browseract-key")
    planner = PlannerService(TaskContractService(InMemoryTaskContractRepository()))

    intent, plan = planner.build_plan(
        task_key=task_key,
        principal_id="exec-1",
        goal=goal,
    )

    assert intent.task_type == task_key
    assert intent.deliverable_type == deliverable_type
    assert [step.step_key for step in plan.steps] == [
        "step_input_prepare",
        "step_structured_generate",
        "step_reasoned_patch_review",
        "step_artifact_save",
    ]
    assert plan.steps[1].tool_name == "provider.brain_router.structured_generate"
    assert plan.steps[2].tool_name == "provider.brain_router.reasoned_patch_review"
