from __future__ import annotations

from tests.smoke_runtime_api_support import build_client as _client
from tests.smoke_runtime_api_support import build_headers as _headers


def test_generic_task_execution_supports_async_approval_and_human_contracts() -> None:
    client = _client(storage_backend="memory", principal_id="exec-1")

    approval_contract = client.post(
        "/v1/tasks/contracts",
        json={
            "task_key": "decision_brief_approval",
            "deliverable_type": "decision_brief",
            "default_risk_class": "low",
            "default_approval_class": "manager",
            "allowed_tools": ["artifact_repository"],
            "evidence_requirements": ["decision_context"],
            "memory_write_policy": "reviewed_only",
            "budget_policy_json": {"class": "low"},
        },
    )
    assert approval_contract.status_code == 200

    approval_execute = client.post(
        "/v1/plans/execute",
        json={
            "task_key": "decision_brief_approval",
            "text": "Decision context for the approval-backed briefing.",
            "goal": "prepare a decision brief",
        },
    )
    assert approval_execute.status_code == 202
    approval_body = approval_execute.json()
    assert approval_body["task_key"] == "decision_brief_approval"
    assert approval_body["status"] == "awaiting_approval"
    assert approval_body["approval_id"]
    approval_session_id = approval_body["session_id"]

    approval_session = client.get(f"/v1/rewrite/sessions/{approval_session_id}")
    assert approval_session.status_code == 200
    approval_session_body = approval_session.json()
    assert approval_session_body["intent_task_type"] == "decision_brief_approval"
    assert approval_session_body["status"] == "awaiting_approval"
    generic_approval_steps = {
        step["input_json"]["plan_step_key"]: step
        for step in approval_session_body["steps"]
    }
    assert generic_approval_steps["step_artifact_save"]["state"] == "waiting_approval"
    assert generic_approval_steps["step_artifact_save"]["dependency_keys"] == ["step_policy_evaluate"]
    assert generic_approval_steps["step_artifact_save"]["dependency_states"] == {"step_policy_evaluate": "completed"}
    assert (
        generic_approval_steps["step_artifact_save"]["dependency_step_ids"]["step_policy_evaluate"]
        == generic_approval_steps["step_policy_evaluate"]["step_id"]
    )
    assert generic_approval_steps["step_artifact_save"]["blocked_dependency_keys"] == []
    assert generic_approval_steps["step_artifact_save"]["dependencies_satisfied"] is True

    pending_approvals = client.get("/v1/policy/approvals/pending", params={"limit": 10})
    assert pending_approvals.status_code == 200
    pending_row = next(
        row
        for row in pending_approvals.json()
        if row["approval_id"] == approval_body["approval_id"] and row["session_id"] == approval_session_id
    )
    assert pending_row["task_key"] == "decision_brief_approval"
    assert pending_row["deliverable_type"] == "decision_brief"

    approved = client.post(
        f"/v1/policy/approvals/{approval_body['approval_id']}/approve",
        json={"decided_by": "exec-1", "reason": "approved generic task execution"},
    )
    assert approved.status_code == 200
    assert approved.json()["task_key"] == "decision_brief_approval"
    assert approved.json()["deliverable_type"] == "decision_brief"

    approval_done = client.get(f"/v1/rewrite/sessions/{approval_session_id}")
    assert approval_done.status_code == 200
    approval_done_body = approval_done.json()
    assert approval_done_body["status"] == "completed"
    assert approval_done_body["artifacts"][0]["kind"] == "decision_brief"

    approval_history = client.get("/v1/policy/approvals/history", params={"session_id": approval_session_id, "limit": 10})
    assert approval_history.status_code == 200
    approval_history_row = next(
        row
        for row in approval_history.json()
        if row["approval_id"] == approval_body["approval_id"] and row["decision"] == "approved"
    )
    assert approval_history_row["task_key"] == "decision_brief_approval"
    assert approval_history_row["deliverable_type"] == "decision_brief"

    review_contract = client.post(
        "/v1/tasks/contracts",
        json={
            "task_key": "stakeholder_briefing_review",
            "deliverable_type": "stakeholder_briefing",
            "default_risk_class": "low",
            "default_approval_class": "none",
            "allowed_tools": ["artifact_repository"],
            "evidence_requirements": ["stakeholder_context"],
            "memory_write_policy": "reviewed_only",
            "budget_policy_json": {
                "class": "low",
                "human_review_role": "briefing_reviewer",
                "human_review_task_type": "briefing_review",
                "human_review_brief": "Review the stakeholder briefing before finalization.",
                "human_review_priority": "high",
                "human_review_desired_output_json": {"format": "review_packet"},
            },
        },
    )
    assert review_contract.status_code == 200

    review_execute = client.post(
        "/v1/plans/execute",
        json={
            "task_key": "stakeholder_briefing_review",
            "text": "Stakeholder context for human-reviewed briefing.",
            "goal": "prepare a stakeholder briefing",
        },
    )
    assert review_execute.status_code == 202
    review_body = review_execute.json()
    assert review_body["task_key"] == "stakeholder_briefing_review"
    assert review_body["status"] == "awaiting_human"
    assert review_body["human_task_id"]
    review_session_id = review_body["session_id"]

    review_session = client.get(f"/v1/rewrite/sessions/{review_session_id}")
    assert review_session.status_code == 200
    review_session_body = review_session.json()
    assert review_session_body["intent_task_type"] == "stakeholder_briefing_review"
    assert review_session_body["status"] == "awaiting_human"
    generic_review_steps = {
        step["input_json"]["plan_step_key"]: step
        for step in review_session_body["steps"]
    }
    assert generic_review_steps["step_human_review"]["state"] == "waiting_human"
    assert generic_review_steps["step_human_review"]["dependency_states"] == {"step_policy_evaluate": "completed"}
    assert (
        generic_review_steps["step_human_review"]["dependency_step_ids"]["step_policy_evaluate"]
        == generic_review_steps["step_policy_evaluate"]["step_id"]
    )
    assert generic_review_steps["step_human_review"]["blocked_dependency_keys"] == []
    assert generic_review_steps["step_human_review"]["dependencies_satisfied"] is True
    assert generic_review_steps["step_artifact_save"]["state"] == "queued"
    assert generic_review_steps["step_artifact_save"]["dependency_keys"] == ["step_human_review"]
    assert generic_review_steps["step_artifact_save"]["dependency_states"] == {"step_human_review": "waiting_human"}
    assert (
        generic_review_steps["step_artifact_save"]["dependency_step_ids"]["step_human_review"]
        == generic_review_steps["step_human_review"]["step_id"]
    )
    assert generic_review_steps["step_artifact_save"]["blocked_dependency_keys"] == ["step_human_review"]
    assert generic_review_steps["step_artifact_save"]["dependencies_satisfied"] is False
    assert review_session_body["human_tasks"][0]["task_key"] == "stakeholder_briefing_review"
    assert review_session_body["human_tasks"][0]["deliverable_type"] == "stakeholder_briefing"
    assert review_session_body["human_task_assignment_history"][0]["task_key"] == "stakeholder_briefing_review"
    assert review_session_body["human_task_assignment_history"][0]["deliverable_type"] == "stakeholder_briefing"

    review_list = client.get("/v1/human/tasks", params={"session_id": review_session_id, "limit": 10})
    assert review_list.status_code == 200
    review_list_row = next(row for row in review_list.json() if row["human_task_id"] == review_body["human_task_id"])
    assert review_list_row["task_key"] == "stakeholder_briefing_review"
    assert review_list_row["deliverable_type"] == "stakeholder_briefing"

    review_detail = client.get(f"/v1/human/tasks/{review_body['human_task_id']}")
    assert review_detail.status_code == 200
    assert review_detail.json()["task_key"] == "stakeholder_briefing_review"
    assert review_detail.json()["deliverable_type"] == "stakeholder_briefing"

    review_history = client.get(
        f"/v1/human/tasks/{review_body['human_task_id']}/assignment-history",
        params={"limit": 10},
    )
    assert review_history.status_code == 200
    assert review_history.json()[0]["task_key"] == "stakeholder_briefing_review"
    assert review_history.json()[0]["deliverable_type"] == "stakeholder_briefing"

    returned = client.post(
        f"/v1/human/tasks/{review_body['human_task_id']}/return",
        json={
            "operator_id": "briefing-reviewer",
            "resolution": "ready_for_publish",
            "returned_payload_json": {
                "final_text": "Stakeholder context for human-reviewed briefing, edited by reviewer."
            },
            "provenance_json": {"review_mode": "human"},
        },
    )
    assert returned.status_code == 200
    assert returned.json()["task_key"] == "stakeholder_briefing_review"
    assert returned.json()["deliverable_type"] == "stakeholder_briefing"

    review_done = client.get(f"/v1/rewrite/sessions/{review_session_id}")
    assert review_done.status_code == 200
    review_done_body = review_done.json()
    assert review_done_body["status"] == "completed"
    assert review_done_body["artifacts"][0]["kind"] == "stakeholder_briefing"
    assert (
        review_done_body["artifacts"][0]["content"]
        == "Stakeholder context for human-reviewed briefing, edited by reviewer."
    )


def test_task_contract_workflow_template_can_compile_and_resume_dispatch_branch() -> None:
    client = _client(storage_backend="memory", principal_id="exec-1")

    binding = client.post(
        "/v1/connectors/bindings",
        json={
            "connector_name": "gmail",
            "external_account_ref": "acct-dispatch",
            "scope_json": {"scopes": ["mail.send"]},
            "auth_metadata_json": {"provider": "google"},
            "status": "enabled",
        },
    )
    assert binding.status_code == 200
    binding_id = binding.json()["binding_id"]

    contract = client.post(
        "/v1/tasks/contracts",
        json={
            "task_key": "stakeholder_dispatch",
            "deliverable_type": "stakeholder_briefing",
            "default_risk_class": "low",
            "default_approval_class": "none",
            "allowed_tools": ["artifact_repository", "connector.dispatch"],
            "evidence_requirements": ["stakeholder_context"],
            "memory_write_policy": "reviewed_only",
            "budget_policy_json": {
                "class": "low",
                "workflow_template": "artifact_then_dispatch",
            },
        },
    )
    assert contract.status_code == 200

    compiled = client.post(
        "/v1/plans/compile",
        json={
            "task_key": "stakeholder_dispatch",
            "goal": "prepare and send a stakeholder briefing",
        },
    )
    assert compiled.status_code == 200
    plan_steps = compiled.json()["plan"]["steps"]
    assert [step["step_key"] for step in plan_steps] == [
        "step_input_prepare",
        "step_artifact_save",
        "step_policy_evaluate",
        "step_connector_dispatch",
    ]
    assert plan_steps[1]["tool_name"] == "artifact_repository"
    assert plan_steps[1]["depends_on"] == ["step_input_prepare"]
    assert plan_steps[2]["depends_on"] == ["step_artifact_save"]
    assert plan_steps[3]["tool_name"] == "connector.dispatch"
    assert plan_steps[3]["depends_on"] == ["step_policy_evaluate"]
    assert plan_steps[3]["authority_class"] == "execute"
    assert plan_steps[3]["input_keys"] == ["binding_id", "channel", "recipient", "content"]
    assert plan_steps[3]["output_keys"] == ["delivery_id", "status", "binding_id"]

    execute = client.post(
        "/v1/plans/execute",
        json={
            "task_key": "stakeholder_dispatch",
            "goal": "prepare and send a stakeholder briefing",
            "input_json": {
                "source_text": "Board context and stakeholder sensitivities.",
                "binding_id": binding_id,
                "channel": "email",
                "recipient": "ops@example.com",
            },
        },
    )
    assert execute.status_code == 202
    execute_body = execute.json()
    assert execute_body["task_key"] == "stakeholder_dispatch"
    assert execute_body["status"] == "awaiting_approval"
    assert execute_body["approval_id"]
    session_id = execute_body["session_id"]

    session = client.get(f"/v1/rewrite/sessions/{session_id}")
    assert session.status_code == 200
    session_body = session.json()
    assert session_body["intent_task_type"] == "stakeholder_dispatch"
    assert session_body["status"] == "awaiting_approval"
    steps_by_key = {step["input_json"]["plan_step_key"]: step for step in session_body["steps"]}
    assert steps_by_key["step_artifact_save"]["state"] == "completed"
    assert steps_by_key["step_artifact_save"]["dependency_states"] == {"step_input_prepare": "completed"}
    assert steps_by_key["step_policy_evaluate"]["state"] == "completed"
    assert steps_by_key["step_policy_evaluate"]["dependency_states"] == {"step_artifact_save": "completed"}
    assert steps_by_key["step_connector_dispatch"]["state"] == "waiting_approval"
    assert steps_by_key["step_connector_dispatch"]["dependency_states"] == {"step_policy_evaluate": "completed"}
    assert steps_by_key["step_connector_dispatch"]["blocked_dependency_keys"] == []
    assert steps_by_key["step_connector_dispatch"]["dependencies_satisfied"] is True
    assert len(session_body["artifacts"]) == 1
    assert session_body["artifacts"][0]["kind"] == "stakeholder_briefing"
    assert session_body["artifacts"][0]["content"] == "Board context and stakeholder sensitivities."
    assert [row["tool_name"] for row in session_body["receipts"]] == ["artifact_repository"]

    pending_before = client.get("/v1/delivery/outbox/pending", params={"limit": 10})
    assert pending_before.status_code == 200
    assert pending_before.json() == []

    approved = client.post(
        f"/v1/policy/approvals/{execute_body['approval_id']}/approve",
        json={"decided_by": "exec-1", "reason": "approved dispatch workflow"},
    )
    assert approved.status_code == 200
    assert approved.json()["task_key"] == "stakeholder_dispatch"
    assert approved.json()["deliverable_type"] == "stakeholder_briefing"

    done = client.get(f"/v1/rewrite/sessions/{session_id}")
    assert done.status_code == 200
    done_body = done.json()
    assert done_body["status"] == "completed"
    done_steps = {step["input_json"]["plan_step_key"]: step for step in done_body["steps"]}
    assert done_steps["step_connector_dispatch"]["state"] == "completed"
    assert [row["tool_name"] for row in done_body["receipts"]] == ["artifact_repository", "connector.dispatch"]
    dispatch_receipt = next(row for row in done_body["receipts"] if row["tool_name"] == "connector.dispatch")
    fetched_receipt = client.get(f"/v1/rewrite/receipts/{dispatch_receipt['receipt_id']}")
    assert fetched_receipt.status_code == 200
    assert fetched_receipt.json()["task_key"] == "stakeholder_dispatch"
    assert fetched_receipt.json()["deliverable_type"] == "stakeholder_briefing"

    pending_after = client.get("/v1/delivery/outbox/pending", params={"limit": 10})
    assert pending_after.status_code == 200
    assert pending_after.json()[0]["delivery_id"] == dispatch_receipt["target_ref"]
    assert pending_after.json()[0]["recipient"] == "ops@example.com"


def test_artifact_then_memory_candidate_workflow_template_stages_candidate_over_http() -> None:
    client = _client(storage_backend="memory", principal_id="exec-1")

    contract = client.post(
        "/v1/tasks/contracts",
        json={
            "task_key": "stakeholder_memory_candidate",
            "deliverable_type": "stakeholder_briefing",
            "default_risk_class": "low",
            "default_approval_class": "none",
            "allowed_tools": ["artifact_repository"],
            "evidence_requirements": ["stakeholder_context"],
            "memory_write_policy": "reviewed_only",
            "budget_policy_json": {
                "class": "low",
                "workflow_template": "artifact_then_memory_candidate",
                "memory_candidate_category": "stakeholder_briefing_fact",
                "memory_candidate_confidence": 0.7,
                "memory_candidate_sensitivity": "internal",
            },
        },
    )
    assert contract.status_code == 200

    compiled = client.post(
        "/v1/plans/compile",
        json={
            "task_key": "stakeholder_memory_candidate",
            "goal": "prepare a stakeholder briefing and stage memory",
        },
    )
    assert compiled.status_code == 200
    plan_steps = compiled.json()["plan"]["steps"]
    assert [step["step_key"] for step in plan_steps] == [
        "step_input_prepare",
        "step_policy_evaluate",
        "step_artifact_save",
        "step_memory_candidate_stage",
    ]
    assert plan_steps[1]["output_keys"] == [
        "allow",
        "requires_approval",
        "reason",
        "retention_policy",
        "memory_write_allowed",
    ]
    assert plan_steps[3]["step_kind"] == "memory_write"
    assert plan_steps[3]["depends_on"] == ["step_artifact_save", "step_policy_evaluate"]
    assert plan_steps[3]["authority_class"] == "queue"
    assert plan_steps[3]["review_class"] == "operator"
    assert plan_steps[3]["input_keys"] == ["artifact_id", "normalized_text", "memory_write_allowed"]
    assert plan_steps[3]["output_keys"] == ["candidate_id", "candidate_status", "candidate_category"]
    assert plan_steps[3]["desired_output_json"]["category"] == "stakeholder_briefing_fact"
    assert plan_steps[3]["desired_output_json"]["confidence"] == 0.7

    execute = client.post(
        "/v1/plans/execute",
        json={
            "task_key": "stakeholder_memory_candidate",
            "goal": "prepare a stakeholder briefing and stage memory",
            "input_json": {
                "source_text": "Board context and stakeholder sensitivities.",
            },
        },
    )
    assert execute.status_code == 200
    execute_body = execute.json()
    assert execute_body["task_key"] == "stakeholder_memory_candidate"
    assert execute_body["kind"] == "stakeholder_briefing"
    assert execute_body["deliverable_type"] == "stakeholder_briefing"
    assert execute_body["content"] == "Board context and stakeholder sensitivities."
    assert execute_body["principal_id"] == "exec-1"
    session_id = execute_body["execution_session_id"]

    session = client.get(f"/v1/rewrite/sessions/{session_id}")
    assert session.status_code == 200
    session_body = session.json()
    assert session_body["intent_task_type"] == "stakeholder_memory_candidate"
    assert session_body["status"] == "completed"
    steps_by_key = {step["input_json"]["plan_step_key"]: step for step in session_body["steps"]}
    assert steps_by_key["step_policy_evaluate"]["state"] == "completed"
    assert steps_by_key["step_artifact_save"]["state"] == "completed"
    assert steps_by_key["step_memory_candidate_stage"]["state"] == "completed"
    assert steps_by_key["step_memory_candidate_stage"]["dependency_states"] == {
        "step_artifact_save": "completed",
        "step_policy_evaluate": "completed",
    }
    assert steps_by_key["step_memory_candidate_stage"]["blocked_dependency_keys"] == []
    assert steps_by_key["step_memory_candidate_stage"]["dependencies_satisfied"] is True
    assert steps_by_key["step_memory_candidate_stage"]["output_json"]["candidate_status"] == "pending"
    assert steps_by_key["step_memory_candidate_stage"]["output_json"]["candidate_category"] == "stakeholder_briefing_fact"
    candidate_id = steps_by_key["step_memory_candidate_stage"]["output_json"]["candidate_id"]
    assert candidate_id

    candidates = client.get("/v1/memory/candidates", params={"limit": 20, "status": "pending"})
    assert candidates.status_code == 200
    candidate = next(row for row in candidates.json() if row["candidate_id"] == candidate_id)
    assert candidate["principal_id"] == "exec-1"
    assert candidate["category"] == "stakeholder_briefing_fact"
    assert candidate["summary"] == "Board context and stakeholder sensitivities."
    assert candidate["source_session_id"] == session_id
    assert candidate["source_step_id"] == steps_by_key["step_memory_candidate_stage"]["step_id"]


def test_dispatch_then_memory_candidate_workflow_template_stages_candidate_after_approval_over_http() -> None:
    client = _client(storage_backend="memory", principal_id="exec-1")

    binding = client.post(
        "/v1/connectors/bindings",
        json={
            "connector_name": "gmail",
            "external_account_ref": "acct-dispatch-memory",
            "scope_json": {"scopes": ["mail.send"]},
            "auth_metadata_json": {"provider": "google"},
            "status": "enabled",
        },
    )
    assert binding.status_code == 200
    binding_id = binding.json()["binding_id"]

    contract = client.post(
        "/v1/tasks/contracts",
        json={
            "task_key": "stakeholder_dispatch_memory_candidate",
            "deliverable_type": "stakeholder_briefing",
            "default_risk_class": "low",
            "default_approval_class": "none",
            "allowed_tools": ["artifact_repository", "connector.dispatch"],
            "evidence_requirements": ["stakeholder_context"],
            "memory_write_policy": "reviewed_only",
            "budget_policy_json": {
                "class": "low",
                "workflow_template": "artifact_then_dispatch_then_memory_candidate",
                "memory_candidate_category": "stakeholder_follow_up_fact",
                "memory_candidate_confidence": 0.8,
                "memory_candidate_sensitivity": "internal",
            },
        },
    )
    assert contract.status_code == 200

    compiled = client.post(
        "/v1/plans/compile",
        json={
            "task_key": "stakeholder_dispatch_memory_candidate",
            "goal": "prepare, send, and stage stakeholder follow-up memory",
        },
    )
    assert compiled.status_code == 200
    plan_steps = compiled.json()["plan"]["steps"]
    assert [step["step_key"] for step in plan_steps] == [
        "step_input_prepare",
        "step_artifact_save",
        "step_policy_evaluate",
        "step_connector_dispatch",
        "step_memory_candidate_stage",
    ]
    assert plan_steps[4]["depends_on"] == [
        "step_artifact_save",
        "step_policy_evaluate",
        "step_connector_dispatch",
    ]
    assert plan_steps[4]["input_keys"] == [
        "artifact_id",
        "normalized_text",
        "memory_write_allowed",
        "delivery_id",
        "status",
        "binding_id",
        "channel",
        "recipient",
    ]
    assert plan_steps[4]["desired_output_json"]["category"] == "stakeholder_follow_up_fact"

    execute = client.post(
        "/v1/plans/execute",
        json={
            "task_key": "stakeholder_dispatch_memory_candidate",
            "goal": "prepare, send, and stage stakeholder follow-up memory",
            "input_json": {
                "source_text": "Board context and stakeholder sensitivities.",
                "binding_id": binding_id,
                "channel": "email",
                "recipient": "dispatch-memory@example.com",
            },
        },
    )
    assert execute.status_code == 202
    execute_body = execute.json()
    assert execute_body["status"] == "awaiting_approval"
    assert execute_body["approval_id"]
    session_id = execute_body["session_id"]

    waiting = client.get(f"/v1/rewrite/sessions/{session_id}")
    assert waiting.status_code == 200
    waiting_body = waiting.json()
    assert waiting_body["status"] == "awaiting_approval"
    waiting_steps = {step["input_json"]["plan_step_key"]: step for step in waiting_body["steps"]}
    assert waiting_steps["step_artifact_save"]["state"] == "completed"
    assert waiting_steps["step_policy_evaluate"]["state"] == "completed"
    assert waiting_steps["step_connector_dispatch"]["state"] == "waiting_approval"
    assert waiting_steps["step_memory_candidate_stage"]["state"] == "queued"
    assert waiting_steps["step_memory_candidate_stage"]["dependency_states"] == {
        "step_artifact_save": "completed",
        "step_policy_evaluate": "completed",
        "step_connector_dispatch": "waiting_approval",
    }
    assert waiting_steps["step_memory_candidate_stage"]["blocked_dependency_keys"] == ["step_connector_dispatch"]
    before_candidates = client.get("/v1/memory/candidates", params={"limit": 20, "status": "pending"})
    assert before_candidates.status_code == 200
    assert all(row["source_session_id"] != session_id for row in before_candidates.json())

    approved = client.post(
        f"/v1/policy/approvals/{execute_body['approval_id']}/approve",
        json={"decided_by": "exec-1", "reason": "approved dispatch memory workflow"},
    )
    assert approved.status_code == 200
    assert approved.json()["task_key"] == "stakeholder_dispatch_memory_candidate"
    assert approved.json()["deliverable_type"] == "stakeholder_briefing"

    done = client.get(f"/v1/rewrite/sessions/{session_id}")
    assert done.status_code == 200
    done_body = done.json()
    assert done_body["status"] == "completed"
    done_steps = {step["input_json"]["plan_step_key"]: step for step in done_body["steps"]}
    assert done_steps["step_connector_dispatch"]["state"] == "completed"
    assert done_steps["step_memory_candidate_stage"]["state"] == "completed"
    candidate_id = done_steps["step_memory_candidate_stage"]["output_json"]["candidate_id"]
    assert candidate_id
    dispatch_receipt = next(row for row in done_body["receipts"] if row["tool_name"] == "connector.dispatch")
    pending = client.get("/v1/delivery/outbox/pending", params={"limit": 20})
    assert pending.status_code == 200
    delivery = next(row for row in pending.json() if row["delivery_id"] == dispatch_receipt["target_ref"])
    assert delivery["recipient"] == "dispatch-memory@example.com"
    candidates = client.get("/v1/memory/candidates", params={"limit": 20, "status": "pending"})
    assert candidates.status_code == 200
    candidate = next(row for row in candidates.json() if row["candidate_id"] == candidate_id)
    assert candidate["category"] == "stakeholder_follow_up_fact"
    assert candidate["source_session_id"] == session_id
    assert candidate["summary"] == "Board context and stakeholder sensitivities."
    assert candidate["fact_json"]["delivery_id"] == dispatch_receipt["target_ref"]
    assert candidate["fact_json"]["recipient"] == "dispatch-memory@example.com"


def test_review_then_dispatch_then_memory_candidate_workflow_template_stages_candidate_after_human_and_approval_over_http() -> None:
    client = _client(storage_backend="memory", principal_id="exec-1")

    binding = client.post(
        "/v1/connectors/bindings",
        json={
            "connector_name": "gmail",
            "external_account_ref": "acct-review-dispatch-memory",
            "scope_json": {"scopes": ["mail.send"]},
            "auth_metadata_json": {"provider": "google"},
            "status": "enabled",
        },
    )
    assert binding.status_code == 200
    binding_id = binding.json()["binding_id"]

    contract = client.post(
        "/v1/tasks/contracts",
        json={
            "task_key": "stakeholder_review_dispatch_memory_candidate",
            "deliverable_type": "stakeholder_briefing",
            "default_risk_class": "low",
            "default_approval_class": "none",
            "allowed_tools": ["artifact_repository", "connector.dispatch"],
            "evidence_requirements": ["stakeholder_context"],
            "memory_write_policy": "reviewed_only",
            "budget_policy_json": {
                "class": "low",
                "workflow_template": "artifact_then_dispatch_then_memory_candidate",
                "human_review_role": "briefing_reviewer",
                "human_review_task_type": "briefing_review",
                "human_review_brief": "Review before stakeholder dispatch and memory staging.",
                "human_review_priority": "high",
                "human_review_desired_output_json": {"format": "review_packet"},
                "memory_candidate_category": "stakeholder_follow_up_fact",
                "memory_candidate_confidence": 0.8,
                "memory_candidate_sensitivity": "internal",
            },
        },
    )
    assert contract.status_code == 200

    compiled = client.post(
        "/v1/plans/compile",
        json={
            "task_key": "stakeholder_review_dispatch_memory_candidate",
            "goal": "review, send, and stage stakeholder follow-up memory",
        },
    )
    assert compiled.status_code == 200
    assert [step["step_key"] for step in compiled.json()["plan"]["steps"]] == [
        "step_input_prepare",
        "step_human_review",
        "step_artifact_save",
        "step_policy_evaluate",
        "step_connector_dispatch",
        "step_memory_candidate_stage",
    ]

    execute = client.post(
        "/v1/plans/execute",
        json={
            "task_key": "stakeholder_review_dispatch_memory_candidate",
            "goal": "review, send, and stage stakeholder follow-up memory",
            "input_json": {
                "source_text": "Board context and stakeholder sensitivities.",
                "binding_id": binding_id,
                "channel": "email",
                "recipient": "reviewed-memory@example.com",
            },
        },
    )
    assert execute.status_code == 202
    execute_body = execute.json()
    assert execute_body["status"] == "awaiting_human"
    assert execute_body["human_task_id"]
    session_id = execute_body["session_id"]

    waiting = client.get(f"/v1/rewrite/sessions/{session_id}")
    assert waiting.status_code == 200
    waiting_body = waiting.json()
    assert waiting_body["status"] == "awaiting_human"
    waiting_steps = {step["input_json"]["plan_step_key"]: step for step in waiting_body["steps"]}
    assert waiting_steps["step_human_review"]["state"] == "waiting_human"
    assert waiting_steps["step_artifact_save"]["state"] == "queued"
    assert waiting_steps["step_memory_candidate_stage"]["state"] == "queued"
    before_candidates = client.get("/v1/memory/candidates", params={"limit": 20, "status": "pending"})
    assert before_candidates.status_code == 200
    assert all(row["source_session_id"] != session_id for row in before_candidates.json())

    returned = client.post(
        f"/v1/human/tasks/{execute_body['human_task_id']}/return",
        json={
            "operator_id": "briefing-reviewer",
            "resolution": "ready_for_dispatch",
            "returned_payload_json": {"final_text": "Reviewed stakeholder briefing with follow-up notes."},
            "provenance_json": {"review_mode": "human"},
        },
    )
    assert returned.status_code == 200

    awaiting_approval = client.get(f"/v1/rewrite/sessions/{session_id}")
    assert awaiting_approval.status_code == 200
    awaiting_approval_body = awaiting_approval.json()
    assert awaiting_approval_body["status"] == "awaiting_approval"
    approval_steps = {step["input_json"]["plan_step_key"]: step for step in awaiting_approval_body["steps"]}
    assert approval_steps["step_human_review"]["state"] == "completed"
    assert approval_steps["step_artifact_save"]["state"] == "completed"
    assert approval_steps["step_policy_evaluate"]["state"] == "completed"
    assert approval_steps["step_connector_dispatch"]["state"] == "waiting_approval"
    assert approval_steps["step_memory_candidate_stage"]["state"] == "queued"
    assert awaiting_approval_body["artifacts"][0]["content"] == "Reviewed stakeholder briefing with follow-up notes."

    approvals = client.get("/v1/policy/approvals/pending", params={"limit": 20})
    assert approvals.status_code == 200
    approval_row = next(row for row in approvals.json() if row["session_id"] == session_id)

    approved = client.post(
        f"/v1/policy/approvals/{approval_row['approval_id']}/approve",
        json={"decided_by": "exec-1", "reason": "approved reviewed dispatch memory workflow"},
    )
    assert approved.status_code == 200
    assert approved.json()["task_key"] == "stakeholder_review_dispatch_memory_candidate"

    done = client.get(f"/v1/rewrite/sessions/{session_id}")
    assert done.status_code == 200
    done_body = done.json()
    assert done_body["status"] == "completed"
    done_steps = {step["input_json"]["plan_step_key"]: step for step in done_body["steps"]}
    assert done_steps["step_connector_dispatch"]["state"] == "completed"
    assert done_steps["step_memory_candidate_stage"]["state"] == "completed"
    candidate_id = done_steps["step_memory_candidate_stage"]["output_json"]["candidate_id"]
    assert candidate_id
    dispatch_receipt = next(row for row in done_body["receipts"] if row["tool_name"] == "connector.dispatch")
    pending = client.get("/v1/delivery/outbox/pending", params={"limit": 20})
    assert pending.status_code == 200
    delivery = next(row for row in pending.json() if row["delivery_id"] == dispatch_receipt["target_ref"])
    assert delivery["recipient"] == "reviewed-memory@example.com"
    candidates = client.get("/v1/memory/candidates", params={"limit": 20, "status": "pending"})
    assert candidates.status_code == 200
    candidate = next(row for row in candidates.json() if row["candidate_id"] == candidate_id)
    assert candidate["category"] == "stakeholder_follow_up_fact"
    assert candidate["source_session_id"] == session_id
    assert candidate["summary"] == "Reviewed stakeholder briefing with follow-up notes."
    assert candidate["fact_json"]["delivery_id"] == dispatch_receipt["target_ref"]
    assert candidate["fact_json"]["recipient"] == "reviewed-memory@example.com"


def test_review_then_dispatch_workflow_template_pauses_for_human_then_approval_over_http() -> None:
    client = _client(storage_backend="memory", principal_id="exec-1")

    binding = client.post(
        "/v1/connectors/bindings",
        json={
            "connector_name": "gmail",
            "external_account_ref": "acct-review-dispatch",
            "scope_json": {"scopes": ["mail.send"]},
            "auth_metadata_json": {"provider": "google"},
            "status": "enabled",
        },
    )
    assert binding.status_code == 200
    binding_id = binding.json()["binding_id"]

    contract = client.post(
        "/v1/tasks/contracts",
        json={
            "task_key": "stakeholder_review_dispatch",
            "deliverable_type": "stakeholder_briefing",
            "default_risk_class": "low",
            "default_approval_class": "none",
            "allowed_tools": ["artifact_repository", "connector.dispatch"],
            "evidence_requirements": ["stakeholder_context"],
            "memory_write_policy": "reviewed_only",
            "budget_policy_json": {
                "class": "low",
                "workflow_template": "artifact_then_dispatch",
                "human_review_role": "briefing_reviewer",
                "human_review_task_type": "briefing_review",
                "human_review_brief": "Review before stakeholder dispatch.",
                "human_review_priority": "high",
                "human_review_desired_output_json": {"format": "review_packet"},
            },
        },
    )
    assert contract.status_code == 200

    execute = client.post(
        "/v1/plans/execute",
        json={
            "task_key": "stakeholder_review_dispatch",
            "goal": "review and send a stakeholder briefing",
            "input_json": {
                "source_text": "Board context and stakeholder sensitivities.",
                "binding_id": binding_id,
                "channel": "email",
                "recipient": "hybrid@example.com",
            },
        },
    )
    assert execute.status_code == 202
    execute_body = execute.json()
    assert execute_body["task_key"] == "stakeholder_review_dispatch"
    assert execute_body["status"] == "awaiting_human"
    assert execute_body["human_task_id"]
    session_id = execute_body["session_id"]

    waiting = client.get(f"/v1/rewrite/sessions/{session_id}")
    assert waiting.status_code == 200
    waiting_body = waiting.json()
    assert waiting_body["status"] == "awaiting_human"
    waiting_steps = {step["input_json"]["plan_step_key"]: step for step in waiting_body["steps"]}
    assert waiting_steps["step_human_review"]["state"] == "waiting_human"
    assert waiting_steps["step_human_review"]["dependency_states"] == {"step_input_prepare": "completed"}
    assert waiting_steps["step_artifact_save"]["state"] == "queued"
    assert waiting_steps["step_artifact_save"]["dependency_states"] == {"step_human_review": "waiting_human"}
    assert waiting_body["artifacts"] == []

    pending_before = client.get("/v1/delivery/outbox/pending", params={"limit": 20})
    assert pending_before.status_code == 200
    assert all(row["recipient"] != "hybrid@example.com" for row in pending_before.json())

    returned = client.post(
        f"/v1/human/tasks/{execute_body['human_task_id']}/return",
        json={
            "operator_id": "briefing-reviewer",
            "resolution": "ready_for_dispatch",
            "returned_payload_json": {"final_text": "Reviewed stakeholder briefing."},
            "provenance_json": {"review_mode": "human"},
        },
    )
    assert returned.status_code == 200
    assert returned.json()["task_key"] == "stakeholder_review_dispatch"

    awaiting_approval = client.get(f"/v1/rewrite/sessions/{session_id}")
    assert awaiting_approval.status_code == 200
    awaiting_approval_body = awaiting_approval.json()
    assert awaiting_approval_body["status"] == "awaiting_approval"
    approval_steps = {step["input_json"]["plan_step_key"]: step for step in awaiting_approval_body["steps"]}
    assert approval_steps["step_human_review"]["state"] == "completed"
    assert approval_steps["step_artifact_save"]["state"] == "completed"
    assert approval_steps["step_policy_evaluate"]["state"] == "completed"
    assert approval_steps["step_connector_dispatch"]["state"] == "waiting_approval"
    assert awaiting_approval_body["artifacts"][0]["content"] == "Reviewed stakeholder briefing."

    approvals = client.get("/v1/policy/approvals/pending", params={"limit": 20})
    assert approvals.status_code == 200
    approval_row = next(row for row in approvals.json() if row["session_id"] == session_id)

    approved = client.post(
        f"/v1/policy/approvals/{approval_row['approval_id']}/approve",
        json={"decided_by": "exec-1", "reason": "approved reviewed dispatch"},
    )
    assert approved.status_code == 200
    assert approved.json()["task_key"] == "stakeholder_review_dispatch"

    done = client.get(f"/v1/rewrite/sessions/{session_id}")
    assert done.status_code == 200
    done_body = done.json()
    assert done_body["status"] == "completed"
    assert [row["tool_name"] for row in done_body["receipts"]] == ["artifact_repository", "connector.dispatch"]
    dispatch_receipt = next(row for row in done_body["receipts"] if row["tool_name"] == "connector.dispatch")
    pending_after = client.get("/v1/delivery/outbox/pending", params={"limit": 20})
    assert pending_after.status_code == 200
    queued = next(row for row in pending_after.json() if row["delivery_id"] == dispatch_receipt["target_ref"])
    assert queued["recipient"] == "hybrid@example.com"


def test_review_then_dispatch_delayed_retry_stays_queued_after_http_approval() -> None:
    client = _client(storage_backend="memory", principal_id="exec-1")

    contract = client.post(
        "/v1/tasks/contracts",
        json={
            "task_key": "stakeholder_review_dispatch_retry",
            "deliverable_type": "stakeholder_briefing",
            "default_risk_class": "low",
            "default_approval_class": "none",
            "allowed_tools": ["artifact_repository", "connector.dispatch"],
            "evidence_requirements": ["stakeholder_context"],
            "memory_write_policy": "reviewed_only",
            "budget_policy_json": {
                "class": "low",
                "workflow_template": "artifact_then_dispatch",
                "human_review_role": "briefing_reviewer",
                "human_review_task_type": "briefing_review",
                "human_review_brief": "Review before stakeholder dispatch.",
                "human_review_priority": "high",
                "human_review_desired_output_json": {"format": "review_packet"},
                "dispatch_failure_strategy": "retry",
                "dispatch_max_attempts": 2,
                "dispatch_retry_backoff_seconds": 45,
            },
        },
    )
    assert contract.status_code == 200

    execute = client.post(
        "/v1/plans/execute",
        json={
            "task_key": "stakeholder_review_dispatch_retry",
            "goal": "review and send a stakeholder briefing",
            "input_json": {
                "source_text": "Board context and stakeholder sensitivities.",
                "binding_id": "missing-review-dispatch-binding",
                "channel": "email",
                "recipient": "hybrid-retry@example.com",
            },
        },
    )
    assert execute.status_code == 202
    execute_body = execute.json()
    assert execute_body["status"] == "awaiting_human"
    assert execute_body["human_task_id"]
    session_id = execute_body["session_id"]

    returned = client.post(
        f"/v1/human/tasks/{execute_body['human_task_id']}/return",
        json={
            "operator_id": "briefing-reviewer",
            "resolution": "ready_for_dispatch",
            "returned_payload_json": {"final_text": "Reviewed stakeholder briefing."},
            "provenance_json": {"review_mode": "human"},
        },
    )
    assert returned.status_code == 200

    awaiting_approval = client.get(f"/v1/rewrite/sessions/{session_id}")
    assert awaiting_approval.status_code == 200
    awaiting_approval_body = awaiting_approval.json()
    assert awaiting_approval_body["status"] == "awaiting_approval"

    approvals = client.get("/v1/policy/approvals/pending", params={"limit": 20})
    assert approvals.status_code == 200
    approval_row = next(row for row in approvals.json() if row["session_id"] == session_id)

    approved = client.post(
        f"/v1/policy/approvals/{approval_row['approval_id']}/approve",
        json={"decided_by": "exec-1", "reason": "approve reviewed dispatch retry"},
    )
    assert approved.status_code == 200
    assert approved.json()["task_key"] == "stakeholder_review_dispatch_retry"
    assert approved.json()["deliverable_type"] == "stakeholder_briefing"

    queued = client.get(f"/v1/rewrite/sessions/{session_id}")
    assert queued.status_code == 200
    queued_body = queued.json()
    assert queued_body["status"] == "queued"
    queued_steps = {step["input_json"]["plan_step_key"]: step for step in queued_body["steps"]}
    assert queued_steps["step_human_review"]["state"] == "completed"
    assert queued_steps["step_artifact_save"]["state"] == "completed"
    assert queued_steps["step_policy_evaluate"]["state"] == "completed"
    assert queued_steps["step_connector_dispatch"]["state"] == "queued"
    assert queued_steps["step_connector_dispatch"]["error_json"]["reason"] == "retry_scheduled"
    assert queued_body["queue_items"][-1]["state"] == "queued"
    assert queued_body["queue_items"][-1]["next_attempt_at"]
    pending_after = client.get("/v1/delivery/outbox/pending", params={"limit": 20})
    assert pending_after.status_code == 200
    assert all(row["recipient"] != "hybrid-retry@example.com" for row in pending_after.json())


def test_rewrite_compiled_human_review_branch_pauses_and_resumes() -> None:
    client = _client(storage_backend="memory")
    contract = client.post(
        "/v1/tasks/contracts",
        json={
            "task_key": "rewrite_text",
            "deliverable_type": "rewrite_note",
            "default_risk_class": "low",
            "default_approval_class": "none",
            "allowed_tools": ["artifact_repository"],
            "evidence_requirements": ["stakeholder_context"],
            "memory_write_policy": "reviewed_only",
            "budget_policy_json": {
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
        },
    )
    assert contract.status_code == 200

    operator_profile = client.post(
        "/v1/human/tasks/operators",
        json={
            "operator_id": "operator-specialist",
            "display_name": "Senior Comms Reviewer",
            "roles": ["communications_reviewer"],
            "skill_tags": ["tone", "accuracy", "stakeholder_sensitivity"],
            "trust_tier": "senior",
            "status": "active",
        },
    )
    assert operator_profile.status_code == 200
    operator_low = client.post(
        "/v1/human/tasks/operators",
        json={
            "operator_id": "operator-junior",
            "display_name": "Junior Reviewer",
            "roles": ["communications_reviewer"],
            "skill_tags": ["tone"],
            "trust_tier": "standard",
            "status": "active",
        },
    )
    assert operator_low.status_code == 200

    create = client.post("/v1/rewrite/artifact", json={"text": "rewrite with human review"})
    assert create.status_code == 202
    assert create.json()["status"] == "awaiting_human"
    assert create.json()["human_task_id"]
    assert create.json()["approval_id"] == ""
    session_id = create.json()["session_id"]
    human_task_id = create.json()["human_task_id"]

    session = client.get(f"/v1/rewrite/sessions/{session_id}")
    assert session.status_code == 200
    body = session.json()
    assert body["status"] == "awaiting_human"
    assert len(body["steps"]) == 4
    assert body["steps"][2]["input_json"]["plan_step_key"] == "step_human_review"
    assert body["steps"][2]["input_json"]["owner"] == "human"
    assert body["steps"][2]["input_json"]["authority_class"] == "draft"
    assert body["steps"][2]["input_json"]["review_class"] == "operator"
    assert body["steps"][2]["input_json"]["failure_strategy"] == "fail"
    assert body["steps"][2]["input_json"]["timeout_budget_seconds"] == 3600
    review_steps = {
        step["input_json"]["plan_step_key"]: step
        for step in body["steps"]
    }
    assert review_steps["step_human_review"]["state"] == "waiting_human"
    assert review_steps["step_human_review"]["dependency_keys"] == ["step_policy_evaluate"]
    assert review_steps["step_human_review"]["dependency_states"] == {"step_policy_evaluate": "completed"}
    assert (
        review_steps["step_human_review"]["dependency_step_ids"]["step_policy_evaluate"]
        == review_steps["step_policy_evaluate"]["step_id"]
    )
    assert review_steps["step_human_review"]["blocked_dependency_keys"] == []
    assert review_steps["step_human_review"]["dependencies_satisfied"] is True
    assert review_steps["step_artifact_save"]["state"] == "queued"
    assert review_steps["step_artifact_save"]["dependency_keys"] == ["step_human_review"]
    assert review_steps["step_artifact_save"]["dependency_states"] == {"step_human_review": "waiting_human"}
    assert (
        review_steps["step_artifact_save"]["dependency_step_ids"]["step_human_review"]
        == review_steps["step_human_review"]["step_id"]
    )
    assert review_steps["step_artifact_save"]["blocked_dependency_keys"] == ["step_human_review"]
    assert review_steps["step_artifact_save"]["dependencies_satisfied"] is False
    assert len(body["queue_items"]) == 3
    assert all(item["state"] == "done" for item in body["queue_items"])
    assert any(row["human_task_id"] == human_task_id and row["status"] == "pending" for row in body["human_tasks"])
    review_task = next(row for row in body["human_tasks"] if row["human_task_id"] == human_task_id)
    assert review_task["priority"] == "high"
    assert review_task["sla_due_at"]
    assert review_task["desired_output_json"]["escalation_policy"] == "manager_review"
    assert review_task["authority_required"] == "send_on_behalf_review"
    assert review_task["why_human"] == "Executive-facing rewrite needs human judgment before finalization."
    assert review_task["quality_rubric_json"]["checks"][0] == "tone"
    assert review_task["assignment_state"] == "assigned"
    assert review_task["assigned_operator_id"] == "operator-specialist"
    assert review_task["assignment_source"] == "auto_preselected"
    assert review_task["assigned_at"]
    # operator guard anchor: review_task["last_transition_event_name"] == "human_task_assigned"
    assert review_task["assigned_by_actor_id"] == "orchestrator:auto_preselected"
    assert review_task["last_transition_event_name"] in {"human_task_assigned", ""}
    assert review_task["last_transition_at"]
    assert review_task["last_transition_assignment_state"] == "assigned"
    assert review_task["last_transition_operator_id"] == "operator-specialist"
    assert review_task["last_transition_assignment_source"] == "auto_preselected"
    assert review_task["last_transition_by_actor_id"] == "orchestrator:auto_preselected"
    assert [row["event_name"] for row in body["human_task_assignment_history"]] == [
        "human_task_created",
        "human_task_assigned",
    ]
    assert body["human_task_assignment_history"][1]["assigned_operator_id"] == "operator-specialist"
    assert body["human_task_assignment_history"][1]["assignment_source"] == "auto_preselected"
    assert review_task["routing_hints_json"]["recommended_operator_id"] == "operator-specialist"
    assert review_task["routing_hints_json"]["auto_assign_operator_id"] == ""
    assert review_task["routing_hints_json"]["candidate_count"] == 1

    auto_only = client.get(
        f"/v1/rewrite/sessions/{session_id}",
        params={"human_task_assignment_source": "auto_preselected"},
    )
    assert auto_only.status_code == 200
    auto_only_body = auto_only.json()
    assert len(auto_only_body["human_tasks"]) == 1
    assert auto_only_body["human_tasks"][0]["human_task_id"] == human_task_id
    assert [row["event_name"] for row in auto_only_body["human_task_assignment_history"]] == [
        "human_task_assigned"
    ]

    reviewed_text = "rewrite with human review, edited by reviewer"
    returned = client.post(
        f"/v1/human/tasks/{human_task_id}/return",
        json={
            "operator_id": "reviewer-1",
            "resolution": "ready_for_send",
            "returned_payload_json": {"final_text": reviewed_text},
            "provenance_json": {"review_mode": "human"},
        },
    )
    assert returned.status_code == 200
    assert returned.json()["status"] == "returned"
    assert returned.json()["last_transition_event_name"] in {"human_task_returned", ""}
    assert returned.json()["last_transition_assignment_state"] == "returned"
    assert returned.json()["last_transition_operator_id"] == "reviewer-1"
    assert returned.json()["last_transition_assignment_source"] == "manual"
    assert returned.json()["last_transition_by_actor_id"] == "reviewer-1"

    session_after = client.get(f"/v1/rewrite/sessions/{session_id}")
    assert session_after.status_code == 200
    body_after = session_after.json()
    event_names = [row["name"] for row in body_after["events"]]
    assert body_after["status"] == "completed"
    assert "human_task_step_started" in event_names
    assert "human_task_created" in event_names
    assert "human_task_returned" in event_names
    assert "session_resumed_from_human_task" in event_names
    assert "tool_execution_completed" in event_names
    assert len(body_after["queue_items"]) == 4
    assert all(item["state"] == "done" for item in body_after["queue_items"])
    assert len(body_after["artifacts"]) == 1
    assert body_after["artifacts"][0]["content"] == reviewed_text
    assert body_after["steps"][2]["state"] == "completed"
    assert body_after["steps"][3]["state"] == "completed"


def test_evidence_object_routes_materialize_and_merge_evidence_pack_artifacts() -> None:
    client = _client(storage_backend="memory", principal_id="exec-1")

    contract = client.post(
        "/v1/tasks/contracts",
        json={
            "task_key": "research_brief",
            "deliverable_type": "decision_summary",
            "default_risk_class": "low",
            "default_approval_class": "none",
            "allowed_tools": ["artifact_repository"],
            "evidence_requirements": ["decision_context"],
            "memory_write_policy": "reviewed_only",
            "budget_policy_json": {
                "class": "low",
                "workflow_template": "artifact_then_memory_candidate",
                "artifact_output_template": "evidence_pack",
                "evidence_pack_confidence": 0.72,
            },
        },
    )
    assert contract.status_code == 200

    first = client.post(
        "/v1/plans/execute",
        json={
            "task_key": "research_brief",
            "goal": "prepare an evidence-backed brief",
            "input_json": {
                "source_text": "Market conditions suggest two viable options.",
                "claims": ["Option A preserves margin", "Option B accelerates launch"],
                "evidence_refs": ["browseract://run/123", "paper://abc"],
                "open_questions": ["Need final vendor pricing"],
            },
        },
    )
    assert first.status_code == 200
    first_body = first.json()

    second = client.post(
        "/v1/plans/execute",
        json={
            "task_key": "research_brief",
            "goal": "prepare an evidence-backed brief",
            "input_json": {
                "source_text": "Support load may fall if the simpler option ships first.",
                "claims": ["Option C reduces support load"],
                "evidence_refs": ["paper://abc", "call://ops-review"],
                "open_questions": ["Need service staffing forecast"],
                "confidence": 0.58,
            },
        },
    )
    assert second.status_code == 200
    second_body = second.json()

    listed = client.get(
        "/v1/evidence/objects",
        params={"limit": 10, "artifact_id": first_body["artifact_id"], "principal_id": "exec-1"},
    )
    assert listed.status_code == 200
    rows = listed.json()
    assert len(rows) == 1
    assert rows[0]["artifact_id"] == first_body["artifact_id"]
    assert rows[0]["claims"] == ["Option A preserves margin", "Option B accelerates launch"]
    assert rows[0]["evidence_refs"] == ["browseract://run/123", "paper://abc"]
    assert rows[0]["citation_handle"].startswith("evidence://")
    first_evidence_id = rows[0]["evidence_id"]

    ref_list = client.get("/v1/evidence/objects", params={"limit": 10, "evidence_ref": "paper://abc"})
    assert ref_list.status_code == 200
    ref_ids = {row["artifact_id"] for row in ref_list.json()}
    assert first_body["artifact_id"] in ref_ids
    assert second_body["artifact_id"] in ref_ids

    fetched = client.get(f"/v1/evidence/objects/{first_evidence_id}")
    assert fetched.status_code == 200
    assert fetched.json()["artifact_id"] == first_body["artifact_id"]

    second_evidence_id = next(
        row["evidence_id"] for row in ref_list.json() if row["artifact_id"] == second_body["artifact_id"]
    )
    merged = client.post(
        "/v1/evidence/merge",
        json={"principal_id": "exec-1", "evidence_ids": [first_evidence_id, second_evidence_id]},
    )
    assert merged.status_code == 200
    merged_body = merged.json()
    assert merged_body["format"] == "evidence_pack"
    assert merged_body["claims"] == [
        "Option A preserves margin",
        "Option B accelerates launch",
        "Option C reduces support load",
    ]
    assert merged_body["evidence_refs"] == ["browseract://run/123", "paper://abc", "call://ops-review"]
    assert merged_body["open_questions"] == ["Need final vendor pricing", "Need service staffing forecast"]
    assert merged_body["source_artifact_ids"] == [first_body["artifact_id"], second_body["artifact_id"]]
    assert len(merged_body["citation_handles"]) == 2

    mismatch = client.get("/v1/evidence/objects", params={"limit": 10, "principal_id": "exec-2"})
    assert mismatch.status_code == 403
    assert mismatch.json()["error"]["code"] == "principal_scope_mismatch"


def test_memory_candidate_promotion_flow() -> None:
    client = _client(storage_backend="memory")

    staged = client.post(
        "/v1/memory/candidates",
        json={
            "category": "stakeholder_pref",
            "summary": "CEO prefers concise updates",
            "fact_json": {"tone": "concise"},
            "source_session_id": "session-1",
            "source_event_id": "event-1",
            "source_step_id": "step-1",
            "confidence": 0.72,
            "sensitivity": "internal",
        },
    )
    assert staged.status_code == 200
    candidate_id = staged.json()["candidate_id"]
    assert staged.json()["principal_id"] == "exec-1"
    assert staged.json()["status"] == "pending"

    listed_candidates = client.get("/v1/memory/candidates", params={"limit": 10, "status": "pending"})
    assert listed_candidates.status_code == 200
    assert any(row["candidate_id"] == candidate_id for row in listed_candidates.json())

    promoted = client.post(
        f"/v1/memory/candidates/{candidate_id}/promote",
        json={"reviewer": "operator-1", "sharing_policy": "private"},
    )
    assert promoted.status_code == 200
    promoted_body = promoted.json()
    assert promoted_body["candidate"]["status"] == "promoted"
    item_id = promoted_body["item"]["item_id"]
    assert promoted_body["item"]["provenance_json"]["candidate_id"] == candidate_id

    listed_items = client.get("/v1/memory/items", params={"limit": 10})
    assert listed_items.status_code == 200
    assert any(row["item_id"] == item_id for row in listed_items.json())

    fetched_item = client.get(f"/v1/memory/items/{item_id}")
    assert fetched_item.status_code == 200
    assert fetched_item.json()["item_id"] == item_id

    mismatch = client.get("/v1/memory/items", params={"limit": 10, "principal_id": "exec-2"})
    assert mismatch.status_code == 403
    assert mismatch.json()["error"]["code"] == "principal_scope_mismatch"


def test_memory_entities_relationships_flow() -> None:
    client = _client(storage_backend="memory")

    executive = client.post(
        "/v1/memory/entities",
        json={
            "principal_id": "exec-1",
            "entity_type": "person",
            "canonical_name": "Alex Executive",
            "attributes_json": {"role": "executive"},
            "confidence": 0.9,
            "status": "active",
        },
    )
    assert executive.status_code == 200
    executive_id = executive.json()["entity_id"]

    stakeholder = client.post(
        "/v1/memory/entities",
        json={
            "principal_id": "exec-1",
            "entity_type": "person",
            "canonical_name": "Sam Stakeholder",
            "attributes_json": {"role": "board_member"},
            "confidence": 0.88,
            "status": "active",
        },
    )
    assert stakeholder.status_code == 200
    stakeholder_id = stakeholder.json()["entity_id"]

    relationship = client.post(
        "/v1/memory/relationships",
        json={
            "principal_id": "exec-1",
            "from_entity_id": executive_id,
            "to_entity_id": stakeholder_id,
            "relationship_type": "reports_to",
            "attributes_json": {"strength": "high"},
            "confidence": 0.75,
        },
    )
    assert relationship.status_code == 200
    relationship_id = relationship.json()["relationship_id"]

    listed_entities = client.get("/v1/memory/entities", params={"limit": 10, "principal_id": "exec-1"})
    assert listed_entities.status_code == 200
    assert any(row["entity_id"] == executive_id for row in listed_entities.json())

    fetched_entity = client.get(f"/v1/memory/entities/{executive_id}")
    assert fetched_entity.status_code == 200
    assert fetched_entity.json()["canonical_name"] == "Alex Executive"

    listed_relationships = client.get("/v1/memory/relationships", params={"limit": 10, "principal_id": "exec-1"})
    assert listed_relationships.status_code == 200
    assert any(row["relationship_id"] == relationship_id for row in listed_relationships.json())

    fetched_relationship = client.get(f"/v1/memory/relationships/{relationship_id}")
    assert fetched_relationship.status_code == 200
    assert fetched_relationship.json()["relationship_type"] == "reports_to"


def test_memory_commitments_principal_scope_flow() -> None:
    client = _client(storage_backend="memory")

    created = client.post(
        "/v1/memory/commitments",
        json={
            "principal_id": "exec-1",
            "title": "Send board follow-up",
            "details": "Draft and send by Friday",
            "status": "open",
            "priority": "high",
            "due_at": "2026-03-06T10:00:00+00:00",
            "source_json": {"source": "manual"},
        },
    )
    assert created.status_code == 200
    commitment_id = created.json()["commitment_id"]

    listed = client.get("/v1/memory/commitments", params={"principal_id": "exec-1", "limit": 10})
    assert listed.status_code == 200
    assert any(row["commitment_id"] == commitment_id for row in listed.json())

    fetched = client.get(f"/v1/memory/commitments/{commitment_id}", params={"principal_id": "exec-1"})
    assert fetched.status_code == 200
    assert fetched.json()["title"] == "Send board follow-up"

    wrong_scope = client.get(f"/v1/memory/commitments/{commitment_id}", params={"principal_id": "exec-2"})
    assert wrong_scope.status_code == 403
    assert wrong_scope.json()["error"]["code"] == "principal_scope_mismatch"


def test_memory_authority_bindings_principal_scope_flow() -> None:
    client = _client(storage_backend="memory")

    created = client.post(
        "/v1/memory/authority-bindings",
        json={
            "principal_id": "exec-1",
            "subject_ref": "assistant",
            "action_scope": "calendar.write",
            "approval_level": "manager",
            "channel_scope": ["email", "slack"],
            "policy_json": {"quiet_hours_enforced": True},
            "status": "active",
        },
    )
    assert created.status_code == 200
    binding_id = created.json()["binding_id"]

    listed = client.get("/v1/memory/authority-bindings", params={"principal_id": "exec-1", "limit": 10})
    assert listed.status_code == 200
    assert any(row["binding_id"] == binding_id for row in listed.json())

    fetched = client.get(f"/v1/memory/authority-bindings/{binding_id}", params={"principal_id": "exec-1"})
    assert fetched.status_code == 200
    assert fetched.json()["action_scope"] == "calendar.write"

    wrong_scope = client.get(f"/v1/memory/authority-bindings/{binding_id}", params={"principal_id": "exec-2"})
    assert wrong_scope.status_code == 403
    assert wrong_scope.json()["error"]["code"] == "principal_scope_mismatch"


def test_memory_delivery_preferences_principal_scope_flow() -> None:
    client = _client(storage_backend="memory")

    created = client.post(
        "/v1/memory/delivery-preferences",
        json={
            "principal_id": "exec-1",
            "channel": "email",
            "recipient_ref": "ceo@example.com",
            "cadence": "urgent_only",
            "quiet_hours_json": {"start": "22:00", "end": "07:00"},
            "format_json": {"style": "concise"},
            "status": "active",
        },
    )
    assert created.status_code == 200
    preference_id = created.json()["preference_id"]

    listed = client.get("/v1/memory/delivery-preferences", params={"principal_id": "exec-1", "limit": 10})
    assert listed.status_code == 200
    assert any(row["preference_id"] == preference_id for row in listed.json())

    fetched = client.get(f"/v1/memory/delivery-preferences/{preference_id}", params={"principal_id": "exec-1"})
    assert fetched.status_code == 200
    assert fetched.json()["channel"] == "email"

    wrong_scope = client.get(f"/v1/memory/delivery-preferences/{preference_id}", params={"principal_id": "exec-2"})
    assert wrong_scope.status_code == 403
    assert wrong_scope.json()["error"]["code"] == "principal_scope_mismatch"


def test_memory_follow_ups_principal_scope_flow() -> None:
    client = _client(storage_backend="memory")

    created = client.post(
        "/v1/memory/follow-ups",
        json={
            "principal_id": "exec-1",
            "stakeholder_ref": "ceo@example.com",
            "topic": "Board follow-up",
            "status": "open",
            "due_at": "2026-03-07T09:00:00+00:00",
            "channel_hint": "email",
            "notes": "Send summary after prep call",
            "source_json": {"source": "manual"},
        },
    )
    assert created.status_code == 200
    follow_up_id = created.json()["follow_up_id"]

    listed = client.get("/v1/memory/follow-ups", params={"principal_id": "exec-1", "limit": 10})
    assert listed.status_code == 200
    assert any(row["follow_up_id"] == follow_up_id for row in listed.json())

    fetched = client.get(f"/v1/memory/follow-ups/{follow_up_id}", params={"principal_id": "exec-1"})
    assert fetched.status_code == 200
    assert fetched.json()["topic"] == "Board follow-up"

    wrong_scope = client.get(f"/v1/memory/follow-ups/{follow_up_id}", params={"principal_id": "exec-2"})
    assert wrong_scope.status_code == 403
    assert wrong_scope.json()["error"]["code"] == "principal_scope_mismatch"
