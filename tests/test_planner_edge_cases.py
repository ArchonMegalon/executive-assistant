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
