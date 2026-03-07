from __future__ import annotations

from app.domain.models import IntentSpecV3
from app.services.policy import PolicyDecisionService


def _intent(
    *,
    risk_class: str = "low",
    approval_class: str = "none",
    budget_class: str = "low",
    allowed_tools: tuple[str, ...] = ("artifact_repository",),
) -> IntentSpecV3:
    return IntentSpecV3(
        principal_id="exec-1",
        goal="rewrite",
        task_type="rewrite_text",
        deliverable_type="rewrite_note",
        risk_class=risk_class,
        approval_class=approval_class,
        budget_class=budget_class,
        allowed_tools=allowed_tools,
        memory_write_policy="reviewed_only",
    )


def test_policy_allows_low_risk_rewrite_with_allowed_tool() -> None:
    service = PolicyDecisionService(max_rewrite_chars=200, approval_required_chars=50)
    decision = service.evaluate_rewrite(
        _intent(),
        "short rewrite input",
        tool_name="artifact_repository",
        action_kind="artifact.save",
    )
    assert decision.allow is True
    assert decision.requires_approval is False
    assert decision.reason == "allowed"


def test_policy_denies_disallowed_tool() -> None:
    service = PolicyDecisionService(max_rewrite_chars=200, approval_required_chars=50)
    decision = service.evaluate_rewrite(
        _intent(allowed_tools=("artifact_repository",)),
        "short rewrite input",
        tool_name="email.send",
        action_kind="artifact.save",
    )
    assert decision.allow is False
    assert decision.requires_approval is False
    assert decision.reason == "tool_not_allowed"


def test_policy_requires_approval_for_high_risk() -> None:
    service = PolicyDecisionService(max_rewrite_chars=200, approval_required_chars=50)
    decision = service.evaluate_rewrite(
        _intent(risk_class="high"),
        "short rewrite input",
        tool_name="artifact_repository",
        action_kind="artifact.save",
    )
    assert decision.allow is True
    assert decision.requires_approval is True


def test_policy_requires_approval_for_high_budget() -> None:
    service = PolicyDecisionService(max_rewrite_chars=200, approval_required_chars=50)
    decision = service.evaluate_rewrite(
        _intent(budget_class="critical"),
        "short rewrite input",
        tool_name="artifact_repository",
        action_kind="artifact.save",
    )
    assert decision.allow is True
    assert decision.requires_approval is True


def test_policy_requires_approval_for_external_send_action() -> None:
    service = PolicyDecisionService(max_rewrite_chars=200, approval_required_chars=50)
    decision = service.evaluate_rewrite(
        _intent(),
        "short rewrite input",
        tool_name="artifact_repository",
        action_kind="delivery.send",
        channel="email",
    )
    assert decision.allow is True
    assert decision.requires_approval is True


def test_policy_requires_approval_for_connector_dispatch_step_even_without_explicit_send_action() -> None:
    service = PolicyDecisionService(max_rewrite_chars=200, approval_required_chars=50)
    decision = service.evaluate_step(
        _intent(allowed_tools=("artifact_repository", "connector.dispatch")),
        "short rewrite input",
        tool_name="connector.dispatch",
        action_kind="",
        channel="",
        step_kind="connector_call",
        authority_class="execute",
        review_class="manager",
    )
    assert decision.allow is True
    assert decision.requires_approval is True


def test_policy_allows_draft_artifact_step_without_external_action_metadata() -> None:
    service = PolicyDecisionService(max_rewrite_chars=200, approval_required_chars=50)
    decision = service.evaluate_step(
        _intent(),
        "short rewrite input",
        tool_name="artifact_repository",
        action_kind="artifact.save",
        channel="",
        step_kind="tool_call",
        authority_class="draft",
        review_class="none",
    )
    assert decision.allow is True
    assert decision.requires_approval is False


def test_policy_evaluate_action_alias_matches_step_contract() -> None:
    service = PolicyDecisionService(max_rewrite_chars=200, approval_required_chars=50)
    step_decision = service.evaluate_step(
        _intent(allowed_tools=("artifact_repository", "connector.dispatch")),
        "short rewrite input",
        tool_name="connector.dispatch",
        action_kind="delivery.send",
        channel="email",
        step_kind="connector_call",
        authority_class="execute",
        review_class="manager",
    )
    action_decision = service.evaluate_action(
        _intent(allowed_tools=("artifact_repository", "connector.dispatch")),
        "short rewrite input",
        tool_name="connector.dispatch",
        action_kind="delivery.send",
        channel="email",
        step_kind="connector_call",
        authority_class="execute",
        review_class="manager",
    )

    assert action_decision == step_decision
