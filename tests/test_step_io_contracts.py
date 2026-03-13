from __future__ import annotations

import pytest

from app.domain.models import IntentSpecV3, PlanSpec, PlanStepSpec, TaskExecutionRequest, now_utc_iso
from app.repositories.artifacts import InMemoryArtifactRepository
from app.repositories.connector_bindings import InMemoryConnectorBindingRepository
from app.repositories.ledger import InMemoryExecutionLedgerRepository
from app.repositories.tool_registry import InMemoryToolRegistryRepository
from app.services.orchestrator import RewriteOrchestrator
from app.services.tool_execution import ToolExecutionService
from app.services.tool_runtime import ToolRuntimeService


def _tool_execution_with_artifacts(artifacts: InMemoryArtifactRepository) -> ToolExecutionService:
    return ToolExecutionService(
        tool_runtime=ToolRuntimeService(
            tool_registry=InMemoryToolRegistryRepository(),
            connector_bindings=InMemoryConnectorBindingRepository(),
        ),
        artifacts=artifacts,
    )


def _intent() -> IntentSpecV3:
    return IntentSpecV3(
        principal_id="exec-1",
        goal="rewrite this",
        task_type="rewrite_text",
        deliverable_type="rewrite_note",
        risk_class="low",
        approval_class="none",
        budget_class="low",
        allowed_tools=("artifact_repository",),
        desired_artifact="rewrite_note",
    )


def test_merged_step_input_json_filters_dependency_outputs_to_declared_input_keys() -> None:
    ledger = InMemoryExecutionLedgerRepository()
    artifacts = InMemoryArtifactRepository()
    orchestrator = RewriteOrchestrator(
        artifacts=artifacts,
        ledger=ledger,
        tool_execution=_tool_execution_with_artifacts(artifacts),
    )
    session = ledger.start_session(_intent())
    dependency = ledger.start_step(
        session.session_id,
        "system_task",
        input_json={"plan_step_key": "step_input_prepare", "output_keys": ["normalized_text", "text_length"]},
    )
    ledger.update_step(
        dependency.step_id,
        state="completed",
        output_json={
            "normalized_text": "Prepared text",
            "text_length": 13,
            "leaked_value": "should_not_flow",
        },
        error_json={},
    )
    child = ledger.start_step(
        session.session_id,
        "tool_call",
        input_json={
            "plan_step_key": "step_artifact_save",
            "depends_on": ["step_input_prepare"],
            "input_keys": ["normalized_text"],
            "output_keys": ["artifact_id", "receipt_id", "cost_id"],
        },
    )

    merged = orchestrator._merged_step_input_json(session.session_id, child)

    assert merged["normalized_text"] == "Prepared text"
    assert merged["source_text"] == "Prepared text"
    assert "leaked_value" not in merged


def test_merged_step_input_json_rejects_missing_declared_inputs() -> None:
    ledger = InMemoryExecutionLedgerRepository()
    artifacts = InMemoryArtifactRepository()
    orchestrator = RewriteOrchestrator(
        artifacts=artifacts,
        ledger=ledger,
        tool_execution=_tool_execution_with_artifacts(artifacts),
    )
    session = ledger.start_session(_intent())
    child = ledger.start_step(
        session.session_id,
        "policy_check",
        input_json={
            "plan_step_key": "step_policy_evaluate",
            "input_keys": ["normalized_text", "text_length"],
            "output_keys": ["allow", "requires_approval", "reason", "retention_policy", "memory_write_allowed"],
        },
    )

    with pytest.raises(RuntimeError, match="missing_step_input:step_policy_evaluate:normalized_text"):
        orchestrator._merged_step_input_json(session.session_id, child)


class _OutputContractPlanner:
    def build_plan(self, *, task_key: str, principal_id: str, goal: str):
        intent = _intent()
        plan = PlanSpec(
            plan_id="plan-output-contract",
            task_key=task_key,
            principal_id=principal_id,
            created_at=now_utc_iso(),
            steps=(
                PlanStepSpec(
                    step_key="step_input_prepare",
                    step_kind="system_task",
                    tool_name="",
                    evidence_required=(),
                    approval_required=False,
                    reversible=False,
                    expected_artifact="",
                    fallback="fail",
                    input_keys=("source_text",),
                    output_keys=("normalized_text", "text_length"),
                ),
                PlanStepSpec(
                    step_key="step_artifact_save",
                    step_kind="tool_call",
                    tool_name="artifact_repository",
                    evidence_required=(),
                    approval_required=False,
                    reversible=False,
                    expected_artifact="rewrite_note",
                    fallback="fail",
                    depends_on=("step_input_prepare",),
                    input_keys=("normalized_text",),
                    output_keys=("artifact_id", "receipt_id", "cost_id", "missing_output"),
                ),
            ),
        )
        return intent, plan


def test_orchestrator_fails_session_when_declared_step_output_is_missing() -> None:
    ledger = InMemoryExecutionLedgerRepository()
    artifacts = InMemoryArtifactRepository()
    orchestrator = RewriteOrchestrator(
        artifacts=artifacts,
        ledger=ledger,
        planner=_OutputContractPlanner(),
        tool_execution=_tool_execution_with_artifacts(artifacts),
    )

    with pytest.raises(RuntimeError, match="missing_step_output:step_artifact_save:missing_output"):
        orchestrator.execute_task_artifact(
            TaskExecutionRequest(
                task_key="rewrite_text",
                text="Output contracts matter.",
                principal_id="exec-1",
                goal="rewrite this",
            )
        )

    session = next(iter(ledger._sessions.values()))
    assert session.status == "failed"
    failed_step = next(step for step in ledger.steps_for(session.session_id) if step.state == "failed")
    assert failed_step.error_json["detail"] == "missing_step_output:step_artifact_save:missing_output"
