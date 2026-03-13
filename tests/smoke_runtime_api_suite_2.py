from __future__ import annotations

from tests.smoke_runtime_api_support import build_client as _client
from tests.smoke_runtime_api_support import build_headers as _headers


def test_human_task_priority_summary_for_matching_operator_profile() -> None:
    client = _client(storage_backend="memory")
    create = client.post("/v1/rewrite/artifact", json={"text": "operator-matched priority summary seed"})
    assert create.status_code == 200
    session_id = create.json()["execution_session_id"]

    session = client.get(f"/v1/rewrite/sessions/{session_id}")
    assert session.status_code == 200
    step_id = session.json()["steps"][-1]["step_id"]

    specialist = client.post(
        "/v1/human/tasks/operators",
        json={
            "operator_id": "operator-specialist-summary",
            "display_name": "Senior Comms Reviewer",
            "roles": ["communications_reviewer"],
            "skill_tags": ["tone", "accuracy", "stakeholder_sensitivity"],
            "trust_tier": "senior",
            "status": "active",
        },
    )
    assert specialist.status_code == 200
    junior = client.post(
        "/v1/human/tasks/operators",
        json={
            "operator_id": "operator-junior-summary",
            "display_name": "Junior Reviewer",
            "roles": ["communications_reviewer"],
            "skill_tags": ["tone"],
            "trust_tier": "standard",
            "status": "active",
        },
    )
    assert junior.status_code == 200
    scheduler = client.post(
        "/v1/human/tasks/operators",
        json={
            "operator_id": "operator-scheduler-summary",
            "display_name": "Scheduler",
            "roles": ["schedule_coordinator"],
            "skill_tags": ["calendar"],
            "trust_tier": "standard",
            "status": "active",
        },
    )
    assert scheduler.status_code == 200

    for priority in ("urgent", "high"):
        response = client.post(
            "/v1/human/tasks",
            json={
                "session_id": session_id,
                "step_id": step_id,
                "task_type": "communications_review",
                "role_required": "communications_reviewer",
                "brief": f"{priority.title()} specialist-only task.",
                "authority_required": "send_on_behalf_review",
                "quality_rubric_json": {
                    "checks": ["tone", "accuracy", "stakeholder_sensitivity"],
                },
                "priority": priority,
                "resume_session_on_return": False,
            },
        )
        assert response.status_code == 200

    scheduler_task = client.post(
        "/v1/human/tasks",
        json={
            "session_id": session_id,
            "step_id": step_id,
            "task_type": "schedule_review",
            "role_required": "schedule_coordinator",
            "brief": "Normal scheduling task.",
            "priority": "normal",
            "resume_session_on_return": False,
        },
    )
    assert scheduler_task.status_code == 200

    specialist_summary = client.get(
        "/v1/human/tasks/priority-summary",
        params={
            "status": "pending",
            "assignment_state": "unassigned",
            "operator_id": "operator-specialist-summary",
        },
    )
    assert specialist_summary.status_code == 200
    specialist_body = specialist_summary.json()
    assert specialist_body["operator_id"] == "operator-specialist-summary"
    assert specialist_body["total"] == 2
    assert specialist_body["highest_priority"] == "urgent"
    assert specialist_body["counts_json"]["urgent"] == 1
    assert specialist_body["counts_json"]["high"] == 1
    assert specialist_body["counts_json"]["normal"] == 0

    junior_summary = client.get(
        "/v1/human/tasks/priority-summary",
        params={
            "status": "pending",
            "assignment_state": "unassigned",
            "operator_id": "operator-junior-summary",
        },
    )
    assert junior_summary.status_code == 200
    junior_body = junior_summary.json()
    assert junior_body["operator_id"] == "operator-junior-summary"
    assert junior_body["total"] == 0
    assert junior_body["highest_priority"] == ""
    assert junior_body["counts_json"]["urgent"] == 0
    assert junior_body["counts_json"]["high"] == 0
    assert junior_body["counts_json"]["normal"] == 0

    scheduler_summary = client.get(
        "/v1/human/tasks/priority-summary",
        params={
            "status": "pending",
            "assignment_state": "unassigned",
            "operator_id": "operator-scheduler-summary",
        },
    )
    assert scheduler_summary.status_code == 200
    scheduler_body = scheduler_summary.json()
    assert scheduler_body["operator_id"] == "operator-scheduler-summary"
    assert scheduler_body["total"] == 1
    assert scheduler_body["highest_priority"] == "normal"
    assert scheduler_body["counts_json"]["urgent"] == 0
    assert scheduler_body["counts_json"]["high"] == 0
    assert scheduler_body["counts_json"]["normal"] == 1


def test_human_task_priority_summary_for_assignment_source() -> None:
    client = _client(storage_backend="memory")

    contract = client.post(
        "/v1/task-contracts",
        json={
            "task_type": "rewrite_text",
            "description": "Rewrite text with human review and auto-preselection.",
            "deliverable_type": "rewrite_note",
            "default_approval_class": "none",
            "allowed_tools": ["artifact_repository"],
            "evidence_requirements": ["stakeholder_context"],
            "memory_write_policy": "reviewed_only",
            "budget_policy_json": {
                "class": "low",
                "human_review_role": "source_filter_reviewer",
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
                    "checks": ["tone", "accuracy", "stakeholder_sensitivity"],
                },
            },
        },
    )
    assert contract.status_code == 200

    operator_profile = client.post(
        "/v1/human/tasks/operators",
        json={
            "operator_id": "operator-auto-summary",
            "display_name": "Senior Comms Reviewer",
            "roles": ["source_filter_reviewer"],
            "skill_tags": ["tone", "accuracy", "stakeholder_sensitivity"],
            "trust_tier": "senior",
            "status": "active",
        },
    )
    assert operator_profile.status_code == 200

    create = client.post("/v1/rewrite/artifact", json={"text": "rewrite with pending auto-preselected review"})
    assert create.status_code == 202
    auto_task_id = create.json()["human_task_id"]
    session_id = create.json()["session_id"]

    session = client.get(f"/v1/rewrite/sessions/{session_id}")
    assert session.status_code == 200
    step_id = session.json()["steps"][-1]["step_id"]

    manual_task = client.post(
        "/v1/human/tasks",
        json={
            "session_id": session_id,
            "step_id": step_id,
            "task_type": "communications_review",
            "role_required": "manual_source_filter_reviewer",
            "brief": "Manual assigned task.",
            "priority": "normal",
            "resume_session_on_return": False,
        },
    )
    assert manual_task.status_code == 200
    manual_task_id = manual_task.json()["human_task_id"]
    assign_manual = client.post(
        f"/v1/human/tasks/{manual_task_id}/assign",
        json={"operator_id": "operator-manual-summary"},
    )
    assert assign_manual.status_code == 200

    ownerless_task = client.post(
        "/v1/human/tasks",
        json={
            "session_id": session_id,
            "step_id": step_id,
            "task_type": "communications_review",
            "role_required": "manual_source_filter_reviewer",
            "brief": "Ownerless pending task.",
            "priority": "low",
            "resume_session_on_return": False,
        },
    )
    assert ownerless_task.status_code == 200
    ownerless_task_id = ownerless_task.json()["human_task_id"]

    ownerless_summary = client.get(
        "/v1/human/tasks/priority-summary",
        params={"status": "pending", "assignment_state": "unassigned", "assignment_source": "none"},
    )
    assert ownerless_summary.status_code == 200
    ownerless_body = ownerless_summary.json()
    assert ownerless_body["assignment_source"] == "none"
    assert ownerless_body["total"] == 1
    assert ownerless_body["highest_priority"] == "low"
    assert ownerless_body["counts_json"]["urgent"] == 0
    assert ownerless_body["counts_json"]["high"] == 0
    assert ownerless_body["counts_json"]["normal"] == 0
    assert ownerless_body["counts_json"]["low"] == 1

    ownerless_list = client.get(
        "/v1/human/tasks",
        params={"status": "pending", "assignment_state": "unassigned", "assignment_source": "none"},
    )
    assert ownerless_list.status_code == 200
    ownerless_ids = {row["human_task_id"] for row in ownerless_list.json()}
    assert ownerless_task_id in ownerless_ids
    assert manual_task_id not in ownerless_ids
    assert auto_task_id not in ownerless_ids

    ownerless_unassigned = client.get(
        "/v1/human/tasks/unassigned",
        params={"assignment_source": "none"},
    )
    assert ownerless_unassigned.status_code == 200
    ownerless_unassigned_ids = {row["human_task_id"] for row in ownerless_unassigned.json()}
    assert ownerless_task_id in ownerless_unassigned_ids
    assert manual_task_id not in ownerless_unassigned_ids
    assert auto_task_id not in ownerless_unassigned_ids

    ownerless_backlog = client.get(
        "/v1/human/tasks/backlog",
        params={"assignment_state": "unassigned", "assignment_source": "none"},
    )
    assert ownerless_backlog.status_code == 200
    ownerless_backlog_ids = {row["human_task_id"] for row in ownerless_backlog.json()}
    assert ownerless_task_id in ownerless_backlog_ids
    assert manual_task_id not in ownerless_backlog_ids
    assert auto_task_id not in ownerless_backlog_ids

    ownerless_session = client.get(
        f"/v1/rewrite/sessions/{session_id}",
        params={"human_task_assignment_source": "none"},
    )
    assert ownerless_session.status_code == 200
    ownerless_session_body = ownerless_session.json()
    assert len(ownerless_session_body["human_tasks"]) == 1
    assert ownerless_session_body["human_tasks"][0]["human_task_id"] == ownerless_task_id
    assert all(row["assignment_source"] == "" for row in ownerless_session_body["human_task_assignment_history"])
    assert all(row["event_name"] == "human_task_created" for row in ownerless_session_body["human_task_assignment_history"])
    assert any(
        row["human_task_id"] == ownerless_task_id for row in ownerless_session_body["human_task_assignment_history"]
    )

    ownerless_newer_task = client.post(
        "/v1/human/tasks",
        json={
            "session_id": session_id,
            "step_id": step_id,
            "task_type": "communications_review",
            "role_required": "manual_source_filter_reviewer",
            "brief": "Newer ownerless pending task.",
            "priority": "low",
            "resume_session_on_return": False,
        },
    )
    assert ownerless_newer_task.status_code == 200
    ownerless_newer_task_id = ownerless_newer_task.json()["human_task_id"]

    ownerless_summary_after_churn = client.get(
        "/v1/human/tasks/priority-summary",
        params={"status": "pending", "assignment_state": "unassigned", "assignment_source": "none"},
    )
    assert ownerless_summary_after_churn.status_code == 200
    ownerless_summary_after_churn_body = ownerless_summary_after_churn.json()
    assert ownerless_summary_after_churn_body["assignment_source"] == "none"
    assert ownerless_summary_after_churn_body["total"] == 2
    assert ownerless_summary_after_churn_body["highest_priority"] == "low"
    assert ownerless_summary_after_churn_body["counts_json"]["urgent"] == 0
    assert ownerless_summary_after_churn_body["counts_json"]["high"] == 0
    assert ownerless_summary_after_churn_body["counts_json"]["normal"] == 0
    assert ownerless_summary_after_churn_body["counts_json"]["low"] == 2

    ownerless_list_after_churn = client.get(
        "/v1/human/tasks",
        params={"status": "pending", "assignment_state": "unassigned", "assignment_source": "none"},
    )
    assert ownerless_list_after_churn.status_code == 200
    ownerless_list_after_churn_ids = {row["human_task_id"] for row in ownerless_list_after_churn.json()}
    assert ownerless_list_after_churn_ids == {ownerless_task_id, ownerless_newer_task_id}

    ownerless_unassigned_after_churn = client.get(
        "/v1/human/tasks/unassigned",
        params={"assignment_source": "none"},
    )
    assert ownerless_unassigned_after_churn.status_code == 200
    ownerless_unassigned_after_churn_ids = {
        row["human_task_id"] for row in ownerless_unassigned_after_churn.json()
    }
    assert ownerless_unassigned_after_churn_ids == {ownerless_task_id, ownerless_newer_task_id}

    ownerless_backlog_after_churn = client.get(
        "/v1/human/tasks/backlog",
        params={"assignment_state": "unassigned", "assignment_source": "none"},
    )
    assert ownerless_backlog_after_churn.status_code == 200
    ownerless_backlog_after_churn_ids = {row["human_task_id"] for row in ownerless_backlog_after_churn.json()}
    assert ownerless_backlog_after_churn_ids == {ownerless_task_id, ownerless_newer_task_id}

    ownerless_session_list_after_churn = client.get(
        "/v1/human/tasks",
        params={"session_id": session_id, "assignment_source": "none"},
    )
    assert ownerless_session_list_after_churn.status_code == 200
    ownerless_session_list_after_churn_ids = {
        row["human_task_id"] for row in ownerless_session_list_after_churn.json()
    }
    assert ownerless_session_list_after_churn_ids == {ownerless_task_id, ownerless_newer_task_id}

    ownerless_backlog_created = client.get(
        "/v1/human/tasks/backlog",
        params={
            "assignment_state": "unassigned",
            "assignment_source": "none",
            "sort": "created_asc",
        },
    )
    assert ownerless_backlog_created.status_code == 200
    ownerless_backlog_created_all_ids = [row["human_task_id"] for row in ownerless_backlog_created.json()]
    assert ownerless_backlog_created_all_ids == [ownerless_task_id, ownerless_newer_task_id]
    ownerless_backlog_created_ids = [
        row["human_task_id"]
        for row in ownerless_backlog_created.json()
        if row["human_task_id"] in {ownerless_task_id, ownerless_newer_task_id}
    ]
    assert ownerless_backlog_created_ids == [ownerless_task_id, ownerless_newer_task_id]

    ownerless_backlog_transition = client.get(
        "/v1/human/tasks/backlog",
        params={
            "assignment_state": "unassigned",
            "assignment_source": "none",
            "sort": "last_transition_desc",
        },
    )
    assert ownerless_backlog_transition.status_code == 200
    ownerless_backlog_transition_all_ids = [row["human_task_id"] for row in ownerless_backlog_transition.json()]
    assert ownerless_backlog_transition_all_ids == [ownerless_newer_task_id, ownerless_task_id]
    ownerless_backlog_transition_ids = [
        row["human_task_id"]
        for row in ownerless_backlog_transition.json()
        if row["human_task_id"] in {ownerless_task_id, ownerless_newer_task_id}
    ]
    assert ownerless_backlog_transition_ids == [ownerless_newer_task_id, ownerless_task_id]

    ownerless_unassigned_transition = client.get(
        "/v1/human/tasks/unassigned",
        params={"assignment_source": "none", "sort": "last_transition_desc"},
    )
    assert ownerless_unassigned_transition.status_code == 200
    ownerless_unassigned_transition_all_ids = [row["human_task_id"] for row in ownerless_unassigned_transition.json()]
    assert ownerless_unassigned_transition_all_ids == [ownerless_newer_task_id, ownerless_task_id]
    ownerless_unassigned_transition_ids = [
        row["human_task_id"]
        for row in ownerless_unassigned_transition.json()
        if row["human_task_id"] in {ownerless_task_id, ownerless_newer_task_id}
    ]
    assert ownerless_unassigned_transition_ids == [ownerless_newer_task_id, ownerless_task_id]

    ownerless_unassigned_created = client.get(
        "/v1/human/tasks/unassigned",
        params={"assignment_source": "none", "sort": "created_asc"},
    )
    assert ownerless_unassigned_created.status_code == 200
    ownerless_unassigned_created_all_ids = [row["human_task_id"] for row in ownerless_unassigned_created.json()]
    assert ownerless_unassigned_created_all_ids == [ownerless_task_id, ownerless_newer_task_id]
    ownerless_unassigned_created_ids = [
        row["human_task_id"]
        for row in ownerless_unassigned_created.json()
        if row["human_task_id"] in {ownerless_task_id, ownerless_newer_task_id}
    ]
    assert ownerless_unassigned_created_ids == [ownerless_task_id, ownerless_newer_task_id]

    ownerless_list_created = client.get(
        "/v1/human/tasks",
        params={
            "status": "pending",
            "assignment_state": "unassigned",
            "assignment_source": "none",
            "sort": "created_asc",
        },
    )
    assert ownerless_list_created.status_code == 200
    ownerless_list_created_all_ids = [row["human_task_id"] for row in ownerless_list_created.json()]
    assert ownerless_list_created_all_ids == [ownerless_task_id, ownerless_newer_task_id]
    ownerless_list_created_ids = [
        row["human_task_id"]
        for row in ownerless_list_created.json()
        if row["human_task_id"] in {ownerless_task_id, ownerless_newer_task_id}
    ]
    assert ownerless_list_created_ids == [ownerless_task_id, ownerless_newer_task_id]

    ownerless_list_transition = client.get(
        "/v1/human/tasks",
        params={
            "status": "pending",
            "assignment_state": "unassigned",
            "assignment_source": "none",
            "sort": "last_transition_desc",
        },
    )
    assert ownerless_list_transition.status_code == 200
    ownerless_list_transition_all_ids = [row["human_task_id"] for row in ownerless_list_transition.json()]
    assert ownerless_list_transition_all_ids == [ownerless_newer_task_id, ownerless_task_id]
    ownerless_list_transition_ids = [
        row["human_task_id"]
        for row in ownerless_list_transition.json()
        if row["human_task_id"] in {ownerless_task_id, ownerless_newer_task_id}
    ]
    assert ownerless_list_transition_ids == [ownerless_newer_task_id, ownerless_task_id]

    ownerless_session_created = client.get(
        "/v1/human/tasks",
        params={"session_id": session_id, "assignment_source": "none", "sort": "created_asc"},
    )
    assert ownerless_session_created.status_code == 200
    ownerless_session_created_all_ids = [row["human_task_id"] for row in ownerless_session_created.json()]
    assert ownerless_session_created_all_ids == [ownerless_task_id, ownerless_newer_task_id]
    ownerless_session_created_ids = [
        row["human_task_id"]
        for row in ownerless_session_created.json()
        if row["human_task_id"] in {ownerless_task_id, ownerless_newer_task_id}
    ]
    assert ownerless_session_created_ids == [ownerless_task_id, ownerless_newer_task_id]

    ownerless_session_transition = client.get(
        "/v1/human/tasks",
        params={"session_id": session_id, "assignment_source": "none", "sort": "last_transition_desc"},
    )
    assert ownerless_session_transition.status_code == 200
    ownerless_session_transition_all_ids = [row["human_task_id"] for row in ownerless_session_transition.json()]
    assert ownerless_session_transition_all_ids == [ownerless_newer_task_id, ownerless_task_id]
    ownerless_session_transition_ids = [
        row["human_task_id"]
        for row in ownerless_session_transition.json()
        if row["human_task_id"] in {ownerless_task_id, ownerless_newer_task_id}
    ]
    assert ownerless_session_transition_ids == [ownerless_newer_task_id, ownerless_task_id]

    ownerless_session_projection = client.get(
        f"/v1/rewrite/sessions/{session_id}",
        params={"human_task_assignment_source": "none"},
    )
    assert ownerless_session_projection.status_code == 200
    ownerless_session_projection_body = ownerless_session_projection.json()
    assert len(ownerless_session_projection_body["human_tasks"]) == 2
    assert len(ownerless_session_projection_body["human_task_assignment_history"]) > len(
        ownerless_session_projection_body["human_tasks"]
    )
    ownerless_session_projection_ids = [
        row["human_task_id"]
        for row in ownerless_session_projection_body["human_tasks"]
        if row["human_task_id"] in {ownerless_task_id, ownerless_newer_task_id}
    ]
    assert ownerless_session_projection_ids == [ownerless_task_id, ownerless_newer_task_id]
    ownerless_session_history_ids = [
        row["human_task_id"]
        for row in ownerless_session_projection_body["human_task_assignment_history"]
        if row["human_task_id"] in {ownerless_task_id, ownerless_newer_task_id}
    ]
    assert ownerless_session_history_ids == [ownerless_task_id, ownerless_newer_task_id]
    assert all(
        row["human_task_id"] not in {manual_task_id, auto_task_id}
        for row in ownerless_session_projection_body["human_tasks"]
    )
    ownerless_session_projection_history_all_ids = [
        row["human_task_id"] for row in ownerless_session_projection_body["human_task_assignment_history"]
    ]
    assert ownerless_session_projection_history_all_ids[:4] == [
        auto_task_id,
        manual_task_id,
        ownerless_task_id,
        ownerless_newer_task_id,
    ]

    auto_summary = client.get(
        "/v1/human/tasks/priority-summary",
        params={"status": "pending", "assignment_source": "auto_preselected"},
    )
    assert auto_summary.status_code == 200
    auto_body = auto_summary.json()
    assert auto_body["assignment_source"] == "auto_preselected"
    assert auto_body["total"] == 1
    assert auto_body["highest_priority"] == "high"
    assert auto_body["counts_json"]["urgent"] == 0
    assert auto_body["counts_json"]["high"] == 1
    assert auto_body["counts_json"]["normal"] == 0

    manual_summary = client.get(
        "/v1/human/tasks/priority-summary",
        params={"status": "pending", "assignment_source": "manual"},
    )
    assert manual_summary.status_code == 200
    manual_body = manual_summary.json()
    assert manual_body["assignment_source"] == "manual"
    assert manual_body["total"] == 1
    assert manual_body["highest_priority"] == "normal"
    assert manual_body["counts_json"]["urgent"] == 0
    assert manual_body["counts_json"]["high"] == 0
    assert manual_body["counts_json"]["normal"] == 1

    manual_list = client.get(
        "/v1/human/tasks",
        params={"status": "pending", "assignment_source": "manual"},
    )
    assert manual_list.status_code == 200
    manual_ids = {row["human_task_id"] for row in manual_list.json()}
    assert manual_task_id in manual_ids
    assert auto_task_id not in manual_ids

    manual_mine = client.get(
        "/v1/human/tasks/mine",
        params={"operator_id": "operator-manual-summary", "assignment_source": "manual"},
    )
    assert manual_mine.status_code == 200
    manual_mine_ids = {row["human_task_id"] for row in manual_mine.json()}
    assert manual_task_id in manual_mine_ids

    manual_session_list = client.get(
        "/v1/human/tasks",
        params={"session_id": session_id, "assignment_source": "manual"},
    )
    assert manual_session_list.status_code == 200
    manual_session_ids = {row["human_task_id"] for row in manual_session_list.json()}
    assert manual_task_id in manual_session_ids
    assert auto_task_id not in manual_session_ids

    auto_backlog = client.get(
        "/v1/human/tasks/backlog",
        params={"operator_id": "operator-auto-summary", "assignment_source": "auto_preselected"},
    )
    assert auto_backlog.status_code == 200
    auto_backlog_ids = {row["human_task_id"] for row in auto_backlog.json()}
    assert auto_task_id in auto_backlog_ids
    assert manual_task_id not in auto_backlog_ids

    auto_session_list = client.get(
        "/v1/human/tasks",
        params={"session_id": session_id, "assignment_source": "auto_preselected"},
    )
    assert auto_session_list.status_code == 200
    auto_session_ids = {row["human_task_id"] for row in auto_session_list.json()}
    assert auto_task_id in auto_session_ids
    assert manual_task_id not in auto_session_ids

    session_after = client.get(f"/v1/rewrite/sessions/{session_id}")
    assert session_after.status_code == 200
    auto_task = next(row for row in session_after.json()["human_tasks"] if row["human_task_id"] == auto_task_id)
    assert auto_task["assignment_source"] == "auto_preselected"


def test_human_task_sort_by_sla_due_at_asc() -> None:
    client = _client(storage_backend="memory")
    create = client.post("/v1/rewrite/artifact", json={"text": "sla sort seed"})
    assert create.status_code == 200
    session_id = create.json()["execution_session_id"]

    session = client.get(f"/v1/rewrite/sessions/{session_id}")
    assert session.status_code == 200
    step_id = session.json()["steps"][-1]["step_id"]

    later_due = client.post(
        "/v1/human/tasks",
        json={
            "session_id": session_id,
            "step_id": step_id,
            "task_type": "communications_review",
            "role_required": "communications_reviewer",
            "brief": "Later due task.",
            "sla_due_at": "2100-01-02T00:00:00+00:00",
            "resume_session_on_return": False,
        },
    )
    assert later_due.status_code == 200
    later_due_task_id = later_due.json()["human_task_id"]

    sooner_due = client.post(
        "/v1/human/tasks",
        json={
            "session_id": session_id,
            "step_id": step_id,
            "task_type": "communications_review",
            "role_required": "communications_reviewer",
            "brief": "Sooner due task.",
            "sla_due_at": "2100-01-01T00:00:00+00:00",
            "resume_session_on_return": False,
        },
    )
    assert sooner_due.status_code == 200
    sooner_due_task_id = sooner_due.json()["human_task_id"]

    listed = client.get(
        "/v1/human/tasks",
        params={"status": "pending", "sort": "sla_due_at_asc", "limit": 10},
    )
    assert listed.status_code == 200
    listed_rows = [row for row in listed.json() if row["human_task_id"] in {later_due_task_id, sooner_due_task_id}]
    assert [row["human_task_id"] for row in listed_rows[:2]] == [sooner_due_task_id, later_due_task_id]

    backlog = client.get(
        "/v1/human/tasks/backlog",
        params={"sort": "sla_due_at_asc", "limit": 10},
    )
    assert backlog.status_code == 200
    backlog_rows = [row for row in backlog.json() if row["human_task_id"] in {later_due_task_id, sooner_due_task_id}]
    assert [row["human_task_id"] for row in backlog_rows[:2]] == [sooner_due_task_id, later_due_task_id]


def test_human_task_sort_by_sla_then_last_transition() -> None:
    client = _client(storage_backend="memory")
    create = client.post("/v1/rewrite/artifact", json={"text": "combined sort seed"})
    assert create.status_code == 200
    session_id = create.json()["execution_session_id"]

    session = client.get(f"/v1/rewrite/sessions/{session_id}")
    assert session.status_code == 200
    step_id = session.json()["steps"][-1]["step_id"]

    early_stale = client.post(
        "/v1/human/tasks",
        json={
            "session_id": session_id,
            "step_id": step_id,
            "task_type": "communications_review",
            "role_required": "communications_reviewer",
            "brief": "Earlier due stale task.",
            "sla_due_at": "2100-01-01T00:00:00+00:00",
            "resume_session_on_return": False,
        },
    )
    assert early_stale.status_code == 200
    early_stale_id = early_stale.json()["human_task_id"]

    early_recent = client.post(
        "/v1/human/tasks",
        json={
            "session_id": session_id,
            "step_id": step_id,
            "task_type": "communications_review",
            "role_required": "communications_reviewer",
            "brief": "Earlier due recently touched task.",
            "sla_due_at": "2100-01-01T00:00:00+00:00",
            "resume_session_on_return": False,
        },
    )
    assert early_recent.status_code == 200
    early_recent_id = early_recent.json()["human_task_id"]

    later_due = client.post(
        "/v1/human/tasks",
        json={
            "session_id": session_id,
            "step_id": step_id,
            "task_type": "communications_review",
            "role_required": "communications_reviewer",
            "brief": "Later due task.",
            "sla_due_at": "2100-01-02T00:00:00+00:00",
            "resume_session_on_return": False,
        },
    )
    assert later_due.status_code == 200
    later_due_id = later_due.json()["human_task_id"]

    assigned = client.post(f"/v1/human/tasks/{early_recent_id}/assign", json={"operator_id": "operator-sorter"})
    assert assigned.status_code == 200
    assert assigned.json()["last_transition_event_name"] == "human_task_assigned"

    listed = client.get(
        "/v1/human/tasks",
        params={"status": "pending", "sort": "sla_due_at_asc_last_transition_desc", "limit": 10},
    )
    assert listed.status_code == 200
    listed_rows = [
        row for row in listed.json() if row["human_task_id"] in {early_stale_id, early_recent_id, later_due_id}
    ]
    assert [row["human_task_id"] for row in listed_rows[:3]] == [early_recent_id, early_stale_id, later_due_id]

    backlog = client.get(
        "/v1/human/tasks/backlog",
        params={"sort": "sla_due_at_asc_last_transition_desc", "limit": 10},
    )
    assert backlog.status_code == 200
    backlog_rows = [
        row for row in backlog.json() if row["human_task_id"] in {early_stale_id, early_recent_id, later_due_id}
    ]
    assert [row["human_task_id"] for row in backlog_rows[:3]] == [early_recent_id, early_stale_id, later_due_id]


def test_human_task_unscheduled_fallback_sorting_for_sla_modes() -> None:
    client = _client(storage_backend="memory")
    create = client.post("/v1/rewrite/artifact", json={"text": "unscheduled fallback seed"})
    assert create.status_code == 200
    session_id = create.json()["execution_session_id"]

    session = client.get(f"/v1/rewrite/sessions/{session_id}")
    assert session.status_code == 200
    step_id = session.json()["steps"][-1]["step_id"]

    due_task = client.post(
        "/v1/human/tasks",
        json={
            "session_id": session_id,
            "step_id": step_id,
            "task_type": "communications_review",
            "role_required": "communications_reviewer",
            "brief": "Scheduled task.",
            "sla_due_at": "2100-01-01T00:00:00+00:00",
            "resume_session_on_return": False,
        },
    )
    assert due_task.status_code == 200
    due_task_id = due_task.json()["human_task_id"]

    older_unscheduled = client.post(
        "/v1/human/tasks",
        json={
            "session_id": session_id,
            "step_id": step_id,
            "task_type": "communications_review",
            "role_required": "communications_reviewer",
            "brief": "Older unscheduled task.",
            "resume_session_on_return": False,
        },
    )
    assert older_unscheduled.status_code == 200
    older_unscheduled_id = older_unscheduled.json()["human_task_id"]

    newer_unscheduled = client.post(
        "/v1/human/tasks",
        json={
            "session_id": session_id,
            "step_id": step_id,
            "task_type": "communications_review",
            "role_required": "communications_reviewer",
            "brief": "Newer unscheduled task.",
            "resume_session_on_return": False,
        },
    )
    assert newer_unscheduled.status_code == 200
    newer_unscheduled_id = newer_unscheduled.json()["human_task_id"]

    assigned = client.post(f"/v1/human/tasks/{newer_unscheduled_id}/assign", json={"operator_id": "operator-sorter"})
    assert assigned.status_code == 200
    assert assigned.json()["last_transition_event_name"] == "human_task_assigned"

    sla_list = client.get(
        "/v1/human/tasks",
        params={"status": "pending", "sort": "sla_due_at_asc", "limit": 10},
    )
    assert sla_list.status_code == 200
    sla_list_rows = [
        row for row in sla_list.json() if row["human_task_id"] in {due_task_id, older_unscheduled_id, newer_unscheduled_id}
    ]
    assert [row["human_task_id"] for row in sla_list_rows[:3]] == [due_task_id, older_unscheduled_id, newer_unscheduled_id]

    combined_list = client.get(
        "/v1/human/tasks",
        params={"status": "pending", "sort": "sla_due_at_asc_last_transition_desc", "limit": 10},
    )
    assert combined_list.status_code == 200
    combined_list_rows = [
        row
        for row in combined_list.json()
        if row["human_task_id"] in {due_task_id, older_unscheduled_id, newer_unscheduled_id}
    ]
    assert [row["human_task_id"] for row in combined_list_rows[:3]] == [
        due_task_id,
        older_unscheduled_id,
        newer_unscheduled_id,
    ]

    combined_backlog = client.get(
        "/v1/human/tasks/backlog",
        params={"sort": "sla_due_at_asc_last_transition_desc", "limit": 10},
    )
    assert combined_backlog.status_code == 200
    combined_backlog_rows = [
        row
        for row in combined_backlog.json()
        if row["human_task_id"] in {due_task_id, older_unscheduled_id, newer_unscheduled_id}
    ]
    assert [row["human_task_id"] for row in combined_backlog_rows[:3]] == [
        due_task_id,
        older_unscheduled_id,
        newer_unscheduled_id,
    ]


def test_rewrite_blocked_policy_flow_has_error_envelope() -> None:
    client = _client(storage_backend="memory")
    blocked = client.post("/v1/rewrite/artifact", json={"text": "x" * 20001})
    assert blocked.status_code == 403
    body = blocked.json()
    assert body["error"]["code"] == "policy_denied:input_too_large"
    assert body["error"]["correlation_id"]


def test_observation_and_delivery_flow() -> None:
    client = _client(storage_backend="memory")

    obs = client.post(
        "/v1/observations/ingest",
        json={
            "principal_id": "exec-1",
            "channel": "email",
            "event_type": "thread.opened",
            "payload": {"subject": "Board prep"},
            "source_id": "gmail:account-1",
            "external_id": "msg-1",
            "dedupe_key": "obs-gmail-msg-1",
            "auth_context_json": {"scope": "mail.readonly"},
            "raw_payload_uri": "s3://bucket/raw/msg-1.json",
        },
    )
    assert obs.status_code == 200
    observation_id = obs.json()["observation_id"]
    assert obs.json()["dedupe_key"] == "obs-gmail-msg-1"

    recent = client.get("/v1/observations/recent", params={"limit": 10})
    assert recent.status_code == 200
    assert any(r["observation_id"] == observation_id for r in recent.json())

    obs_dupe = client.post(
        "/v1/observations/ingest",
        json={
            "principal_id": "exec-1",
            "channel": "email",
            "event_type": "thread.opened",
            "payload": {"subject": "Board prep"},
            "source_id": "gmail:account-1",
            "external_id": "msg-1",
            "dedupe_key": "obs-gmail-msg-1",
        },
    )
    assert obs_dupe.status_code == 200
    assert obs_dupe.json()["observation_id"] == observation_id

    queued = client.post(
        "/v1/delivery/outbox",
        json={
            "channel": "slack",
            "recipient": "U1",
            "content": "Draft ready",
            "metadata": {"priority": "high"},
            "idempotency_key": "delivery-msg-1",
        },
    )
    assert queued.status_code == 200
    delivery_id = queued.json()["delivery_id"]
    assert queued.json()["idempotency_key"] == "delivery-msg-1"

    queued_dupe = client.post(
        "/v1/delivery/outbox",
        json={
            "channel": "slack",
            "recipient": "U1",
            "content": "Draft ready duplicate",
            "metadata": {"priority": "high"},
            "idempotency_key": "delivery-msg-1",
        },
    )
    assert queued_dupe.status_code == 200
    assert queued_dupe.json()["delivery_id"] == delivery_id

    failed = client.post(
        f"/v1/delivery/outbox/{delivery_id}/failed",
        json={"error": "temporary channel error", "retry_in_seconds": 0, "dead_letter": False},
    )
    assert failed.status_code == 200
    assert failed.json()["status"] == "retry"
    assert failed.json()["attempt_count"] == 1
    assert failed.json()["last_error"] == "temporary channel error"

    pending = client.get("/v1/delivery/outbox/pending", params={"limit": 10})
    assert pending.status_code == 200
    assert any(r["delivery_id"] == delivery_id for r in pending.json())

    sent = client.post(f"/v1/delivery/outbox/{delivery_id}/sent")
    assert sent.status_code == 200
    assert sent.json()["status"] == "sent"


def test_telegram_adapter_ingest() -> None:
    client = _client(storage_backend="memory")
    resp = client.post(
        "/v1/channels/telegram/ingest",
        json={
            "update": {
                "message": {
                    "chat": {"id": 42},
                    "text": "hello",
                    "message_id": 7,
                    "date": 123,
                }
            }
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["channel"] == "telegram"
    assert body["event_type"] == "telegram.message"


def test_tool_registry_and_connector_bindings_flow() -> None:
    client = _client(storage_backend="memory")

    tool = client.post(
        "/v1/tools/registry",
        json={
            "tool_name": "email.send",
            "version": "v1",
            "input_schema_json": {"type": "object", "properties": {"to": {"type": "string"}}},
            "output_schema_json": {"type": "object"},
            "policy_json": {"risk": "medium"},
            "allowed_channels": ["email", "slack"],
            "approval_default": "manager",
            "enabled": True,
        },
    )
    assert tool.status_code == 200
    assert tool.json()["tool_name"] == "email.send"

    listed_tools = client.get("/v1/tools/registry", params={"limit": 10})
    assert listed_tools.status_code == 200
    assert any(row["tool_name"] == "artifact_repository" for row in listed_tools.json())
    assert any(row["tool_name"] == "connector.dispatch" for row in listed_tools.json())
    assert any(row["tool_name"] == "email.send" for row in listed_tools.json())

    execute_unregistered = client.post(
        "/v1/tools/execute",
        json={
            "tool_name": "provider.not_registered",
            "action_kind": "delivery.send",
            "payload_json": {},
        },
    )
    assert execute_unregistered.status_code == 404
    assert execute_unregistered.json()["error"]["code"] == "tool_not_registered:provider.not_registered"

    binding = client.post(
        "/v1/connectors/bindings",
        json={
            "connector_name": "gmail",
            "external_account_ref": "acct-1",
            "scope_json": {"scopes": ["mail.send", "sms.send"]},
            "auth_metadata_json": {"provider": "google"},
            "status": "enabled",
        },
    )
    assert binding.status_code == 200
    binding_id = binding.json()["binding_id"]
    assert binding.json()["principal_id"] == "exec-1"

    listed_bindings = client.get("/v1/connectors/bindings", params={"limit": 10})
    assert listed_bindings.status_code == 200
    assert any(row["binding_id"] == binding_id for row in listed_bindings.json())

    executed = client.post(
        "/v1/tools/execute",
        json={
            "tool_name": "connector.dispatch",
            "action_kind": "delivery.send",
            "payload_json": {
                "principal_id": "exec-1",
                "binding_id": binding_id,
                "channel": "email",
                "recipient": "ops@example.com",
                "content": "Queued from tool runtime",
                "metadata": {"source": "tool-execute"},
                "idempotency_key": "tool-dispatch-1",
            },
        },
    )
    assert executed.status_code == 200
    assert executed.json()["tool_name"] == "connector.dispatch"
    assert executed.json()["output_json"]["status"] == "queued"
    assert executed.json()["output_json"]["binding_id"] == binding_id
    assert executed.json()["receipt_json"]["handler_key"] == "connector.dispatch"
    assert executed.json()["receipt_json"]["invocation_contract"] == "tool.v1"

    email_handler_missing = client.post(
        "/v1/tools/execute",
        json={
            "tool_name": "email.send",
            "action_kind": "delivery.send",
            "payload_json": {
                "recipient": "ops@example.com",
                "content": "Not wired to runtime handler",
            },
        },
    )
    assert email_handler_missing.status_code == 409
    assert email_handler_missing.json()["error"]["code"] == "tool_handler_missing:email.send"

    pending_after_execute = client.get("/v1/delivery/outbox/pending", params={"limit": 10})
    assert pending_after_execute.status_code == 200
    assert any(row["delivery_id"] == executed.json()["target_ref"] for row in pending_after_execute.json())

    execute_mismatch = client.post(
        "/v1/tools/execute",
        json={
            "tool_name": "connector.dispatch",
            "action_kind": "delivery.send",
            "payload_json": {
                "principal_id": "exec-1",
                "binding_id": binding_id,
                "channel": "email",
                "recipient": "ops@example.com",
                "content": "Should not queue",
            },
        },
        headers=_headers(principal_id="exec-2"),
    )
    assert execute_mismatch.status_code == 403
    assert execute_mismatch.json()["error"]["code"] == "principal_scope_mismatch"

    execute_bad_channel = client.post(
        "/v1/tools/execute",
        json={
            "tool_name": "connector.dispatch",
            "action_kind": "delivery.send",
            "payload_json": {
                "principal_id": "exec-1",
                "binding_id": binding_id,
                "channel": "sms",
                "recipient": "ops@example.com",
                "content": "Should fail dispatch",
            },
        },
    )
    assert execute_bad_channel.status_code == 409
    assert (
        execute_bad_channel.json()["error"]["code"]
        == "connector_dispatch_channel_not_allowed:sms:email,slack,telegram"
    )

    readonly_binding = client.post(
        "/v1/connectors/bindings",
        json={
            "connector_name": "gmail",
            "external_account_ref": "ops-readonly",
            "scope_json": {"scopes": ["mail.readonly"]},
            "auth_metadata_json": {"provider": "google"},
            "status": "enabled",
        },
    )
    assert readonly_binding.status_code == 200

    execute_scope_mismatch = client.post(
        "/v1/tools/execute",
        json={
            "tool_name": "connector.dispatch",
            "action_kind": "delivery.send",
            "payload_json": {
                "principal_id": "exec-1",
                "binding_id": readonly_binding.json()["binding_id"],
                "channel": "email",
                "recipient": "ops@example.com",
                "content": "Should fail scope validation",
            },
        },
    )
    assert execute_scope_mismatch.status_code == 403
    assert execute_scope_mismatch.json()["error"]["code"] == (
        "connector_binding_scope_mismatch:"
        f"{readonly_binding.json()['binding_id']}:email,email.send,mail,mail.send,send.mail"
    )

    mismatch = client.get("/v1/connectors/bindings", params={"principal_id": "exec-2", "limit": 10})
    assert mismatch.status_code == 403
    assert mismatch.json()["error"]["code"] == "principal_scope_mismatch"

    browseract_execute_mismatch = client.post(
        "/v1/tools/execute",
        headers=_headers(principal_id="exec-2"),
        json={
            "tool_name": "browseract.extract_account_facts",
            "action_kind": "account.extract",
            "payload_json": {
                "principal_id": "exec-1",
                "binding_id": binding_id,
                "service_name": "BrowserAct",
            },
        },
    )
    assert browseract_execute_mismatch.status_code == 403
    assert browseract_execute_mismatch.json()["error"]["code"] == "principal_scope_mismatch"

    browseract_binding = client.post(
        "/v1/connectors/bindings",
        json={
            "connector_name": "browseract",
            "external_account_ref": "browseract-primary",
            "scope_json": {"services": ["BrowserAct"]},
            "auth_metadata_json": {"service_accounts_json": {"BrowserAct": {"tier": "Tier 3"}}},
            "status": "enabled",
        },
    )
    assert browseract_binding.status_code == 200

    browseract_scope_mismatch = client.post(
        "/v1/tools/execute",
        json={
            "tool_name": "browseract.extract_account_facts",
            "action_kind": "account.extract",
            "payload_json": {
                "principal_id": "exec-1",
                "binding_id": browseract_binding.json()["binding_id"],
                "service_name": "Teable",
            },
        },
    )
    assert browseract_scope_mismatch.status_code == 403
    assert browseract_scope_mismatch.json()["error"]["code"] == (
        f"connector_binding_scope_mismatch:{browseract_binding.json()['binding_id']}:teable"
    )

    unsigned_client = _client(storage_backend="memory", principal_id="")
    unsigned_binding = unsigned_client.post(
        "/v1/connectors/bindings",
        json={
            "connector_name": "browseract",
            "external_account_ref": "browseract-unsigned",
            "scope_json": {},
            "auth_metadata_json": {"service_accounts_json": {"BrowserAct": {"tier": "Tier 3"}}},
            "status": "enabled",
        },
    )
    assert unsigned_binding.status_code == 200

    browseract_unsigned_request_principal_mismatch = unsigned_client.post(
        "/v1/tools/execute",
        json={
            "tool_name": "browseract.extract_account_facts",
            "action_kind": "account.extract",
            "payload_json": {
                "principal_id": "exec-1",
                "binding_id": unsigned_binding.json()["binding_id"],
                "service_name": "BrowserAct",
            },
        },
    )
    assert browseract_unsigned_request_principal_mismatch.status_code == 403
    assert (
        browseract_unsigned_request_principal_mismatch.json()["error"]["code"]
        == "principal_scope_mismatch"
    )

    foreign_status = client.post(
        f"/v1/connectors/bindings/{binding_id}/status",
        json={"status": "disabled"},
        headers=_headers(principal_id="exec-2"),
    )
    assert foreign_status.status_code == 404
    assert foreign_status.json()["error"]["code"] == "binding_not_found"

    disabled = client.post(
        f"/v1/connectors/bindings/{binding_id}/status",
        json={"status": "disabled"},
    )
    assert disabled.status_code == 200


def test_browseract_tool_execution_and_workflow_template_flow() -> None:
    client = _client(storage_backend="memory", principal_id="exec-1")

    binding = client.post(
        "/v1/connectors/bindings",
        json={
            "connector_name": "browseract",
            "external_account_ref": "browseract-main",
            "scope_json": {"services": ["BrowserAct", "Teable"]},
            "auth_metadata_json": {
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
            "status": "enabled",
        },
    )
    assert binding.status_code == 200
    binding_id = binding.json()["binding_id"]

    listed_tools = client.get("/v1/tools/registry", params={"limit": 20})
    assert listed_tools.status_code == 200
    assert any(row["tool_name"] == "browseract.extract_account_facts" for row in listed_tools.json())
    assert any(row["tool_name"] == "browseract.extract_account_inventory" for row in listed_tools.json())

    executed = client.post(
        "/v1/tools/execute",
        json={
            "tool_name": "browseract.extract_account_facts",
            "action_kind": "account.extract",
            "payload_json": {
                "principal_id": "exec-1",
                "binding_id": binding_id,
                "service_name": "BrowserAct",
                "requested_fields": ["tier", "account_email", "status"],
                "instructions": "Use stored BrowserAct credentials",
                "account_hints_json": {"BrowserAct": {"workspace": "primary"}},
                "run_url": "https://browseract.example/run",
            },
        },
    )
    assert executed.status_code == 200
    executed_body = executed.json()
    assert executed_body["tool_name"] == "browseract.extract_account_facts"
    assert executed_body["output_json"]["service_name"] == "BrowserAct"
    assert executed_body["output_json"]["facts_json"]["tier"] == "Tier 3"
    assert executed_body["output_json"]["account_email"] == "ops@example.com"
    assert executed_body["output_json"]["missing_fields"] == []
    assert executed_body["output_json"]["instructions"] == "Use stored BrowserAct credentials"
    assert executed_body["output_json"]["account_hints_json"] == {"BrowserAct": {"workspace": "primary"}}
    assert executed_body["output_json"]["requested_run_url"] == "https://browseract.example/run"
    assert executed_body["receipt_json"]["handler_key"] == "browseract.extract_account_facts"
    assert executed_body["receipt_json"]["invocation_contract"] == "tool.v1"

    inventory_executed = client.post(
        "/v1/tools/execute",
        json={
            "tool_name": "browseract.extract_account_inventory",
            "action_kind": "account.extract_inventory",
            "payload_json": {
                "principal_id": "exec-1",
                "binding_id": binding_id,
                "service_names": ["BrowserAct", "Teable", "UnknownService"],
                "requested_fields": ["tier", "account_email", "status"],
                "instructions": "Use stored BrowserAct credentials",
                "account_hints_json": {"Teable": {"workspace": "ops"}},
                "run_url": "https://browseract.example/run",
            },
        },
    )
    assert inventory_executed.status_code == 200
    inventory_body = inventory_executed.json()
    assert inventory_body["tool_name"] == "browseract.extract_account_inventory"
    assert inventory_body["output_json"]["service_names"] == ["BrowserAct", "Teable", "UnknownService"]
    assert inventory_body["output_json"]["missing_services"] == ["UnknownService"]
    assert inventory_body["output_json"]["instructions"] == "Use stored BrowserAct credentials"
    assert inventory_body["output_json"]["account_hints_json"] == {"Teable": {"workspace": "ops"}}
    assert inventory_body["output_json"]["requested_run_url"] == "https://browseract.example/run"
    assert inventory_body["output_json"]["services_json"][1]["plan_tier"] == "License Tier 4"
    assert inventory_body["output_json"]["services_json"][1]["structured_output_json"]["account_hints_json"] == {
        "Teable": {"workspace": "ops"}
    }
    assert inventory_body["receipt_json"]["handler_key"] == "browseract.extract_account_inventory"

    contract = client.post(
        "/v1/tasks/contracts",
        json={
            "task_key": "browseract_ltd_discovery",
            "deliverable_type": "ltd_service_profile",
            "default_risk_class": "low",
            "default_approval_class": "none",
            "allowed_tools": ["browseract.extract_account_facts", "artifact_repository"],
            "evidence_requirements": ["account_inventory"],
            "memory_write_policy": "none",
            "budget_policy_json": {
                "class": "low",
                "workflow_template": "browseract_extract_then_artifact",
            },
        },
    )
    assert contract.status_code == 200

    compiled = client.post(
        "/v1/plans/compile",
        json={
            "task_key": "browseract_ltd_discovery",
            "goal": "extract LTD account facts for BrowserAct",
        },
    )
    assert compiled.status_code == 200
    plan_steps = compiled.json()["plan"]["steps"]
    assert [step["step_key"] for step in plan_steps] == [
        "step_input_prepare",
        "step_browseract_extract",
        "step_artifact_save",
    ]
    assert plan_steps[1]["tool_name"] == "browseract.extract_account_facts"
    assert plan_steps[1]["depends_on"] == ["step_input_prepare"]
    assert plan_steps[1]["input_keys"] == [
        "binding_id",
        "service_name",
        "requested_fields",
        "instructions",
        "account_hints_json",
        "run_url",
    ]
    assert "structured_output_json" in plan_steps[1]["output_keys"]
    assert plan_steps[2]["depends_on"] == ["step_browseract_extract"]
    assert plan_steps[2]["input_keys"] == ["normalized_text", "structured_output_json", "preview_text", "mime_type"]

    execute = client.post(
        "/v1/plans/execute",
        json={
            "task_key": "browseract_ltd_discovery",
            "goal": "extract LTD account facts for BrowserAct",
            "input_json": {
                "binding_id": binding_id,
                "service_name": "BrowserAct",
                "requested_fields": ["tier", "account_email", "status"],
            },
        },
    )
    assert execute.status_code == 200
    execute_body = execute.json()
    assert execute_body["task_key"] == "browseract_ltd_discovery"
    assert execute_body["kind"] == "ltd_service_profile"
    assert "Service: BrowserAct" in execute_body["content"]
    assert execute_body["structured_output_json"]["facts_json"]["tier"] == "Tier 3"
    assert execute_body["structured_output_json"]["account_email"] == "ops@example.com"
    session_id = execute_body["execution_session_id"]

    session = client.get(f"/v1/rewrite/sessions/{session_id}")
    assert session.status_code == 200
    session_body = session.json()
    assert session_body["status"] == "completed"
    assert session_body["intent_task_type"] == "browseract_ltd_discovery"
    steps_by_key = {step["input_json"]["plan_step_key"]: step for step in session_body["steps"]}
    assert steps_by_key["step_browseract_extract"]["state"] == "completed"
    assert steps_by_key["step_artifact_save"]["state"] == "completed"
    assert steps_by_key["step_browseract_extract"]["output_json"]["account_email"] == "ops@example.com"
    assert [row["tool_name"] for row in session_body["receipts"]] == [
        "browseract.extract_account_facts",
        "artifact_repository",
    ]
    assert disabled.json()["status"] == "disabled"

    generic_contract = client.post(
        "/v1/tasks/contracts",
        json={
            "task_key": "browseract_ltd_discovery_generic",
            "deliverable_type": "ltd_service_profile",
            "default_risk_class": "low",
            "default_approval_class": "none",
            "allowed_tools": ["browseract.extract_account_facts", "artifact_repository"],
            "evidence_requirements": ["account_inventory"],
            "memory_write_policy": "none",
            "budget_policy_json": {
                "class": "low",
                "workflow_template": "tool_then_artifact",
                "pre_artifact_tool_name": "browseract.extract_account_facts",
            },
        },
    )
    assert generic_contract.status_code == 200

    generic_compiled = client.post(
        "/v1/plans/compile",
        json={
            "task_key": "browseract_ltd_discovery_generic",
            "goal": "extract LTD account facts for BrowserAct",
        },
    )
    assert generic_compiled.status_code == 200
    generic_plan_steps = generic_compiled.json()["plan"]["steps"]
    assert [step["step_key"] for step in generic_plan_steps] == [
        "step_input_prepare",
        "step_browseract_extract",
        "step_artifact_save",
    ]
    assert generic_plan_steps[0]["input_keys"] == [
        "binding_id",
        "service_name",
        "requested_fields",
        "instructions",
        "account_hints_json",
        "run_url",
    ]
    assert generic_plan_steps[1]["tool_name"] == "browseract.extract_account_facts"
    assert generic_plan_steps[2]["input_keys"] == [
        "normalized_text",
        "structured_output_json",
        "preview_text",
        "mime_type",
    ]

    generic_execute = client.post(
        "/v1/plans/execute",
        json={
            "task_key": "browseract_ltd_discovery_generic",
            "goal": "extract LTD account facts for BrowserAct",
            "input_json": {
                "binding_id": binding_id,
                "service_name": "BrowserAct",
                "requested_fields": ["tier", "account_email", "status"],
            },
        },
    )
    assert generic_execute.status_code == 200
    generic_body = generic_execute.json()
    assert generic_body["task_key"] == "browseract_ltd_discovery_generic"
    assert generic_body["kind"] == "ltd_service_profile"
    assert generic_body["structured_output_json"]["facts_json"]["tier"] == "Tier 3"
    assert generic_body["structured_output_json"]["account_email"] == "ops@example.com"
    generic_session = client.get(f"/v1/rewrite/sessions/{generic_body['execution_session_id']}")
    assert generic_session.status_code == 200
    assert [row["tool_name"] for row in generic_session.json()["receipts"]] == [
        "browseract.extract_account_facts",
        "artifact_repository",
    ]

    inventory_contract = client.post(
        "/v1/tasks/contracts",
        json={
            "task_key": "browseract_ltd_inventory_refresh",
            "deliverable_type": "ltd_inventory_profile",
            "default_risk_class": "low",
            "default_approval_class": "none",
            "allowed_tools": ["browseract.extract_account_inventory", "artifact_repository"],
            "evidence_requirements": ["account_inventory"],
            "memory_write_policy": "none",
            "budget_policy_json": {
                "class": "low",
                "workflow_template": "tool_then_artifact",
                "pre_artifact_tool_name": "browseract.extract_account_inventory",
            },
        },
    )
    assert inventory_contract.status_code == 200

    inventory_compiled = client.post(
        "/v1/plans/compile",
        json={
            "task_key": "browseract_ltd_inventory_refresh",
            "goal": "refresh LTD inventory facts",
        },
    )
    assert inventory_compiled.status_code == 200
    inventory_plan_steps = inventory_compiled.json()["plan"]["steps"]
    assert [step["step_key"] for step in inventory_plan_steps] == [
        "step_input_prepare",
        "step_browseract_inventory_extract",
        "step_artifact_save",
    ]
    assert inventory_plan_steps[0]["input_keys"] == [
        "binding_id",
        "service_names",
        "requested_fields",
        "instructions",
        "account_hints_json",
        "run_url",
    ]
    assert inventory_plan_steps[1]["tool_name"] == "browseract.extract_account_inventory"

    inventory_execute = client.post(
        "/v1/plans/execute",
        json={
            "task_key": "browseract_ltd_inventory_refresh",
            "goal": "refresh LTD inventory facts",
            "input_json": {
                "binding_id": binding_id,
                "service_names": ["BrowserAct", "Teable", "UnknownService"],
                "requested_fields": ["tier", "account_email", "status"],
            },
        },
    )
    assert inventory_execute.status_code == 200
    inventory_artifact = inventory_execute.json()
    assert inventory_artifact["task_key"] == "browseract_ltd_inventory_refresh"
    assert inventory_artifact["kind"] == "ltd_inventory_profile"
    assert inventory_artifact["structured_output_json"]["missing_services"] == ["UnknownService"]
    assert inventory_artifact["structured_output_json"]["services_json"][1]["plan_tier"] == "License Tier 4"
    inventory_session = client.get(f"/v1/rewrite/sessions/{inventory_artifact['execution_session_id']}")
    assert inventory_session.status_code == 200
    assert [row["tool_name"] for row in inventory_session.json()["receipts"]] == [
        "browseract.extract_account_inventory",
        "artifact_repository",
    ]


def test_task_contracts_flow_and_rewrite_compilation() -> None:
    client = _client(storage_backend="memory", approval_threshold_chars=20000)

    created = client.post(
        "/v1/tasks/contracts",
        json={
            "task_key": "rewrite_text",
            "deliverable_type": "rewrite_note",
            "default_risk_class": "low",
            "default_approval_class": "manager",
            "allowed_tools": ["artifact_repository"],
            "evidence_requirements": [],
            "memory_write_policy": "reviewed_only",
            "budget_policy_json": {"class": "low"},
        },
    )
    assert created.status_code == 200
    assert created.json()["task_key"] == "rewrite_text"

    listed = client.get("/v1/tasks/contracts", params={"limit": 10})
    assert listed.status_code == 200
    assert any(row["task_key"] == "rewrite_text" for row in listed.json())

    fetched = client.get("/v1/tasks/contracts/rewrite_text")
    assert fetched.status_code == 200
    assert fetched.json()["default_approval_class"] == "manager"

    compiled = client.post(
        "/v1/plans/compile",
        json={"task_key": "rewrite_text", "principal_id": "exec-1", "goal": "rewrite this"},
    )
    assert compiled.status_code == 200
    assert compiled.json()["intent"]["task_type"] == "rewrite_text"
    assert len(compiled.json()["plan"]["steps"]) == 3
    assert compiled.json()["plan"]["steps"][0]["step_key"] == "step_input_prepare"
    assert compiled.json()["plan"]["steps"][0]["owner"] == "system"
    assert compiled.json()["plan"]["steps"][0]["authority_class"] == "observe"
    assert compiled.json()["plan"]["steps"][0]["review_class"] == "none"
    assert compiled.json()["plan"]["steps"][0]["failure_strategy"] == "fail"
    assert compiled.json()["plan"]["steps"][0]["timeout_budget_seconds"] == 30
    assert compiled.json()["plan"]["steps"][0]["max_attempts"] == 1
    assert compiled.json()["plan"]["steps"][0]["retry_backoff_seconds"] == 0
    assert compiled.json()["plan"]["steps"][1]["step_key"] == "step_policy_evaluate"
    assert compiled.json()["plan"]["steps"][1]["step_kind"] == "policy_check"
    assert compiled.json()["plan"]["steps"][1]["depends_on"] == ["step_input_prepare"]
    assert compiled.json()["plan"]["steps"][1]["owner"] == "system"
    assert compiled.json()["plan"]["steps"][1]["authority_class"] == "observe"
    assert compiled.json()["plan"]["steps"][1]["output_keys"] == [
        "allow",
        "requires_approval",
        "reason",
        "retention_policy",
        "memory_write_allowed",
    ]
    assert compiled.json()["plan"]["steps"][2]["tool_name"] == "artifact_repository"
    assert compiled.json()["plan"]["steps"][2]["depends_on"] == ["step_policy_evaluate"]
    assert compiled.json()["plan"]["steps"][2]["owner"] == "tool"
    assert compiled.json()["plan"]["steps"][2]["authority_class"] == "draft"
    assert compiled.json()["plan"]["steps"][2]["review_class"] == "none"
    assert compiled.json()["plan"]["steps"][2]["failure_strategy"] == "fail"
    assert compiled.json()["plan"]["steps"][2]["timeout_budget_seconds"] == 60
    assert compiled.json()["plan"]["steps"][2]["approval_required"] is True

    review_contract = client.post(
        "/v1/tasks/contracts",
        json={
            "task_key": "rewrite_review",
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
    assert review_contract.status_code == 200

    compiled_review = client.post(
        "/v1/plans/compile",
        json={"task_key": "rewrite_review", "principal_id": "exec-1", "goal": "review this rewrite"},
    )
    assert compiled_review.status_code == 200
    assert len(compiled_review.json()["plan"]["steps"]) == 4
    assert compiled_review.json()["plan"]["steps"][2]["step_key"] == "step_human_review"
    assert compiled_review.json()["plan"]["steps"][2]["step_kind"] == "human_task"
    assert compiled_review.json()["plan"]["steps"][2]["owner"] == "human"
    assert compiled_review.json()["plan"]["steps"][2]["authority_class"] == "draft"
    assert compiled_review.json()["plan"]["steps"][2]["review_class"] == "operator"
    assert compiled_review.json()["plan"]["steps"][2]["failure_strategy"] == "fail"
    assert compiled_review.json()["plan"]["steps"][2]["timeout_budget_seconds"] == 3600
    assert compiled_review.json()["plan"]["steps"][2]["max_attempts"] == 1
    assert compiled_review.json()["plan"]["steps"][2]["retry_backoff_seconds"] == 0
    assert compiled_review.json()["plan"]["steps"][2]["task_type"] == "communications_review"
    assert compiled_review.json()["plan"]["steps"][2]["role_required"] == "communications_reviewer"
    assert compiled_review.json()["plan"]["steps"][2]["priority"] == "high"
    assert compiled_review.json()["plan"]["steps"][2]["sla_minutes"] == 45
    assert compiled_review.json()["plan"]["steps"][2]["auto_assign_if_unique"] is True
    assert compiled_review.json()["plan"]["steps"][2]["desired_output_json"]["escalation_policy"] == "manager_review"
    assert compiled_review.json()["plan"]["steps"][2]["authority_required"] == "send_on_behalf_review"
    assert (
        compiled_review.json()["plan"]["steps"][2]["quality_rubric_json"]["checks"][0] == "tone"
    )
    assert compiled_review.json()["plan"]["steps"][3]["depends_on"] == ["step_human_review"]

    rewrite = client.post("/v1/rewrite/artifact", json={"text": "short rewrite input"})
    assert rewrite.status_code == 202
    assert rewrite.json()["status"] == "awaiting_approval"
    assert rewrite.json()["next_action"] == "poll_or_subscribe"


def test_skill_catalog_flow_and_meeting_prep_compilation() -> None:
    client = _client(storage_backend="memory", approval_threshold_chars=20000)

    created = client.post(
        "/v1/skills",
        json={
            "skill_key": "meeting_prep",
            "task_key": "meeting_prep",
            "name": "Meeting Prep",
            "description": "Build an executive-ready meeting prep packet.",
            "deliverable_type": "meeting_pack",
            "default_risk_class": "low",
            "default_approval_class": "none",
            "workflow_template": "artifact_then_memory_candidate",
            "allowed_tools": ["artifact_repository"],
            "evidence_requirements": ["stakeholder_context", "decision_context"],
            "memory_write_policy": "reviewed_only",
            "memory_reads": ["stakeholders", "commitments", "decision_windows"],
            "memory_writes": ["meeting_pack_fact"],
            "tags": ["executive", "meeting", "briefing"],
            "authority_profile_json": {"authority_class": "draft", "review_class": "operator"},
            "provider_hints_json": {
                "primary": ["1min.AI"],
                "research": ["BrowserAct", "Paperguide"],
                "output": ["MarkupGo"],
            },
            "human_policy_json": {"review_roles": ["briefing_reviewer"]},
            "evaluation_cases_json": [{"case_key": "meeting_prep_golden", "priority": "high"}],
            "budget_policy_json": {
                "class": "low",
                "memory_candidate_category": "meeting_pack_fact",
                "memory_candidate_confidence": 0.8,
                "memory_candidate_sensitivity": "internal",
            },
        },
    )
    assert created.status_code == 200
    assert created.json()["skill_key"] == "meeting_prep"
    assert created.json()["workflow_template"] == "artifact_then_memory_candidate"
    assert created.json()["provider_hints_json"]["primary"] == ["1min.AI"]

    listed = client.get("/v1/skills", params={"limit": 10})
    assert listed.status_code == 200
    assert any(row["skill_key"] == "meeting_prep" for row in listed.json())
    filtered = client.get("/v1/skills", params={"limit": 10, "provider_hint": "browseract"})
    assert filtered.status_code == 200
    assert [row["skill_key"] for row in filtered.json()] == ["meeting_prep"]

    fetched = client.get("/v1/skills/meeting_prep")
    assert fetched.status_code == 200
    assert fetched.json()["memory_reads"] == ["stakeholders", "commitments", "decision_windows"]
    assert fetched.json()["memory_writes"] == ["meeting_pack_fact"]
    assert fetched.json()["provider_hints_json"]["research"] == ["BrowserAct", "Paperguide"]
    assert fetched.json()["human_policy_json"]["review_roles"] == ["briefing_reviewer"]

    compiled = client.post(
        "/v1/plans/compile",
        json={"task_key": "meeting_prep", "goal": "prepare the board meeting packet"},
    )
    assert compiled.status_code == 200
    assert compiled.json()["skill_key"] == "meeting_prep"
    assert [step["step_key"] for step in compiled.json()["plan"]["steps"]] == [
        "step_input_prepare",
        "step_policy_evaluate",
        "step_artifact_save",
        "step_memory_candidate_stage",
    ]

    compiled_via_skill = client.post(
        "/v1/plans/compile",
        json={"skill_key": "meeting_prep", "goal": "prepare the board meeting packet"},
    )
    assert compiled_via_skill.status_code == 200
    assert compiled_via_skill.json()["skill_key"] == "meeting_prep"
    assert compiled_via_skill.json()["plan"]["task_key"] == "meeting_prep"


def test_skill_catalog_can_project_ltd_inventory_refresh_runtime() -> None:
    client = _client(storage_backend="memory", approval_threshold_chars=20000)

    binding = client.post(
        "/v1/connectors/bindings",
        json={
            "connector_name": "browseract",
            "external_account_ref": "browseract-main",
            "scope_json": {"services": ["BrowserAct", "Teable", "UnknownService"]},
            "auth_metadata_json": {
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
            "status": "enabled",
        },
    )
    assert binding.status_code == 200
    binding_id = binding.json()["binding_id"]

    created = client.post(
        "/v1/skills",
        json={
            "skill_key": "ltd_inventory_refresh",
            "task_key": "ltd_inventory_refresh",
            "name": "LTD Inventory Refresh",
            "description": "Refresh BrowserAct-backed LTD account facts.",
            "deliverable_type": "ltd_inventory_profile",
            "default_risk_class": "low",
            "default_approval_class": "none",
            "workflow_template": "tool_then_artifact",
            "allowed_tools": ["browseract.extract_account_inventory", "artifact_repository"],
            "evidence_requirements": ["account_inventory"],
            "memory_write_policy": "none",
            "memory_reads": ["account_inventory"],
            "memory_writes": [],
            "tags": ["ltd", "inventory", "operations"],
            "authority_profile_json": {"authority_class": "observe", "review_class": "none"},
            "provider_hints_json": {
                "primary": ["BrowserAct"],
                "ops": ["Teable"],
                "output": ["MarkupGo"],
            },
            "tool_policy_json": {
                "allowed_tools": ["browseract.extract_account_inventory", "artifact_repository"]
            },
            "evaluation_cases_json": [{"case_key": "ltd_inventory_refresh_golden", "priority": "medium"}],
            "budget_policy_json": {
                "class": "low",
                "pre_artifact_tool_name": "browseract.extract_account_inventory",
            },
        },
    )
    assert created.status_code == 200
    assert created.json()["skill_key"] == "ltd_inventory_refresh"

    filtered = client.get("/v1/skills", params={"limit": 10, "provider_hint": "browseract"})
    assert filtered.status_code == 200
    assert [row["skill_key"] for row in filtered.json()] == ["ltd_inventory_refresh"]

    fetched = client.get("/v1/skills/ltd_inventory_refresh")
    assert fetched.status_code == 200
    assert fetched.json()["provider_hints_json"]["ops"] == ["Teable"]

    compiled = client.post(
        "/v1/plans/compile",
        json={"task_key": "ltd_inventory_refresh", "goal": "refresh LTD inventory facts"},
    )
    assert compiled.status_code == 200
    assert compiled.json()["skill_key"] == "ltd_inventory_refresh"
    assert [step["step_key"] for step in compiled.json()["plan"]["steps"]] == [
        "step_input_prepare",
        "step_browseract_inventory_extract",
        "step_artifact_save",
    ]

    compiled_via_skill = client.post(
        "/v1/plans/compile",
        json={"skill_key": "ltd_inventory_refresh", "goal": "refresh LTD inventory facts"},
    )
    assert compiled_via_skill.status_code == 200
    assert compiled_via_skill.json()["skill_key"] == "ltd_inventory_refresh"

    executed = client.post(
        "/v1/plans/execute",
        json={
            "task_key": "ltd_inventory_refresh",
            "goal": "refresh LTD inventory facts",
            "input_json": {
                "binding_id": binding_id,
                "service_names": ["BrowserAct", "Teable", "UnknownService"],
                "requested_fields": ["tier", "account_email", "status"],
            },
        },
    )
    assert executed.status_code == 200
    body = executed.json()
    assert body["skill_key"] == "ltd_inventory_refresh"
    assert body["kind"] == "ltd_inventory_profile"
    assert body["structured_output_json"]["missing_services"] == ["UnknownService"]

    executed_via_skill = client.post(
        "/v1/plans/execute",
        json={
            "skill_key": "ltd_inventory_refresh",
            "goal": "refresh LTD inventory facts",
            "input_json": {
                "binding_id": binding_id,
                "service_names": ["BrowserAct", "Teable", "UnknownService"],
                "requested_fields": ["tier", "account_email", "status"],
            },
        },
    )
    assert executed_via_skill.status_code == 200
    assert executed_via_skill.json()["skill_key"] == "ltd_inventory_refresh"
    assert executed_via_skill.json()["task_key"] == "ltd_inventory_refresh"

    session = client.get(f"/v1/rewrite/sessions/{body['execution_session_id']}")
    assert session.status_code == 200
    session_body = session.json()
    assert session_body["intent_skill_key"] == "ltd_inventory_refresh"
    assert [row["tool_name"] for row in session_body["receipts"]] == [
        "browseract.extract_account_inventory",
        "artifact_repository",
    ]


def test_plan_compile_derives_request_principal_and_rejects_mismatch() -> None:
    client = _client(storage_backend="memory", principal_id="exec-1")

    compiled = client.post(
        "/v1/plans/compile",
        json={"task_key": "rewrite_text", "goal": "rewrite this"},
    )
    assert compiled.status_code == 200
    assert compiled.json()["intent"]["principal_id"] == "exec-1"
    assert compiled.json()["plan"]["principal_id"] == "exec-1"

    mismatch = client.post(
        "/v1/plans/compile",
        json={"task_key": "rewrite_text", "principal_id": "exec-2", "goal": "rewrite this"},
    )
    assert mismatch.status_code == 403
    assert mismatch.json()["error"]["code"] == "principal_scope_mismatch"


def test_generic_task_execution_uses_compiled_contract_runtime() -> None:
    client = _client(storage_backend="memory", principal_id="exec-1")

    contract = client.post(
        "/v1/tasks/contracts",
        json={
            "task_key": "stakeholder_briefing",
            "deliverable_type": "stakeholder_briefing",
            "default_risk_class": "low",
            "default_approval_class": "none",
            "allowed_tools": ["artifact_repository"],
            "evidence_requirements": ["stakeholder_context"],
            "memory_write_policy": "reviewed_only",
            "budget_policy_json": {"class": "low"},
        },
    )
    assert contract.status_code == 200

    execute = client.post(
        "/v1/plans/execute",
        json={
            "task_key": "stakeholder_briefing",
            "input_json": {
                "source_text": "Board context and stakeholder sensitivities.",
                "channel": "email",
                "stakeholder_ref": "alex-exec",
            },
            "context_refs": ["thread:board-prep", "memory:item:stakeholder-brief"],
            "goal": "prepare a stakeholder briefing",
        },
    )
    assert execute.status_code == 200
    body = execute.json()
    assert body["skill_key"] == "stakeholder_briefing"
    assert body["task_key"] == "stakeholder_briefing"
    assert body["kind"] == "stakeholder_briefing"
    assert body["content"] == "Board context and stakeholder sensitivities."
    assert body["execution_session_id"]
    assert body["deliverable_type"] == "stakeholder_briefing"
    assert body["principal_id"] == "exec-1"
    assert body["mime_type"] == "text/plain"
    assert body["preview_text"] == "Board context and stakeholder sensitivities."
    assert body["storage_handle"] == f"artifact://{body['artifact_id']}"
    assert body["body_ref"] == f"artifact://{body['artifact_id']}"
    assert body["structured_output_json"] == {}
    assert body["attachments_json"] == {}

    session = client.get(f"/v1/rewrite/sessions/{body['execution_session_id']}")
    assert session.status_code == 200
    session_body = session.json()
    assert session_body["intent_skill_key"] == "stakeholder_briefing"
    assert session_body["intent_task_type"] == "stakeholder_briefing"
    assert session_body["status"] == "completed"
    assert session_body["artifacts"][0]["kind"] == "stakeholder_briefing"
    assert session_body["artifacts"][0]["skill_key"] == "stakeholder_briefing"
    assert session_body["artifacts"][0]["task_key"] == "stakeholder_briefing"
    assert session_body["artifacts"][0]["deliverable_type"] == "stakeholder_briefing"
    assert session_body["artifacts"][0]["principal_id"] == "exec-1"
    assert session_body["artifacts"][0]["mime_type"] == "text/plain"
    assert session_body["artifacts"][0]["preview_text"] == "Board context and stakeholder sensitivities."
    assert session_body["artifacts"][0]["storage_handle"] == f"artifact://{body['artifact_id']}"
    assert session_body["artifacts"][0]["body_ref"].startswith("file://")
    assert session_body["artifacts"][0]["structured_output_json"] == {}
    assert session_body["artifacts"][0]["attachments_json"] == {}
    assert session_body["steps"][0]["parent_step_id"] is None
    assert session_body["steps"][1]["parent_step_id"] == session_body["steps"][0]["step_id"]
    assert session_body["steps"][2]["parent_step_id"] == session_body["steps"][1]["step_id"]
    assert session_body["steps"][2]["input_json"]["plan_step_key"] == "step_artifact_save"
    assert session_body["steps"][0]["input_json"]["channel"] == "email"
    assert session_body["steps"][0]["input_json"]["stakeholder_ref"] == "alex-exec"
    assert session_body["steps"][0]["input_json"]["context_refs"] == [
        "thread:board-prep",
        "memory:item:stakeholder-brief",
    ]
    plan_event = next(event for event in session_body["events"] if event["name"] == "plan_compiled")
    assert plan_event["payload"]["step_semantics"][0]["timeout_budget_seconds"] == 30

    fetched_artifact = client.get(f"/v1/rewrite/artifacts/{body['artifact_id']}")
    assert fetched_artifact.status_code == 200
    assert fetched_artifact.json()["skill_key"] == "stakeholder_briefing"
    assert fetched_artifact.json()["task_key"] == "stakeholder_briefing"
    assert fetched_artifact.json()["deliverable_type"] == "stakeholder_briefing"
    assert fetched_artifact.json()["principal_id"] == "exec-1"
    assert fetched_artifact.json()["mime_type"] == "text/plain"
    assert fetched_artifact.json()["preview_text"] == "Board context and stakeholder sensitivities."
    assert fetched_artifact.json()["storage_handle"] == f"artifact://{body['artifact_id']}"
    assert fetched_artifact.json()["body_ref"].startswith("file://")
    assert fetched_artifact.json()["structured_output_json"] == {}
    assert fetched_artifact.json()["attachments_json"] == {}

    fetched_receipt = client.get(f"/v1/rewrite/receipts/{session_body['receipts'][0]['receipt_id']}")
    assert fetched_receipt.status_code == 200
    assert fetched_receipt.json()["skill_key"] == "stakeholder_briefing"
    assert fetched_receipt.json()["task_key"] == "stakeholder_briefing"
    assert fetched_receipt.json()["deliverable_type"] == "stakeholder_briefing"

    fetched_cost = client.get(f"/v1/rewrite/run-costs/{session_body['run_costs'][0]['cost_id']}")
    assert fetched_cost.status_code == 200
    assert fetched_cost.json()["skill_key"] == "stakeholder_briefing"
    assert fetched_cost.json()["task_key"] == "stakeholder_briefing"
    assert fetched_cost.json()["deliverable_type"] == "stakeholder_briefing"

    mismatch = client.post(
        "/v1/plans/execute",
        json={
            "task_key": "stakeholder_briefing",
            "text": "Should stay in principal scope.",
            "principal_id": "exec-2",
            "goal": "prepare a stakeholder briefing",
        },
    )
    assert mismatch.status_code == 403
    assert mismatch.json()["error"]["code"] == "principal_scope_mismatch"
