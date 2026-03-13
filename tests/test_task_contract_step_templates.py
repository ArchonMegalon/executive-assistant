from __future__ import annotations

import os

import pytest

from app.domain.models import PlanValidationError, TaskExecutionRequest
from app.repositories.approvals import InMemoryApprovalRepository
from app.repositories.artifacts import InMemoryArtifactRepository
from app.repositories.connector_bindings import InMemoryConnectorBindingRepository
from app.repositories.delivery_outbox import InMemoryDeliveryOutboxRepository
from app.repositories.ledger import InMemoryExecutionLedgerRepository
from app.repositories.authority_bindings import InMemoryAuthorityBindingRepository
from app.repositories.commitments import InMemoryCommitmentRepository
from app.repositories.communication_policies import InMemoryCommunicationPolicyRepository
from app.repositories.decision_windows import InMemoryDecisionWindowRepository
from app.repositories.deadline_windows import InMemoryDeadlineWindowRepository
from app.repositories.delivery_preferences import InMemoryDeliveryPreferenceRepository
from app.repositories.entities import InMemoryEntityRepository
from app.repositories.evidence_objects import InMemoryEvidenceObjectRepository
from app.repositories.follow_ups import InMemoryFollowUpRepository
from app.repositories.follow_up_rules import InMemoryFollowUpRuleRepository
from app.repositories.interruption_budgets import InMemoryInterruptionBudgetRepository
from app.repositories.memory_candidates import InMemoryMemoryCandidateRepository
from app.repositories.memory_items import InMemoryMemoryItemRepository
from app.repositories.observation import InMemoryObservationEventRepository
from app.repositories.policy_decisions import InMemoryPolicyDecisionRepository
from app.repositories.relationships import InMemoryRelationshipRepository
from app.repositories.stakeholders import InMemoryStakeholderRepository
from app.repositories.task_contracts import InMemoryTaskContractRepository
from app.repositories.tool_registry import InMemoryToolRegistryRepository
from app.services.channel_runtime import ChannelRuntimeService
from app.services.evidence_runtime import EvidenceRuntimeService
from app.services.memory_runtime import MemoryRuntimeService
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
    evidence_runtime = EvidenceRuntimeService(InMemoryEvidenceObjectRepository())
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
            evidence_runtime=evidence_runtime,
        ),
    )
    return orchestrator, channel_runtime, tool_runtime


def _build_memory_candidate_runtime(
    *,
    task_key: str = "stakeholder_memory_candidate",
    budget_policy_json: dict[str, object] | None = None,
) -> tuple[RewriteOrchestrator, MemoryRuntimeService]:
    task_contracts = TaskContractService(InMemoryTaskContractRepository())
    task_contracts.upsert_contract(
        task_key=task_key,
        deliverable_type="stakeholder_briefing",
        default_risk_class="low",
        default_approval_class="none",
        allowed_tools=("artifact_repository",),
        evidence_requirements=("stakeholder_context",),
        memory_write_policy="reviewed_only",
        budget_policy_json=dict(
            budget_policy_json
            or {
                "class": "low",
                "workflow_template": "artifact_then_memory_candidate",
                "memory_candidate_category": "stakeholder_briefing_fact",
                "memory_candidate_confidence": 0.7,
                "memory_candidate_sensitivity": "internal",
            }
        ),
    )
    memory_runtime = MemoryRuntimeService(
        candidates=InMemoryMemoryCandidateRepository(),
        items=InMemoryMemoryItemRepository(),
        entities=InMemoryEntityRepository(),
        relationships=InMemoryRelationshipRepository(),
        commitments=InMemoryCommitmentRepository(),
        communication_policies=InMemoryCommunicationPolicyRepository(),
        decision_windows=InMemoryDecisionWindowRepository(),
        deadline_windows=InMemoryDeadlineWindowRepository(),
        stakeholders=InMemoryStakeholderRepository(),
        authority_bindings=InMemoryAuthorityBindingRepository(),
        delivery_preferences=InMemoryDeliveryPreferenceRepository(),
        follow_ups=InMemoryFollowUpRepository(),
        follow_up_rules=InMemoryFollowUpRuleRepository(),
        interruption_budgets=InMemoryInterruptionBudgetRepository(),
    )
    artifacts = InMemoryArtifactRepository()
    evidence_runtime = EvidenceRuntimeService(InMemoryEvidenceObjectRepository())
    orchestrator = RewriteOrchestrator(
        artifacts=artifacts,
        ledger=InMemoryExecutionLedgerRepository(),
        approvals=InMemoryApprovalRepository(),
        policy_repo=InMemoryPolicyDecisionRepository(),
        policy=PolicyDecisionService(),
        task_contracts=task_contracts,
        planner=PlannerService(task_contracts),
        memory_runtime=memory_runtime,
        tool_execution=ToolExecutionService(
            tool_runtime=ToolRuntimeService(
                tool_registry=InMemoryToolRegistryRepository(),
                connector_bindings=InMemoryConnectorBindingRepository(),
            ),
            artifacts=artifacts,
            evidence_runtime=evidence_runtime,
        ),
    )
    return orchestrator, memory_runtime


def _build_dispatch_memory_runtime(
    *,
    task_key: str = "stakeholder_dispatch_memory_candidate",
    budget_policy_json: dict[str, object] | None = None,
) -> tuple[RewriteOrchestrator, ChannelRuntimeService, ToolRuntimeService, MemoryRuntimeService]:
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
            or {
                "class": "low",
                "workflow_template": "artifact_then_dispatch_then_memory_candidate",
                "memory_candidate_category": "stakeholder_follow_up_fact",
                "memory_candidate_confidence": 0.8,
                "memory_candidate_sensitivity": "internal",
            }
        ),
    )
    memory_runtime = MemoryRuntimeService(
        candidates=InMemoryMemoryCandidateRepository(),
        items=InMemoryMemoryItemRepository(),
        entities=InMemoryEntityRepository(),
        relationships=InMemoryRelationshipRepository(),
        commitments=InMemoryCommitmentRepository(),
        communication_policies=InMemoryCommunicationPolicyRepository(),
        decision_windows=InMemoryDecisionWindowRepository(),
        deadline_windows=InMemoryDeadlineWindowRepository(),
        stakeholders=InMemoryStakeholderRepository(),
        authority_bindings=InMemoryAuthorityBindingRepository(),
        delivery_preferences=InMemoryDeliveryPreferenceRepository(),
        follow_ups=InMemoryFollowUpRepository(),
        follow_up_rules=InMemoryFollowUpRuleRepository(),
        interruption_budgets=InMemoryInterruptionBudgetRepository(),
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
        memory_runtime=memory_runtime,
        tool_execution=ToolExecutionService(
            tool_runtime=tool_runtime,
            artifacts=artifacts,
            channel_runtime=channel_runtime,
        ),
    )
    return orchestrator, channel_runtime, tool_runtime, memory_runtime


def _build_browseract_runtime(
    *,
    task_key: str = "browseract_ltd_discovery",
    deliverable_type: str = "ltd_service_profile",
    allowed_tools: tuple[str, ...] = ("browseract.extract_account_facts", "artifact_repository"),
    budget_policy_json: dict[str, object] | None = None,
) -> tuple[RewriteOrchestrator, ToolRuntimeService]:
    task_contracts = TaskContractService(InMemoryTaskContractRepository())
    task_contracts.upsert_contract(
        task_key=task_key,
        deliverable_type=deliverable_type,
        default_risk_class="low",
        default_approval_class="none",
        allowed_tools=allowed_tools,
        evidence_requirements=("account_inventory",),
        memory_write_policy="none",
        budget_policy_json=dict(
            budget_policy_json
            or {"class": "low", "workflow_template": "browseract_extract_then_artifact"}
        ),
    )
    tool_runtime = ToolRuntimeService(
        tool_registry=InMemoryToolRegistryRepository(),
        connector_bindings=InMemoryConnectorBindingRepository(),
    )
    artifacts = InMemoryArtifactRepository()
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
        ),
    )
    return orchestrator, tool_runtime


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


def test_planner_can_compile_memory_candidate_workflow_template() -> None:
    task_contracts = TaskContractService(InMemoryTaskContractRepository())
    task_contracts.upsert_contract(
        task_key="stakeholder_memory_candidate",
        deliverable_type="stakeholder_briefing",
        default_risk_class="low",
        default_approval_class="none",
        allowed_tools=("artifact_repository",),
        evidence_requirements=("stakeholder_context",),
        memory_write_policy="reviewed_only",
        budget_policy_json={
            "class": "low",
            "workflow_template": "artifact_then_memory_candidate",
            "memory_candidate_category": "stakeholder_briefing_fact",
            "memory_candidate_confidence": 0.7,
            "memory_candidate_sensitivity": "internal",
        },
    )
    planner = PlannerService(task_contracts)

    _, plan = planner.build_plan(
        task_key="stakeholder_memory_candidate",
        principal_id="exec-1",
        goal="prepare a stakeholder briefing and stage memory",
    )

    assert _step_keys(plan) == (
        "step_input_prepare",
        "step_policy_evaluate",
        "step_artifact_save",
        "step_memory_candidate_stage",
    )
    memory_step = plan.steps[3]
    assert memory_step.step_kind == "memory_write"
    assert memory_step.depends_on == ("step_artifact_save", "step_policy_evaluate")
    assert memory_step.authority_class == "queue"
    assert memory_step.review_class == "operator"
    assert memory_step.input_keys == ("artifact_id", "normalized_text", "memory_write_allowed")
    assert memory_step.output_keys == ("candidate_id", "candidate_status", "candidate_category")
    assert memory_step.desired_output_json["category"] == "stakeholder_briefing_fact"
    assert memory_step.desired_output_json["confidence"] == 0.7


def test_planner_can_compile_browseract_extract_then_artifact_workflow_template() -> None:
    task_contracts = TaskContractService(InMemoryTaskContractRepository())
    task_contracts.upsert_contract(
        task_key="browseract_ltd_discovery",
        deliverable_type="ltd_service_profile",
        default_risk_class="low",
        default_approval_class="none",
        allowed_tools=("browseract.extract_account_facts", "artifact_repository"),
        evidence_requirements=("account_inventory",),
        memory_write_policy="none",
        budget_policy_json={"class": "low", "workflow_template": "browseract_extract_then_artifact"},
    )
    planner = PlannerService(task_contracts)

    _, plan = planner.build_plan(
        task_key="browseract_ltd_discovery",
        principal_id="exec-1",
        goal="extract LTD account facts for BrowserAct",
    )

    assert _step_keys(plan) == (
        "step_input_prepare",
        "step_browseract_extract",
        "step_artifact_save",
    )
    extract_step = plan.steps[1]
    assert extract_step.step_kind == "tool_call"
    assert extract_step.tool_name == "browseract.extract_account_facts"
    assert extract_step.depends_on == ("step_input_prepare",)
    assert extract_step.authority_class == "observe"
    assert extract_step.input_keys == (
        "binding_id",
        "service_name",
        "requested_fields",
        "instructions",
        "account_hints_json",
        "run_url",
    )
    assert "structured_output_json" in extract_step.output_keys
    artifact_step = plan.steps[2]
    assert artifact_step.tool_name == "artifact_repository"
    assert artifact_step.depends_on == ("step_browseract_extract",)
    assert artifact_step.input_keys == ("normalized_text", "structured_output_json", "preview_text", "mime_type")


def test_planner_can_compile_generic_tool_then_artifact_workflow_template_for_browseract() -> None:
    task_contracts = TaskContractService(InMemoryTaskContractRepository())
    task_contracts.upsert_contract(
        task_key="browseract_ltd_discovery_generic",
        deliverable_type="ltd_service_profile",
        default_risk_class="low",
        default_approval_class="none",
        allowed_tools=("browseract.extract_account_facts", "artifact_repository"),
        evidence_requirements=("account_inventory",),
        memory_write_policy="none",
        budget_policy_json={
            "class": "low",
            "workflow_template": "tool_then_artifact",
            "pre_artifact_tool_name": "browseract.extract_account_facts",
        },
    )
    planner = PlannerService(task_contracts)

    _, plan = planner.build_plan(
        task_key="browseract_ltd_discovery_generic",
        principal_id="exec-1",
        goal="extract LTD account facts for BrowserAct",
    )

    assert _step_keys(plan) == (
        "step_input_prepare",
        "step_browseract_extract",
        "step_artifact_save",
    )
    assert plan.steps[0].input_keys == (
        "binding_id",
        "service_name",
        "requested_fields",
        "instructions",
        "account_hints_json",
        "run_url",
    )
    assert plan.steps[1].tool_name == "browseract.extract_account_facts"
    assert plan.steps[2].input_keys == ("normalized_text", "structured_output_json", "preview_text", "mime_type")


def test_planner_can_compile_generic_tool_then_artifact_workflow_template_for_browseract_inventory() -> None:
    task_contracts = TaskContractService(InMemoryTaskContractRepository())
    task_contracts.upsert_contract(
        task_key="browseract_ltd_inventory_refresh",
        deliverable_type="ltd_inventory_profile",
        default_risk_class="low",
        default_approval_class="none",
        allowed_tools=("browseract.extract_account_inventory", "artifact_repository"),
        evidence_requirements=("account_inventory",),
        memory_write_policy="none",
        budget_policy_json={
            "class": "low",
            "workflow_template": "tool_then_artifact",
            "pre_artifact_tool_name": "browseract.extract_account_inventory",
        },
    )
    planner = PlannerService(task_contracts)

    _, plan = planner.build_plan(
        task_key="browseract_ltd_inventory_refresh",
        principal_id="exec-1",
        goal="refresh LTD inventory facts",
    )

    assert _step_keys(plan) == (
        "step_input_prepare",
        "step_browseract_inventory_extract",
        "step_artifact_save",
    )
    assert plan.steps[0].input_keys == (
        "binding_id",
        "service_names",
        "requested_fields",
        "instructions",
        "account_hints_json",
        "run_url",
    )
    assert plan.steps[1].tool_name == "browseract.extract_account_inventory"
    assert plan.steps[1].output_keys == (
        "service_names",
        "services_json",
        "missing_services",
        "normalized_text",
        "preview_text",
        "mime_type",
        "structured_output_json",
    )
    assert plan.steps[2].input_keys == ("normalized_text", "structured_output_json", "preview_text", "mime_type")


def test_generic_tool_then_artifact_workflow_template_rejects_unsupported_tool() -> None:
    task_contracts = TaskContractService(InMemoryTaskContractRepository())
    task_contracts.upsert_contract(
        task_key="unsupported_tool_then_artifact",
        deliverable_type="rewrite_note",
        default_risk_class="low",
        default_approval_class="none",
        allowed_tools=("artifact_repository",),
        evidence_requirements=(),
        memory_write_policy="none",
        budget_policy_json={
            "class": "low",
            "workflow_template": "tool_then_artifact",
            "pre_artifact_tool_name": "not_real",
        },
    )
    planner = PlannerService(task_contracts)

    with pytest.raises(PlanValidationError) as exc:
        planner.build_plan(
            task_key="unsupported_tool_then_artifact",
            principal_id="exec-1",
            goal="fail fast",
        )

    assert str(exc.value) == "pre_artifact_tool_not_allowed:not_real"


def test_planner_can_compile_generic_tool_then_artifact_workflow_template_for_gemini_vortex() -> None:
    task_contracts = TaskContractService(InMemoryTaskContractRepository())
    task_contracts.upsert_contract(
        task_key="chummer6_prompt_brain",
        deliverable_type="chummer6_guide_refresh_packet",
        default_risk_class="low",
        default_approval_class="none",
        allowed_tools=("provider.gemini_vortex.structured_generate", "artifact_repository"),
        evidence_requirements=("repo_readmes", "design_scope"),
        memory_write_policy="none",
        budget_policy_json={
            "class": "low",
            "workflow_template": "tool_then_artifact",
            "pre_artifact_capability_key": "structured_generate",
        },
    )
    planner = PlannerService(task_contracts)

    _, plan = planner.build_plan(
        task_key="chummer6_prompt_brain",
        principal_id="exec-1",
        goal="generate a structured Chummer6 refresh packet",
    )

    assert _step_keys(plan) == (
        "step_input_prepare",
        "step_structured_generate",
        "step_artifact_save",
    )
    assert plan.steps[0].input_keys == ("normalized_text",)
    assert plan.steps[1].tool_name == "provider.gemini_vortex.structured_generate"
    assert plan.steps[1].output_keys == (
        "normalized_text",
        "structured_output_json",
        "preview_text",
        "mime_type",
    )
    assert plan.steps[2].input_keys == ("normalized_text", "structured_output_json", "preview_text", "mime_type")


def test_planner_can_compile_generic_tool_then_artifact_workflow_template_for_browseract_workflow_repair() -> None:
    task_contracts = TaskContractService(InMemoryTaskContractRepository())
    task_contracts.upsert_contract(
        task_key="browseract_workflow_repair_manager",
        deliverable_type="browseract_workflow_repair_packet",
        default_risk_class="medium",
        default_approval_class="none",
        allowed_tools=("browseract.repair_workflow_spec", "artifact_repository"),
        evidence_requirements=("workflow_runtime_failure", "workflow_spec"),
        memory_write_policy="none",
        budget_policy_json={
            "class": "medium",
            "workflow_template": "tool_then_artifact",
            "pre_artifact_capability_key": "workflow_spec_repair",
        },
    )
    planner = PlannerService(task_contracts)

    _, plan = planner.build_plan(
        task_key="browseract_workflow_repair_manager",
        principal_id="exec-1",
        goal="repair a broken BrowserAct workflow spec",
    )

    assert _step_keys(plan) == (
        "step_input_prepare",
        "step_browseract_workflow_spec_repair",
        "step_artifact_save",
    )
    assert plan.steps[1].tool_name == "browseract.repair_workflow_spec"
    assert plan.steps[1].output_keys == (
        "normalized_text",
        "structured_output_json",
        "preview_text",
        "mime_type",
    )
    assert plan.steps[2].input_keys == ("normalized_text", "structured_output_json", "preview_text", "mime_type")


def test_planner_can_compile_dispatch_then_memory_candidate_workflow_template() -> None:
    task_contracts = TaskContractService(InMemoryTaskContractRepository())
    task_contracts.upsert_contract(
        task_key="stakeholder_dispatch_memory_candidate",
        deliverable_type="stakeholder_briefing",
        default_risk_class="low",
        default_approval_class="none",
        allowed_tools=("artifact_repository", "connector.dispatch"),
        evidence_requirements=("stakeholder_context",),
        memory_write_policy="reviewed_only",
        budget_policy_json={
            "class": "low",
            "workflow_template": "artifact_then_dispatch_then_memory_candidate",
            "memory_candidate_category": "stakeholder_follow_up_fact",
            "memory_candidate_confidence": 0.8,
            "memory_candidate_sensitivity": "internal",
        },
    )
    planner = PlannerService(task_contracts)

    _, plan = planner.build_plan(
        task_key="stakeholder_dispatch_memory_candidate",
        principal_id="exec-1",
        goal="prepare, send, and stage stakeholder follow-up memory",
    )

    assert _step_keys(plan) == (
        "step_input_prepare",
        "step_artifact_save",
        "step_policy_evaluate",
        "step_connector_dispatch",
        "step_memory_candidate_stage",
    )
    memory_step = plan.steps[4]
    assert memory_step.step_kind == "memory_write"
    assert memory_step.depends_on == ("step_artifact_save", "step_policy_evaluate", "step_connector_dispatch")
    assert memory_step.input_keys == (
        "artifact_id",
        "normalized_text",
        "memory_write_allowed",
        "delivery_id",
        "status",
        "binding_id",
        "channel",
        "recipient",
    )
    assert memory_step.desired_output_json["category"] == "stakeholder_follow_up_fact"
    assert plan.steps[3].tool_name == "connector.dispatch"


def test_planner_can_compile_post_artifact_packs_template() -> None:
    task_contracts = TaskContractService(InMemoryTaskContractRepository())
    task_contracts.upsert_contract(
        task_key="stakeholder_pack_template",
        deliverable_type="stakeholder_briefing",
        default_risk_class="low",
        default_approval_class="none",
        allowed_tools=("artifact_repository", "connector.dispatch"),
        evidence_requirements=("stakeholder_context",),
        memory_write_policy="reviewed_only",
        budget_policy_json={
            "class": "low",
            "workflow_template": "artifact_then_packs",
            "post_artifact_packs": ["dispatch", "memory_candidate"],
            "memory_candidate_category": "stakeholder_follow_up_fact",
            "memory_candidate_confidence": 0.8,
            "memory_candidate_sensitivity": "internal",
        },
    )
    planner = PlannerService(task_contracts)

    _, plan = planner.build_plan(
        task_key="stakeholder_pack_template",
        principal_id="exec-1",
        goal="prepare, send, and stage stakeholder follow-up memory",
    )

    assert _step_keys(plan) == (
        "step_input_prepare",
        "step_artifact_save",
        "step_policy_evaluate",
        "step_connector_dispatch",
        "step_memory_candidate_stage",
    )
    memory_step = plan.steps[4]
    assert memory_step.depends_on == ("step_artifact_save", "step_policy_evaluate", "step_connector_dispatch")
    assert memory_step.input_keys == (
        "artifact_id",
        "normalized_text",
        "memory_write_allowed",
        "delivery_id",
        "status",
        "binding_id",
        "channel",
        "recipient",
    )


def test_planner_rejects_unknown_post_artifact_pack() -> None:
    task_contracts = TaskContractService(InMemoryTaskContractRepository())
    task_contracts.upsert_contract(
        task_key="stakeholder_bad_pack",
        deliverable_type="stakeholder_briefing",
        default_risk_class="low",
        default_approval_class="none",
        allowed_tools=("artifact_repository",),
        evidence_requirements=("stakeholder_context",),
        memory_write_policy="reviewed_only",
        budget_policy_json={
            "class": "low",
            "workflow_template": "artifact_then_packs",
            "post_artifact_packs": ["unknown_pack"],
        },
    )
    planner = PlannerService(task_contracts)

    with pytest.raises(PlanValidationError, match="unknown_post_artifact_pack:unknown_pack"):
        planner.build_plan(
            task_key="stakeholder_bad_pack",
            principal_id="exec-1",
            goal="prepare a stakeholder briefing",
        )


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


def test_memory_candidate_workflow_template_stages_candidate_after_artifact() -> None:
    orchestrator, memory_runtime = _build_memory_candidate_runtime()

    artifact = orchestrator.execute_task_artifact(
        TaskExecutionRequest(
            task_key="stakeholder_memory_candidate",
            principal_id="exec-1",
            goal="prepare a stakeholder briefing and stage memory",
            input_json={"source_text": "Board context and stakeholder sensitivities."},
        )
    )

    snapshot = orchestrator.fetch_session(artifact.execution_session_id)
    assert snapshot is not None
    assert snapshot.session.status == "completed"
    steps_by_key = {step.input_json["plan_step_key"]: step for step in snapshot.steps}
    assert steps_by_key["step_memory_candidate_stage"].state == "completed"
    assert steps_by_key["step_memory_candidate_stage"].output_json["candidate_status"] == "pending"
    candidate_id = steps_by_key["step_memory_candidate_stage"].output_json["candidate_id"]
    assert candidate_id
    candidates = memory_runtime.list_candidates(limit=10, principal_id="exec-1")
    assert any(row.candidate_id == candidate_id for row in candidates)
    candidate = next(row for row in candidates if row.candidate_id == candidate_id)
    assert candidate.category == "stakeholder_briefing_fact"
    assert candidate.source_session_id == artifact.execution_session_id
    assert candidate.summary == "Board context and stakeholder sensitivities."


def test_browseract_extract_then_artifact_workflow_template_persists_discovered_facts() -> None:
    orchestrator, tool_runtime = _build_browseract_runtime()
    binding = tool_runtime.upsert_connector_binding(
        principal_id="exec-1",
        connector_name="browseract",
        external_account_ref="browseract-main",
        scope_json={"services": ["BrowserAct"]},
        auth_metadata_json={
            "service_accounts_json": {
                "BrowserAct": {
                    "tier": "Tier 3",
                    "account_email": "ops@example.com",
                    "status": "activated",
                }
            }
        },
        status="enabled",
    )

    artifact = orchestrator.execute_task_artifact(
        TaskExecutionRequest(
            task_key="browseract_ltd_discovery",
            principal_id="exec-1",
            goal="extract LTD account facts for BrowserAct",
            input_json={
                "binding_id": binding.binding_id,
                "service_name": "BrowserAct",
                "requested_fields": ["tier", "account_email", "status"],
            },
        )
    )

    snapshot = orchestrator.fetch_session(artifact.execution_session_id)
    assert snapshot is not None
    assert snapshot.session.status == "completed"
    steps_by_key = {step.input_json["plan_step_key"]: step for step in snapshot.steps}
    assert steps_by_key["step_browseract_extract"].state == "completed"
    assert steps_by_key["step_artifact_save"].state == "completed"
    assert steps_by_key["step_browseract_extract"].output_json["service_name"] == "BrowserAct"
    assert steps_by_key["step_browseract_extract"].output_json["facts_json"]["tier"] == "Tier 3"
    assert steps_by_key["step_browseract_extract"].output_json["account_email"] == "ops@example.com"
    assert steps_by_key["step_browseract_extract"].output_json["missing_fields"] == []
    assert artifact.kind == "ltd_service_profile"
    assert "Service: BrowserAct" in artifact.content
    assert artifact.structured_output_json["facts_json"]["tier"] == "Tier 3"
    assert artifact.structured_output_json["account_email"] == "ops@example.com"
    assert [row.tool_name for row in snapshot.receipts] == ["browseract.extract_account_facts", "artifact_repository"]


def test_generic_tool_then_artifact_workflow_template_persists_browseract_facts() -> None:
    orchestrator, tool_runtime = _build_browseract_runtime(
        task_key="browseract_ltd_discovery_generic",
        budget_policy_json={
            "class": "low",
            "workflow_template": "tool_then_artifact",
            "pre_artifact_tool_name": "browseract.extract_account_facts",
        },
    )
    binding = tool_runtime.upsert_connector_binding(
        principal_id="exec-1",
        connector_name="browseract",
        external_account_ref="browseract-main",
        scope_json={"services": ["BrowserAct"]},
        auth_metadata_json={
            "service_accounts_json": {
                "BrowserAct": {
                    "tier": "Tier 3",
                    "account_email": "ops@example.com",
                    "status": "activated",
                }
            }
        },
        status="enabled",
    )

    artifact = orchestrator.execute_task_artifact(
        TaskExecutionRequest(
            task_key="browseract_ltd_discovery_generic",
            principal_id="exec-1",
            goal="extract LTD account facts for BrowserAct",
            input_json={
                "binding_id": binding.binding_id,
                "service_name": "BrowserAct",
                "requested_fields": ["tier", "account_email", "status"],
            },
        )
    )

    snapshot = orchestrator.fetch_session(artifact.execution_session_id)
    assert snapshot is not None
    assert snapshot.session.status == "completed"
    assert [row.tool_name for row in snapshot.receipts] == ["browseract.extract_account_facts", "artifact_repository"]
    assert artifact.kind == "ltd_service_profile"
    assert artifact.structured_output_json["facts_json"]["tier"] == "Tier 3"
    assert artifact.structured_output_json["account_email"] == "ops@example.com"


def test_generic_tool_then_artifact_workflow_template_persists_browseract_inventory() -> None:
    orchestrator, tool_runtime = _build_browseract_runtime(
        task_key="browseract_ltd_inventory_refresh",
        deliverable_type="ltd_inventory_profile",
        allowed_tools=("browseract.extract_account_inventory", "artifact_repository"),
        budget_policy_json={
            "class": "low",
            "workflow_template": "tool_then_artifact",
            "pre_artifact_tool_name": "browseract.extract_account_inventory",
        },
    )
    binding = tool_runtime.upsert_connector_binding(
        principal_id="exec-1",
        connector_name="browseract",
        external_account_ref="browseract-main",
        scope_json={"services": ["BrowserAct", "Teable", "UnknownService"]},
        auth_metadata_json={
            "service_accounts_json": {
                "BrowserAct": {
                    "tier": "Tier 3",
                    "account_email": "ops@example.com",
                    "status": "activated",
                },
                "Teable": {
                    "tier": "License Tier 4",
                    "account_email": "ops@teable.example",
                    "status": "activated",
                },
            }
        },
        status="enabled",
    )

    artifact = orchestrator.execute_task_artifact(
        TaskExecutionRequest(
            task_key="browseract_ltd_inventory_refresh",
            principal_id="exec-1",
            goal="refresh LTD inventory facts",
            input_json={
                "binding_id": binding.binding_id,
                "service_names": ["BrowserAct", "Teable", "UnknownService"],
                "requested_fields": ["tier", "account_email", "status"],
            },
        )
    )

    snapshot = orchestrator.fetch_session(artifact.execution_session_id)
    assert snapshot is not None
    assert snapshot.session.status == "completed"
    assert [row.tool_name for row in snapshot.receipts] == ["browseract.extract_account_inventory", "artifact_repository"]
    assert artifact.kind == "ltd_inventory_profile"
    assert artifact.structured_output_json["service_names"] == ["BrowserAct", "Teable", "UnknownService"]
    assert artifact.structured_output_json["missing_services"] == ["UnknownService"]
    assert artifact.structured_output_json["services_json"][1]["plan_tier"] == "License Tier 4"
    assert "Service: BrowserAct" in artifact.content
    assert "Service: UnknownService" in artifact.content


def test_dispatch_then_memory_candidate_workflow_template_stages_candidate_after_approval() -> None:
    orchestrator, channel_runtime, tool_runtime, memory_runtime = _build_dispatch_memory_runtime()
    binding = tool_runtime.upsert_connector_binding(
        principal_id="exec-1",
        connector_name="gmail",
        external_account_ref="acct-dispatch-memory",
        scope_json={"scopes": ["mail.send"]},
        auth_metadata_json={"provider": "google"},
        status="enabled",
    )

    with pytest.raises(ApprovalRequiredError) as exc:
        orchestrator.execute_task_artifact(
            TaskExecutionRequest(
                task_key="stakeholder_dispatch_memory_candidate",
                principal_id="exec-1",
                goal="prepare, send, and stage stakeholder follow-up memory",
                input_json={
                    "source_text": "Board context and stakeholder sensitivities.",
                    "binding_id": binding.binding_id,
                    "channel": "email",
                    "recipient": "dispatch-memory@example.com",
                },
            )
        )

    waiting = orchestrator.fetch_session(exc.value.session_id)
    assert waiting is not None
    assert waiting.session.status == "awaiting_approval"
    waiting_steps = {step.input_json["plan_step_key"]: step for step in waiting.steps}
    assert waiting_steps["step_artifact_save"].state == "completed"
    assert waiting_steps["step_policy_evaluate"].state == "completed"
    assert waiting_steps["step_connector_dispatch"].state == "waiting_approval"
    assert waiting_steps["step_memory_candidate_stage"].state == "queued"
    assert tuple(waiting_steps["step_memory_candidate_stage"].input_json["depends_on"]) == (
        "step_artifact_save",
        "step_policy_evaluate",
        "step_connector_dispatch",
    )
    assert channel_runtime.list_pending_delivery(limit=10) == []
    assert memory_runtime.list_candidates(limit=10, principal_id="exec-1") == []

    decision = orchestrator.decide_approval(
        exc.value.approval_id,
        decision="approve",
        decided_by="operator",
        reason="approved dispatch memory template",
    )
    assert decision is not None

    resumed = orchestrator.fetch_session(exc.value.session_id)
    assert resumed is not None
    resumed_steps = {step.input_json["plan_step_key"]: step for step in resumed.steps}
    assert resumed.session.status == "completed"
    assert resumed_steps["step_connector_dispatch"].state == "completed"
    assert resumed_steps["step_memory_candidate_stage"].state == "completed"
    candidate_id = resumed_steps["step_memory_candidate_stage"].output_json["candidate_id"]
    assert candidate_id
    pending = channel_runtime.list_pending_delivery(limit=10)
    assert len(pending) == 1
    assert pending[0].recipient == "dispatch-memory@example.com"
    candidates = memory_runtime.list_candidates(limit=10, principal_id="exec-1")
    candidate = next(row for row in candidates if row.candidate_id == candidate_id)
    assert candidate.category == "stakeholder_follow_up_fact"
    assert candidate.source_session_id == exc.value.session_id
    assert candidate.fact_json["delivery_id"] == pending[0].delivery_id
    assert candidate.fact_json["delivery_status"] == pending[0].status
    assert candidate.fact_json["binding_id"] == binding.binding_id
    assert candidate.fact_json["recipient"] == "dispatch-memory@example.com"
    assert candidate.summary == "Board context and stakeholder sensitivities."


def test_planner_can_compile_review_then_dispatch_then_memory_candidate_workflow_template() -> None:
    task_contracts = TaskContractService(InMemoryTaskContractRepository())
    task_contracts.upsert_contract(
        task_key="stakeholder_review_dispatch_memory_candidate",
        deliverable_type="stakeholder_briefing",
        default_risk_class="low",
        default_approval_class="none",
        allowed_tools=("artifact_repository", "connector.dispatch"),
        evidence_requirements=("stakeholder_context",),
        memory_write_policy="reviewed_only",
        budget_policy_json={
            "class": "low",
            "workflow_template": "artifact_then_dispatch_then_memory_candidate",
            "human_review_role": "communications_reviewer",
            "human_review_task_type": "communications_review",
            "human_review_brief": "Review before stakeholder dispatch and memory staging.",
            "human_review_priority": "high",
            "human_review_desired_output_json": {"format": "review_packet"},
            "memory_candidate_category": "stakeholder_follow_up_fact",
        },
    )
    planner = PlannerService(task_contracts)

    _, plan = planner.build_plan(
        task_key="stakeholder_review_dispatch_memory_candidate",
        principal_id="exec-1",
        goal="review, send, and stage stakeholder follow-up memory",
    )

    assert _step_keys(plan) == (
        "step_input_prepare",
        "step_human_review",
        "step_artifact_save",
        "step_policy_evaluate",
        "step_connector_dispatch",
        "step_memory_candidate_stage",
    )
    assert plan.steps[1].step_kind == "human_task"
    assert plan.steps[2].depends_on == ("step_human_review",)
    assert plan.steps[5].depends_on == ("step_artifact_save", "step_policy_evaluate", "step_connector_dispatch")


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


def test_review_then_dispatch_then_memory_candidate_workflow_template_stages_candidate_after_human_and_approval() -> None:
    orchestrator, channel_runtime, tool_runtime, memory_runtime = _build_dispatch_memory_runtime(
        task_key="stakeholder_review_dispatch_memory_candidate",
        budget_policy_json={
            "class": "low",
            "workflow_template": "artifact_then_dispatch_then_memory_candidate",
            "human_review_role": "communications_reviewer",
            "human_review_task_type": "communications_review",
            "human_review_brief": "Review before stakeholder dispatch and memory staging.",
            "human_review_priority": "high",
            "human_review_desired_output_json": {"format": "review_packet"},
            "memory_candidate_category": "stakeholder_follow_up_fact",
            "memory_candidate_confidence": 0.8,
            "memory_candidate_sensitivity": "internal",
        },
    )
    binding = tool_runtime.upsert_connector_binding(
        principal_id="exec-1",
        connector_name="gmail",
        external_account_ref="acct-review-dispatch-memory",
        scope_json={"scopes": ["mail.send"]},
        auth_metadata_json={"provider": "google"},
        status="enabled",
    )

    with pytest.raises(HumanTaskRequiredError) as exc:
        orchestrator.execute_task_artifact(
            TaskExecutionRequest(
                task_key="stakeholder_review_dispatch_memory_candidate",
                principal_id="exec-1",
                goal="review, send, and stage stakeholder follow-up memory",
                input_json={
                    "source_text": "Board context and stakeholder sensitivities.",
                    "binding_id": binding.binding_id,
                    "channel": "email",
                    "recipient": "reviewed-memory@example.com",
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
    assert waiting_steps["step_memory_candidate_stage"].state == "queued"
    assert waiting.artifacts == []
    assert channel_runtime.list_pending_delivery(limit=10) == []
    assert memory_runtime.list_candidates(limit=10, principal_id="exec-1") == []

    returned = orchestrator.return_human_task(
        exc.value.human_task_id,
        principal_id="exec-1",
        operator_id="reviewer-1",
        resolution="ready_for_dispatch",
        returned_payload_json={"final_text": "Reviewed stakeholder briefing with follow-up notes."},
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
    assert approval_steps["step_memory_candidate_stage"].state == "queued"
    assert len(awaiting_approval.artifacts) == 1
    assert awaiting_approval.artifacts[0].content == "Reviewed stakeholder briefing with follow-up notes."
    assert memory_runtime.list_candidates(limit=10, principal_id="exec-1") == []
    pending_approvals = orchestrator.list_pending_approvals(limit=10)
    approval = next(row for row in pending_approvals if row.session_id == exc.value.session_id)

    decision = orchestrator.decide_approval(
        approval.approval_id,
        decision="approve",
        decided_by="operator",
        reason="approved reviewed dispatch memory",
    )
    assert decision is not None

    completed = orchestrator.fetch_session(exc.value.session_id)
    assert completed is not None
    completed_steps = {step.input_json["plan_step_key"]: step for step in completed.steps}
    assert completed.session.status == "completed"
    assert completed_steps["step_connector_dispatch"].state == "completed"
    assert completed_steps["step_memory_candidate_stage"].state == "completed"
    candidate_id = completed_steps["step_memory_candidate_stage"].output_json["candidate_id"]
    assert candidate_id
    pending = channel_runtime.list_pending_delivery(limit=10)
    assert len(pending) == 1
    assert pending[0].recipient == "reviewed-memory@example.com"
    candidates = memory_runtime.list_candidates(limit=10, principal_id="exec-1")
    candidate = next(row for row in candidates if row.candidate_id == candidate_id)
    assert candidate.category == "stakeholder_follow_up_fact"
    assert candidate.fact_json["delivery_id"] == pending[0].delivery_id
    assert candidate.fact_json["recipient"] == "reviewed-memory@example.com"
    assert candidate.summary == "Reviewed stakeholder briefing with follow-up notes."


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


def test_planner_can_project_evidence_pack_artifact_output_template() -> None:
    task_contracts = TaskContractService(InMemoryTaskContractRepository())
    task_contracts.upsert_contract(
        task_key="research_brief",
        deliverable_type="decision_summary",
        default_risk_class="low",
        default_approval_class="none",
        allowed_tools=("artifact_repository",),
        evidence_requirements=("decision_context",),
        memory_write_policy="reviewed_only",
        budget_policy_json={
            "class": "low",
            "workflow_template": "artifact_then_memory_candidate",
            "artifact_output_template": "evidence_pack",
            "evidence_pack_confidence": 0.72,
        },
    )
    planner = PlannerService(task_contracts)

    _intent, plan = planner.build_plan(
        task_key="research_brief",
        principal_id="exec-1",
        goal="compile an evidence-backed decision brief",
    )

    prepare_step = plan.steps[0]
    artifact_step = plan.steps[2]
    memory_step = plan.steps[3]
    assert prepare_step.output_keys == (
        "normalized_text",
        "text_length",
        "structured_output_json",
        "preview_text",
        "mime_type",
    )
    assert prepare_step.desired_output_json["artifact_output_template"] == "evidence_pack"
    assert prepare_step.desired_output_json["default_confidence"] == 0.72
    assert "structured_output_json" in artifact_step.input_keys
    assert "preview_text" in artifact_step.input_keys
    assert "mime_type" in artifact_step.input_keys
    assert artifact_step.output_keys == ("artifact_id", "receipt_id", "cost_id", "evidence_object_id", "citation_handle")
    assert "evidence_object_id" in memory_step.input_keys
    assert "citation_handle" in memory_step.input_keys


def test_artifact_then_memory_candidate_evidence_pack_persists_structured_output() -> None:
    orchestrator, memory_runtime = _build_memory_candidate_runtime(
        task_key="research_brief",
        budget_policy_json={
            "class": "low",
            "workflow_template": "artifact_then_memory_candidate",
            "artifact_output_template": "evidence_pack",
            "evidence_pack_confidence": 0.72,
        },
    )

    artifact = orchestrator.execute_task_artifact(
        TaskExecutionRequest(
            task_key="research_brief",
            principal_id="exec-1",
            goal="prepare an evidence-backed brief",
            input_json={
                "source_text": "Market conditions suggest two viable options.",
                "claims": ["Option A preserves margin", "Option B accelerates launch"],
                "evidence_refs": ["browseract://run/123", "paper://abc"],
                "open_questions": ["Need final vendor pricing"],
            },
        )
    )

    assert artifact.kind == "stakeholder_briefing"
    assert artifact.structured_output_json == {
        "format": "evidence_pack",
        "claims": ["Option A preserves margin", "Option B accelerates launch"],
        "evidence_refs": ["browseract://run/123", "paper://abc"],
        "open_questions": ["Need final vendor pricing"],
        "confidence": 0.72,
    }
    candidates = memory_runtime.list_candidates(limit=10, principal_id="exec-1")
    assert candidates[0].fact_json["claims"] == ["Option A preserves margin", "Option B accelerates launch"]
    assert candidates[0].fact_json["evidence_refs"] == ["browseract://run/123", "paper://abc"]
    assert candidates[0].fact_json["open_questions"] == ["Need final vendor pricing"]
    assert candidates[0].fact_json["evidence_pack"] == artifact.structured_output_json
    assert candidates[0].fact_json["evidence_object_id"].startswith("evidence-")
    assert candidates[0].fact_json["citation_handle"].startswith("evidence://evidence-")
