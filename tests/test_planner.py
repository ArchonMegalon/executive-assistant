from __future__ import annotations

from app.services.planner import PlannerService
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
    assert plan.steps[0].output_keys == ("normalized_text", "text_length")
    assert plan.steps[0].approval_required is False
    assert plan.steps[1].step_key == "step_policy_evaluate"
    assert plan.steps[1].step_kind == "policy_check"
    assert plan.steps[1].depends_on == ("step_input_prepare",)
    assert plan.steps[2].tool_name == "artifact_repository"
    assert plan.steps[2].depends_on == ("step_policy_evaluate",)
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
        },
    )
    planner = PlannerService(contracts)
    _, plan = planner.build_plan(task_key="rewrite_review", principal_id="exec-1", goal="review this rewrite")

    assert len(plan.steps) == 4
    assert plan.steps[2].step_key == "step_human_review"
    assert plan.steps[2].step_kind == "human_task"
    assert plan.steps[2].depends_on == ("step_policy_evaluate",)
    assert plan.steps[2].task_type == "communications_review"
    assert plan.steps[2].role_required == "communications_reviewer"
    assert plan.steps[3].step_key == "step_artifact_save"
    assert plan.steps[3].depends_on == ("step_human_review",)
