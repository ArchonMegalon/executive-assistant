from __future__ import annotations

from app.domain.models import TaskContract, now_utc_iso


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
    assert policy.browseract_timeout_budget_seconds == 1
    assert policy.memory_candidate.confidence == 1.0
    assert policy.human_review.desired_output_json["format"] == "review_packet"
    assert policy.skill_catalog.memory_reads == ()
    assert policy.skill_catalog.evaluation_cases_json == ()
