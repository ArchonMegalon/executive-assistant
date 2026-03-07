from __future__ import annotations

import os

import pytest

from app.domain.models import PlanValidationError, TaskExecutionRequest
from app.repositories.approvals import InMemoryApprovalRepository
from app.repositories.artifacts import InMemoryArtifactRepository
from app.repositories.connector_bindings import InMemoryConnectorBindingRepository
from app.repositories.delivery_outbox import InMemoryDeliveryOutboxRepository
from app.repositories.ledger import InMemoryExecutionLedgerRepository
from app.repositories.observation import InMemoryObservationEventRepository
from app.repositories.policy_decisions import InMemoryPolicyDecisionRepository
from app.repositories.task_contracts import InMemoryTaskContractRepository
from app.repositories.tool_registry import InMemoryToolRegistryRepository
from app.services.channel_runtime import ChannelRuntimeService
from app.services.orchestrator import HumanTaskRequiredError, RewriteOrchestrator
from app.services.planner import PlannerService
from app.services.policy import ApprovalRequiredError, PolicyDecisionService
from app.services.task_contracts import TaskContractService
from app.services.tool_execution import ToolExecutionService
from app.services.tool_runtime import ToolRuntimeService


def _api_client():
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    os.environ["EA_STORAGE_BACKEND"] = "memory"
    os.environ.pop("EA_LEDGER_BACKEND", None)
    os.environ["EA_API_TOKEN"] = ""
    os.environ.pop("DATABASE_URL", None)

    from app.api.app import create_app

    client = TestClient(create_app())
    client.headers.update({"X-EA-Principal-ID": "exec-1"})
    return client


def _step_keys(plan) -> tuple[str, ...]:
    return tuple(step.step_key for step in plan.steps)


def _build_dispatch_runtime(
    *,
    task_key: str = "stakeholder_dispatch",
    budget_policy_json: dict[str, object] | None = None,
) -> tuple[RewriteOrchestrator, ChannelRuntimeService, ToolRuntimeService]:
    task_contracts = TaskContractService(InMemoryTaskContractRepository())
    task_contracts.upsert_contract(
        task_key=task_key,
        deliverable_type="stakeholder_briefing",
        default_risk_class="low",
        default_approval_class="none",
        allowed_tools=("artifact_repository", "connector.dispatch"),
        evidence_requirements=("stakeholder_context",),
        memory_write_policy="reviewed_only",
        budget_policy_json=dict(
            budget_policy_json
            or {"class": "low", "workflow_template": "artifact_then_dispatch"}
        ),
    )
    tool_runtime = ToolRuntimeService(
        tool_registry=InMemoryToolRegistryRepository(),
        connector_bindings=InMemoryConnectorBindingRepository(),
    )
    artifacts = InMemoryArtifactRepository()
    channel_runtime = ChannelRuntimeService(
        observations=InMemoryObservationEventRepository(),
        outbox=InMemoryDeliveryOutboxRepository(),
    )
    orchestrator = RewriteOrchestrator(
        artifacts=artifacts,
        ledger=InMemoryExecutionLedgerRepository(),
        approvals=InMemoryApprovalRepository(),
        policy_repo=InMemoryPolicyDecisionRepository(),
        policy=PolicyDecisionService(),
        task_contracts=task_contracts,
        planner=PlannerService(task_contracts),
        tool_execution=ToolExecutionService(
            tool_runtime=tool_runtime,
            artifacts=artifacts,
            channel_runtime=channel_runtime,
        ),
    )
    return orchestrator, channel_runtime, tool_runtime


def test_planner_can_compile_dispatch_workflow_template() -> None:
    task_contracts = TaskContractService(InMemoryTaskContractRepository())
    task_contracts.upsert_contract(
        task_key="stakeholder_dispatch",
        deliverable_type="stakeholder_briefing",
        default_risk_class="low",
        default_approval_class="none",
        allowed_tools=("artifact_repository", "connector.dispatch"),
        evidence_requirements=("stakeholder_context",),
        memory_write_policy="reviewed_only",
        budget_policy_json={"class": "low", "workflow_template": "artifact_then_dispatch"},
    )
    planner = PlannerService(task_contracts)

    intent, plan = planner.build_plan(
        task_key="stakeholder_dispatch",
        principal_id="exec-1",
        goal="prepare and send a stakeholder briefing",
    )

    assert intent.task_type == "stakeholder_dispatch"
    assert _step_keys(plan) == (
        "step_input_prepare",
        "step_artifact_save",
        "step_policy_evaluate",
        "step_connector_dispatch",
    )
    assert plan.steps[1].tool_name == "artifact_repository"
    assert plan.steps[1].depends_on == ("step_input_prepare",)
    assert plan.steps[2].depends_on == ("step_artifact_save",)
    assert plan.steps[3].tool_name == "connector.dispatch"
    assert plan.steps[3].depends_on == ("step_policy_evaluate",)
    assert plan.steps[3].authority_class == "execute"
    assert plan.steps[3].input_keys == ("binding_id", "channel", "recipient", "content")
    assert plan.steps[3].output_keys == ("delivery_id", "status", "binding_id")


def test_dispatch_workflow_template_pauses_for_approval_after_artifact_persistence() -> None:
    orchestrator, channel_runtime, tool_runtime = _build_dispatch_runtime()
    binding = tool_runtime.upsert_connector_binding(
        principal_id="exec-1",
        connector_name="gmail",
        external_account_ref="acct-1",
        scope_json={"scopes": ["mail.send"]},
        auth_metadata_json={"provider": "google"},
        status="enabled",
    )

    with pytest.raises(ApprovalRequiredError) as exc:
        orchestrator.execute_task_artifact(
            TaskExecutionRequest(
                task_key="stakeholder_dispatch",
                principal_id="exec-1",
                goal="prepare and send a stakeholder briefing",
                input_json={
                    "source_text": "Board context and stakeholder sensitivities.",
                    "binding_id": binding.binding_id,
                    "channel": "email",
                    "recipient": "ops@example.com",
                },
            )
        )
    assert exc.value.session_id
    assert exc.value.approval_id

    snapshot = orchestrator.fetch_session(exc.value.session_id)
    assert snapshot is not None
    assert snapshot.session.status == "awaiting_approval"
    assert [step.input_json["plan_step_key"] for step in snapshot.steps] == [
        "step_input_prepare",
        "step_artifact_save",
        "step_policy_evaluate",
        "step_connector_dispatch",
    ]
    steps_by_key = {step.input_json["plan_step_key"]: step for step in snapshot.steps}
    assert steps_by_key["step_artifact_save"].state == "completed"
    assert steps_by_key["step_policy_evaluate"].state == "completed"
    assert steps_by_key["step_connector_dispatch"].state == "waiting_approval"
    assert len(snapshot.artifacts) == 1
    assert snapshot.artifacts[0].kind == "stakeholder_briefing"
    assert snapshot.artifacts[0].content == "Board context and stakeholder sensitivities."
    assert channel_runtime.list_pending_delivery(limit=10) == []

    decision = orchestrator.decide_approval(
        exc.value.approval_id,
        decision="approve",
        decided_by="operator",
        reason="approved dispatch template",
    )
    assert decision is not None

    resumed = orchestrator.fetch_session(exc.value.session_id)
    assert resumed is not None
    resumed_steps = {step.input_json["plan_step_key"]: step for step in resumed.steps}
    assert resumed.session.status == "completed"
    assert resumed_steps["step_connector_dispatch"].state == "completed"
    assert len(resumed.receipts) == 2
    assert resumed.receipts[-1].tool_name == "connector.dispatch"
    pending = channel_runtime.list_pending_delivery(limit=10)
    assert len(pending) == 1
    assert pending[0].recipient == "ops@example.com"


def test_planner_can_compile_review_then_dispatch_workflow_template() -> None:
    task_contracts = TaskContractService(InMemoryTaskContractRepository())
    task_contracts.upsert_contract(
        task_key="stakeholder_review_dispatch",
        deliverable_type="stakeholder_briefing",
        default_risk_class="low",
        default_approval_class="none",
        allowed_tools=("artifact_repository", "connector.dispatch"),
        evidence_requirements=("stakeholder_context",),
        memory_write_policy="reviewed_only",
        budget_policy_json={
            "class": "low",
            "workflow_template": "artifact_then_dispatch",
            "human_review_role": "communications_reviewer",
            "human_review_task_type": "communications_review",
            "human_review_brief": "Review before stakeholder dispatch.",
            "human_review_priority": "high",
            "human_review_desired_output_json": {"format": "review_packet"},
        },
    )
    planner = PlannerService(task_contracts)

    _, plan = planner.build_plan(
        task_key="stakeholder_review_dispatch",
        principal_id="exec-1",
        goal="review and send a stakeholder briefing",
    )

    assert _step_keys(plan) == (
        "step_input_prepare",
        "step_human_review",
        "step_artifact_save",
        "step_policy_evaluate",
        "step_connector_dispatch",
    )
    assert plan.steps[1].step_kind == "human_task"
    assert plan.steps[1].depends_on == ("step_input_prepare",)
    assert plan.steps[2].depends_on == ("step_human_review",)
    assert plan.steps[3].depends_on == ("step_artifact_save",)
    assert plan.steps[4].depends_on == ("step_policy_evaluate",)


def test_planner_can_compile_dispatch_retry_policy_from_task_contract_metadata() -> None:
    task_contracts = TaskContractService(InMemoryTaskContractRepository())
    task_contracts.upsert_contract(
        task_key="stakeholder_dispatch_retry",
        deliverable_type="stakeholder_briefing",
        default_risk_class="low",
        default_approval_class="none",
        allowed_tools=("artifact_repository", "connector.dispatch"),
        evidence_requirements=("stakeholder_context",),
        memory_write_policy="reviewed_only",
        budget_policy_json={
            "class": "low",
            "workflow_template": "artifact_then_dispatch",
            "dispatch_failure_strategy": "retry",
            "dispatch_max_attempts": 4,
            "dispatch_retry_backoff_seconds": 25,
        },
    )
    planner = PlannerService(task_contracts)

    _, plan = planner.build_plan(
        task_key="stakeholder_dispatch_retry",
        principal_id="exec-1",
        goal="prepare and send a stakeholder briefing",
    )

    dispatch_step = plan.steps[-1]
    assert dispatch_step.step_key == "step_connector_dispatch"
    assert dispatch_step.failure_strategy == "retry"
    assert dispatch_step.max_attempts == 4
    assert dispatch_step.retry_backoff_seconds == 25


def test_planner_can_compile_review_then_dispatch_retry_policy_from_task_contract_metadata() -> None:
    task_contracts = TaskContractService(InMemoryTaskContractRepository())
    task_contracts.upsert_contract(
        task_key="stakeholder_review_dispatch_retry",
        deliverable_type="stakeholder_briefing",
        default_risk_class="low",
        default_approval_class="none",
        allowed_tools=("artifact_repository", "connector.dispatch"),
        evidence_requirements=("stakeholder_context",),
        memory_write_policy="reviewed_only",
        budget_policy_json={
            "class": "low",
            "workflow_template": "artifact_then_dispatch",
            "human_review_role": "communications_reviewer",
            "human_review_task_type": "communications_review",
            "human_review_brief": "Review before stakeholder dispatch.",
            "human_review_priority": "high",
            "human_review_desired_output_json": {"format": "review_packet"},
            "dispatch_failure_strategy": "retry",
            "dispatch_max_attempts": 3,
            "dispatch_retry_backoff_seconds": 45,
        },
    )
    planner = PlannerService(task_contracts)

    _, plan = planner.build_plan(
        task_key="stakeholder_review_dispatch_retry",
        principal_id="exec-1",
        goal="review and send a stakeholder briefing",
    )

    assert _step_keys(plan) == (
        "step_input_prepare",
        "step_human_review",
        "step_artifact_save",
        "step_policy_evaluate",
        "step_connector_dispatch",
    )
    dispatch_step = plan.steps[-1]
    assert dispatch_step.step_key == "step_connector_dispatch"
    assert dispatch_step.failure_strategy == "retry"
    assert dispatch_step.max_attempts == 3
    assert dispatch_step.retry_backoff_seconds == 45


def test_review_then_dispatch_workflow_template_pauses_for_human_then_approval() -> None:
    orchestrator, channel_runtime, tool_runtime = _build_dispatch_runtime(
        task_key="stakeholder_review_dispatch",
        budget_policy_json={
            "class": "low",
            "workflow_template": "artifact_then_dispatch",
            "human_review_role": "communications_reviewer",
            "human_review_task_type": "communications_review",
            "human_review_brief": "Review before stakeholder dispatch.",
            "human_review_priority": "high",
            "human_review_desired_output_json": {"format": "review_packet"},
        },
    )
    binding = tool_runtime.upsert_connector_binding(
        principal_id="exec-1",
        connector_name="gmail",
        external_account_ref="acct-2",
        scope_json={"scopes": ["mail.send"]},
        auth_metadata_json={"provider": "google"},
        status="enabled",
    )

    with pytest.raises(HumanTaskRequiredError) as exc:
        orchestrator.execute_task_artifact(
            TaskExecutionRequest(
                task_key="stakeholder_review_dispatch",
                principal_id="exec-1",
                goal="review and send a stakeholder briefing",
                input_json={
                    "source_text": "Board context and stakeholder sensitivities.",
                    "binding_id": binding.binding_id,
                    "channel": "email",
                    "recipient": "reviewed@example.com",
                },
            )
        )
    assert exc.value.session_id
    assert exc.value.human_task_id

    waiting = orchestrator.fetch_session(exc.value.session_id)
    assert waiting is not None
    waiting_steps = {step.input_json["plan_step_key"]: step for step in waiting.steps}
    assert waiting.session.status == "awaiting_human"
    assert waiting_steps["step_human_review"].state == "waiting_human"
    assert waiting_steps["step_artifact_save"].state == "queued"
    assert waiting.artifacts == []
    assert channel_runtime.list_pending_delivery(limit=10) == []

    returned = orchestrator.return_human_task(
        exc.value.human_task_id,
        principal_id="exec-1",
        operator_id="reviewer-1",
        resolution="ready_for_dispatch",
        returned_payload_json={"final_text": "Reviewed stakeholder briefing."},
        provenance_json={"review_mode": "human"},
    )
    assert returned is not None

    awaiting_approval = orchestrator.fetch_session(exc.value.session_id)
    assert awaiting_approval is not None
    approval_steps = {step.input_json["plan_step_key"]: step for step in awaiting_approval.steps}
    assert awaiting_approval.session.status == "awaiting_approval"
    assert approval_steps["step_human_review"].state == "completed"
    assert approval_steps["step_artifact_save"].state == "completed"
    assert approval_steps["step_policy_evaluate"].state == "completed"
    assert approval_steps["step_connector_dispatch"].state == "waiting_approval"
    assert len(awaiting_approval.artifacts) == 1
    assert awaiting_approval.artifacts[0].content == "Reviewed stakeholder briefing."
    pending_approvals = orchestrator.list_pending_approvals(limit=10)
    approval = next(row for row in pending_approvals if row.session_id == exc.value.session_id)

    decision = orchestrator.decide_approval(
        approval.approval_id,
        decision="approve",
        decided_by="operator",
        reason="approved reviewed dispatch",
    )
    assert decision is not None

    completed = orchestrator.fetch_session(exc.value.session_id)
    assert completed is not None
    completed_steps = {step.input_json["plan_step_key"]: step for step in completed.steps}
    assert completed.session.status == "completed"
    assert completed_steps["step_connector_dispatch"].state == "completed"
    assert [row.tool_name for row in completed.receipts] == ["artifact_repository", "connector.dispatch"]
    pending = channel_runtime.list_pending_delivery(limit=10)
    assert len(pending) == 1
    assert pending[0].recipient == "reviewed@example.com"


def test_review_then_dispatch_workflow_template_keeps_delayed_dispatch_retry_async_after_approval() -> None:
    orchestrator, channel_runtime, tool_runtime = _build_dispatch_runtime(
        task_key="stakeholder_review_dispatch_retry",
        budget_policy_json={
            "class": "low",
            "workflow_template": "artifact_then_dispatch",
            "human_review_role": "communications_reviewer",
            "human_review_task_type": "communications_review",
            "human_review_brief": "Review before stakeholder dispatch.",
            "human_review_priority": "high",
            "human_review_desired_output_json": {"format": "review_packet"},
            "dispatch_failure_strategy": "retry",
            "dispatch_max_attempts": 2,
            "dispatch_retry_backoff_seconds": 45,
        },
    )
    binding = tool_runtime.upsert_connector_binding(
        principal_id="exec-1",
        connector_name="gmail",
        external_account_ref="acct-3",
        scope_json={"scopes": ["mail.send"]},
        auth_metadata_json={"provider": "google"},
        status="enabled",
    )
    original_handler = orchestrator._tool_execution._handlers["connector.dispatch"]  # type: ignore[attr-defined]
    calls = {"count": 0}

    def flaky_dispatch(request, definition):
        calls["count"] += 1
        if calls["count"] == 1:
            raise RuntimeError("temporary_dispatch_failure")
        return original_handler(request, definition)

    orchestrator._tool_execution.register_handler("connector.dispatch", flaky_dispatch)  # type: ignore[attr-defined]

    with pytest.raises(HumanTaskRequiredError) as exc:
        orchestrator.execute_task_artifact(
            TaskExecutionRequest(
                task_key="stakeholder_review_dispatch_retry",
                principal_id="exec-1",
                goal="review and send a stakeholder briefing",
                input_json={
                    "source_text": "Board context and stakeholder sensitivities.",
                    "binding_id": binding.binding_id,
                    "channel": "email",
                    "recipient": "reviewed-retry@example.com",
                },
            )
        )

    returned = orchestrator.return_human_task(
        exc.value.human_task_id,
        principal_id="exec-1",
        operator_id="reviewer-1",
        resolution="ready_for_dispatch",
        returned_payload_json={"final_text": "Reviewed stakeholder briefing."},
        provenance_json={"review_mode": "human"},
    )
    assert returned is not None

    pending_approvals = orchestrator.list_pending_approvals(limit=10)
    approval = next(row for row in pending_approvals if row.session_id == exc.value.session_id)
    decision = orchestrator.decide_approval(
        approval.approval_id,
        decision="approve",
        decided_by="operator",
        reason="approved reviewed dispatch retry",
    )
    assert decision is not None

    queued = orchestrator.fetch_session(exc.value.session_id)
    assert queued is not None
    queued_steps = {step.input_json["plan_step_key"]: step for step in queued.steps}
    assert queued.session.status == "queued"
    assert queued_steps["step_human_review"].state == "completed"
    assert queued_steps["step_artifact_save"].state == "completed"
    assert queued_steps["step_policy_evaluate"].state == "completed"
    assert queued_steps["step_connector_dispatch"].state == "queued"
    assert queued_steps["step_connector_dispatch"].attempt_count == 1
    assert queued_steps["step_connector_dispatch"].error_json["reason"] == "retry_scheduled"
    assert queued.queue_items[-1].state == "queued"
    assert queued.queue_items[-1].next_attempt_at
    assert channel_runtime.list_pending_delivery(limit=10) == []
    assert calls["count"] == 1


def test_planner_rejects_unknown_workflow_template_metadata() -> None:
    task_contracts = TaskContractService(InMemoryTaskContractRepository())
    task_contracts.upsert_contract(
        task_key="invalid_template",
        deliverable_type="rewrite_note",
        default_risk_class="low",
        default_approval_class="none",
        allowed_tools=("artifact_repository",),
        evidence_requirements=(),
        memory_write_policy="reviewed_only",
        budget_policy_json={"class": "low", "workflow_template": "not_real"},
    )
    planner = PlannerService(task_contracts)

    with pytest.raises(PlanValidationError, match="unknown_workflow_template:not_real"):
        planner.build_plan(
            task_key="invalid_template",
            principal_id="exec-1",
            goal="should fail fast",
        )


def test_api_rejects_unknown_workflow_template_metadata_with_validation_error() -> None:
    client = _api_client()
    created = client.post(
        "/v1/tasks/contracts",
        json={
            "task_key": "invalid_template",
            "deliverable_type": "rewrite_note",
            "default_risk_class": "low",
            "default_approval_class": "none",
            "allowed_tools": ["artifact_repository"],
            "evidence_requirements": [],
            "memory_write_policy": "reviewed_only",
            "budget_policy_json": {"class": "low", "workflow_template": "not_real"},
        },
    )
    assert created.status_code == 200

    compiled = client.post(
        "/v1/plans/compile",
        json={"task_key": "invalid_template", "goal": "compile should fail"},
    )
    assert compiled.status_code == 422
    assert compiled.json()["error"]["code"] == "unknown_workflow_template:not_real"

    executed = client.post(
        "/v1/plans/execute",
        json={"task_key": "invalid_template", "text": "fail execute", "goal": "execute should fail"},
    )
    assert executed.status_code == 422
    assert executed.json()["error"]["code"] == "unknown_workflow_template:not_real"


def test_rewrite_route_rejects_unknown_workflow_template_metadata_with_validation_error() -> None:
    client = _api_client()
    created = client.post(
        "/v1/tasks/contracts",
        json={
            "task_key": "rewrite_text",
            "deliverable_type": "rewrite_note",
            "default_risk_class": "low",
            "default_approval_class": "none",
            "allowed_tools": ["artifact_repository"],
            "evidence_requirements": [],
            "memory_write_policy": "reviewed_only",
            "budget_policy_json": {"class": "low", "workflow_template": "not_real"},
        },
    )
    assert created.status_code == 200

    rewrite = client.post(
        "/v1/rewrite/artifact",
        json={"text": "fail rewrite", "goal": "rewrite should fail"},
    )
    assert rewrite.status_code == 422
    assert rewrite.json()["error"]["code"] == "unknown_workflow_template:not_real"
