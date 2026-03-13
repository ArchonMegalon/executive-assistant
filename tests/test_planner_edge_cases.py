from __future__ import annotations

from app.repositories.task_contracts import InMemoryTaskContractRepository
from app.services.planner import PlannerService
from app.services.task_contracts import TaskContractService


def test_artifact_then_memory_candidate_keeps_dispatch_pack_when_requested() -> None:
    contracts = TaskContractService(InMemoryTaskContractRepository())
    contracts.upsert_contract(
        task_key="artifact_memory_dispatch",
        deliverable_type="rewrite_note",
        default_risk_class="low",
        default_approval_class="none",
        allowed_tools=("artifact_repository", "connector.dispatch"),
        memory_write_policy="reviewed_only",
        budget_policy_json={
            "class": "low",
            "workflow_template": "artifact_then_memory_candidate",
            "post_artifact_packs": ["dispatch", "memory_candidate"],
        },
    )
    planner = PlannerService(contracts)
    _, plan = planner.build_plan(
        task_key="artifact_memory_dispatch",
        principal_id="exec-1",
        goal="exercise edge case",
    )
    step_keys = [step.step_key for step in plan.steps]
    assert step_keys == [
        "step_input_prepare",
        "step_policy_evaluate",
        "step_artifact_save",
        "step_connector_dispatch",
        "step_memory_candidate_stage",
    ]


def test_tool_then_artifact_routes_pre_artifact_tool_via_capability() -> None:
    contracts = TaskContractService(InMemoryTaskContractRepository())
    contracts.upsert_contract(
        task_key="inventory_capture",
        deliverable_type="inventory_report",
        default_risk_class="low",
        default_approval_class="none",
        allowed_tools=("browseract.extract_account_inventory", "artifact_repository"),
        memory_write_policy="none",
        budget_policy_json={
            "class": "low",
            "workflow_template": "tool_then_artifact",
            "pre_artifact_tool_name": "not.real.tool",
            "pre_artifact_capability_key": "account_inventory",
            "skill_catalog_json": {"provider_hints_json": {"preferred": ["browseract"]}},
        },
    )
    planner = PlannerService(contracts)
    _, plan = planner.build_plan(
        task_key="inventory_capture",
        principal_id="exec-1",
        goal="capture inventory",
    )
    assert [step.step_key for step in plan.steps] == [
        "step_input_prepare",
        "step_browseract_inventory_extract",
        "step_artifact_save",
    ]
    assert plan.steps[1].tool_name == "browseract.extract_account_inventory"
