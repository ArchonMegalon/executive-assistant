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
