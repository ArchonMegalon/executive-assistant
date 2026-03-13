from __future__ import annotations

import uuid

from app.domain.models import IntentSpecV3, PlanSpec, PlanStepSpec, TaskExecutionRequest, now_utc_iso
from app.repositories.artifacts import InMemoryArtifactRepository
from app.repositories.connector_bindings import InMemoryConnectorBindingRepository
from app.repositories.tool_registry import InMemoryToolRegistryRepository
from app.services.orchestrator import RewriteOrchestrator
from app.services.tool_execution import ToolExecutionService
from app.services.tool_runtime import ToolRuntimeService


class _GraphPlanner:
    def build_plan(
        self,
        *,
        task_key: str,
        principal_id: str,
        goal: str,
    ) -> tuple[IntentSpecV3, PlanSpec]:
        intent = IntentSpecV3(
            principal_id=principal_id,
            goal=goal,
            task_type=task_key,
            deliverable_type="rewrite_note",
            risk_class="low",
            approval_class="none",
            budget_class="low",
            allowed_tools=("artifact_repository",),
        )
        plan = PlanSpec(
            plan_id=str(uuid.uuid4()),
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
                    fallback="request_human_intervention",
                    owner="system",
                    authority_class="observe",
                    review_class="none",
                    failure_strategy="fail",
                    timeout_budget_seconds=30,
                    input_keys=("source_text",),
                    output_keys=("normalized_text", "text_length"),
                ),
                PlanStepSpec(
                    step_key="step_policy_evaluate",
                    step_kind="policy_check",
                    tool_name="",
                    evidence_required=(),
                    approval_required=False,
                    reversible=False,
                    expected_artifact="",
                    fallback="pause_for_approval_or_block",
                    owner="system",
                    authority_class="observe",
                    review_class="none",
                    failure_strategy="fail",
                    timeout_budget_seconds=30,
                    depends_on=("step_input_prepare",),
                    input_keys=("normalized_text", "text_length"),
                    output_keys=("allow", "requires_approval", "reason"),
                ),
                PlanStepSpec(
                    step_key="step_sidecar_save",
                    step_kind="tool_call",
                    tool_name="artifact_repository",
                    evidence_required=(),
                    approval_required=False,
                    reversible=False,
                    fallback="request_human_intervention",
                    owner="tool",
                    authority_class="draft",
                    review_class="none",
                    failure_strategy="fail",
                    timeout_budget_seconds=60,
                    depends_on=("step_input_prepare",),
                    input_keys=("normalized_text",),
                    output_keys=("artifact_id", "receipt_id", "cost_id"),
                    expected_artifact="sidecar_note",
                ),
                PlanStepSpec(
                    step_key="step_artifact_save",
                    step_kind="tool_call",
                    tool_name="artifact_repository",
                    evidence_required=(),
                    approval_required=False,
                    reversible=False,
                    fallback="request_human_intervention",
                    owner="tool",
                    authority_class="draft",
                    review_class="none",
                    failure_strategy="fail",
                    timeout_budget_seconds=60,
                    depends_on=("step_policy_evaluate", "step_sidecar_save"),
                    input_keys=("normalized_text",),
                    output_keys=("artifact_id", "receipt_id", "cost_id"),
                    expected_artifact="rewrite_note",
                ),
            ),
        )
        return intent, plan


def test_parent_step_id_tracks_only_single_dependency_edges() -> None:
    artifacts = InMemoryArtifactRepository()
    orchestrator = RewriteOrchestrator(
        planner=_GraphPlanner(),
        artifacts=artifacts,
        tool_execution=ToolExecutionService(
            tool_runtime=ToolRuntimeService(
                tool_registry=InMemoryToolRegistryRepository(),
                connector_bindings=InMemoryConnectorBindingRepository(),
            ),
            artifacts=artifacts,
        ),
    )

    artifact = orchestrator.execute_task_artifact(
        TaskExecutionRequest(
            task_key="rewrite_text",
            text="graph parent projection",
            principal_id="exec-1",
            goal="exercise graph parent projection",
        )
    )
    session = orchestrator.fetch_session(artifact.execution_session_id)

    assert session is not None
    steps_by_key = {
        str((step.input_json or {}).get("plan_step_key") or ""): step
        for step in session.steps
    }
    input_step = steps_by_key["step_input_prepare"]
    policy_step = steps_by_key["step_policy_evaluate"]
    sidecar_step = steps_by_key["step_sidecar_save"]
    save_step = steps_by_key["step_artifact_save"]

    assert input_step.parent_step_id is None
    assert policy_step.parent_step_id == input_step.step_id
    assert sidecar_step.parent_step_id == input_step.step_id
    assert save_step.parent_step_id is None
    assert tuple((save_step.input_json or {}).get("depends_on") or ()) == ("step_policy_evaluate", "step_sidecar_save")
    assert {row.kind for row in session.artifacts} == {"rewrite_note", "sidecar_note"}
