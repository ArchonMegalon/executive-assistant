from __future__ import annotations

from tests.product_test_helpers import build_operator_product_client, build_product_client, seed_product_state


def test_product_api_projects_real_runtime_objects() -> None:
    principal_id = "exec-product-api"
    client = build_product_client(principal_id=principal_id)
    seeded = seed_product_state(client, principal_id=principal_id)

    brief = client.get("/app/api/brief")
    assert brief.status_code == 200
    brief_body = brief.json()
    assert brief_body["total"] >= 1
    assert any(item["title"] == "Send board materials" for item in brief_body["items"])

    queue = client.get("/app/api/queue")
    assert queue.status_code == 200
    queue_body = queue.json()
    assert queue_body["total"] >= 3
    assert any(item["id"] == f"approval:{seeded['approval_id']}" for item in queue_body["items"])
    assert any(item["id"] == f"commitment:{seeded['commitment_id']}" for item in queue_body["items"])

    commitments = client.get("/app/api/commitments")
    assert commitments.status_code == 200
    commitment_rows = commitments.json()
    assert any(item["id"] == f"commitment:{seeded['commitment_id']}" for item in commitment_rows)
    assert any(item["id"] == f"follow_up:{seeded['follow_up_id']}" for item in commitment_rows)

    drafts = client.get("/app/api/drafts")
    assert drafts.status_code == 200
    draft_rows = drafts.json()
    assert draft_rows[0]["id"] == f"approval:{seeded['approval_id']}"
    assert draft_rows[0]["send_channel"] == "email"

    people = client.get("/app/api/people")
    assert people.status_code == 200
    people_rows = people.json()
    assert people_rows[0]["display_name"] == "Sofia N."
    person_detail = client.get(f"/app/api/people/{seeded['stakeholder_id']}")
    assert person_detail.status_code == 200
    assert person_detail.json()["open_loops_count"] >= 1
    person_graph_detail = client.get(f"/app/api/people/{seeded['stakeholder_id']}/detail")
    assert person_graph_detail.status_code == 200
    assert person_graph_detail.json()["profile"]["display_name"] == "Sofia N."
    assert any(item["statement"] == "Send board materials" for item in person_graph_detail.json()["commitments"])
    assert any(item["recipient_summary"] == "sofia@example.com" for item in person_graph_detail.json()["drafts"])

    handoffs = client.get("/app/api/handoffs")
    assert handoffs.status_code == 200
    handoff_rows = handoffs.json()
    assert handoff_rows[0]["id"] == f"human_task:{seeded['human_task_id']}"

    diagnostics = client.get("/app/api/diagnostics")
    assert diagnostics.status_code == 200
    diagnostics_body = diagnostics.json()
    assert diagnostics_body["workspace"]["mode"] == "personal"
    assert diagnostics_body["plan"]["plan_key"] == "pilot"
    assert diagnostics_body["billing"]["billing_state"] == "trial"
    assert diagnostics_body["billing"]["support_tier"] == "guided"
    assert diagnostics_body["entitlements"]["principal_seats"] == 1
    assert diagnostics_body["usage"]["queue_items"] >= 1


def test_product_commitment_detail_and_queue_resolution() -> None:
    principal_id = "exec-product-resolve"
    client = build_product_client(principal_id=principal_id)
    seeded = seed_product_state(client, principal_id=principal_id)
    commitment_ref = f"commitment:{seeded['commitment_id']}"

    detail = client.get(f"/app/api/commitments/{commitment_ref}")
    assert detail.status_code == 200
    assert detail.json()["statement"] == "Send board materials"

    resolved = client.post(
        f"/app/api/queue/{commitment_ref}/resolve",
        json={"action": "close", "reason": "Materials sent"},
    )
    assert resolved.status_code == 200
    assert resolved.json()["resolution_state"] == "completed"

    updated = client.get(f"/app/api/commitments/{commitment_ref}")
    assert updated.status_code == 200
    assert updated.json()["status"] == "completed"
    history = client.get(f"/app/api/commitments/{commitment_ref}/history")
    assert history.status_code == 200
    assert any(row["event_type"] == "commitment_closed" for row in history.json())

    created = client.post(
        "/app/api/commitments",
        json={
            "kind": "follow_up",
            "title": "Share revised board packet",
            "details": "Manual follow-up created from the product loop.",
            "stakeholder_id": seeded["stakeholder_id"],
            "counterparty": "Sofia N.",
            "due_at": "2026-03-25T16:00:00+00:00",
        },
    )
    assert created.status_code == 200
    assert created.json()["id"].startswith("follow_up:")
    assert created.json()["statement"] == "Share revised board packet"

    decision_resolved = client.post(
        f"/app/api/queue/decision:{seeded['decision_window_id']}/resolve",
        json={"action": "resolve", "reason": "Principal chose the owner"},
    )
    assert decision_resolved.status_code == 200
    assert decision_resolved.json()["resolution_state"] == "decided"

    deadline_closed = client.post(
        f"/app/api/queue/deadline:{seeded['deadline_window_id']}/resolve",
        json={"action": "close", "reason": "Window covered in the queue"},
    )
    assert deadline_closed.status_code == 200
    assert deadline_closed.json()["resolution_state"] == "elapsed"

    follow_up_dropped = client.post(
        f"/app/api/queue/follow_up:{seeded['follow_up_id']}/resolve",
        json={"action": "drop", "reason": "No longer needed"},
    )
    assert follow_up_dropped.status_code == 200
    assert follow_up_dropped.json()["resolution_state"] == "dropped"

    extracted = client.post(
        "/app/api/commitments/extract",
        json={
            "text": "I'll send the revised board packet and confirm the investor meeting time tomorrow.",
            "counterparty": "Sofia N.",
            "due_at": "2026-03-26T10:00:00+00:00",
        },
    )
    assert extracted.status_code == 200
    assert extracted.json()
    assert any("board packet" in item["title"].lower() for item in extracted.json())

    staged = client.post(
        "/app/api/commitments/candidates/stage",
        json={
            "text": "Please send the revised board packet to Sofia tomorrow morning.",
            "counterparty": "Sofia N.",
        },
    )
    assert staged.status_code == 200
    candidate_id = staged.json()[0]["candidate_id"]
    listed = client.get("/app/api/commitments/candidates")
    assert listed.status_code == 200
    assert any(row["candidate_id"] == candidate_id for row in listed.json())

    accepted = client.post(
        f"/app/api/commitments/candidates/{candidate_id}/accept",
        json={
            "reviewer": "operator-office",
            "title": "Send revised board packet",
            "details": "Edited before promotion from the candidate queue.",
            "counterparty": "Sofia N.",
            "due_at": "2026-03-27T10:00:00+00:00",
        },
    )
    assert accepted.status_code == 200
    assert accepted.json()["statement"] == "Send revised board packet"
    assert accepted.json()["due_at"] == "2026-03-27T10:00:00+00:00"

    restaged = client.post(
        "/app/api/commitments/candidates/stage",
        json={
            "text": "Confirm investor dinner date with Sofia next week.",
            "counterparty": "Sofia N.",
        },
    )
    reject_candidate_id = restaged.json()[0]["candidate_id"]
    rejected = client.post(
        f"/app/api/commitments/candidates/{reject_candidate_id}/reject",
        json={"reviewer": "operator-office"},
    )
    assert rejected.status_code == 200
    assert rejected.json()["status"] == "rejected"


def test_product_draft_approval_uses_real_approval_runtime() -> None:
    principal_id = "exec-product-approvals"
    client = build_product_client(principal_id=principal_id)
    seeded = seed_product_state(client, principal_id=principal_id)
    draft_ref = f"approval:{seeded['approval_id']}"

    approved = client.post(
        f"/app/api/drafts/{draft_ref}/approve",
        json={"reason": "Looks good to send"},
    )
    assert approved.status_code == 200
    body = approved.json()
    assert body["id"] == draft_ref
    assert body["approval_status"] == "approved"

    pending = client.get("/app/api/drafts")
    assert pending.status_code == 200
    assert all(item["id"] != draft_ref for item in pending.json())


def test_product_draft_rejection_uses_real_approval_runtime() -> None:
    principal_id = "exec-product-rejections"
    client = build_product_client(principal_id=principal_id)
    seeded = seed_product_state(client, principal_id=principal_id)
    draft_ref = f"approval:{seeded['approval_id']}"

    rejected = client.post(
        f"/app/api/drafts/{draft_ref}/reject",
        json={"reason": "Not ready to send"},
    )
    assert rejected.status_code == 200
    body = rejected.json()
    assert body["id"] == draft_ref
    assert body["approval_status"] == "rejected"

    pending = client.get("/app/api/drafts")
    assert pending.status_code == 200
    assert all(item["id"] != draft_ref for item in pending.json())


def test_product_handoffs_can_be_assigned_and_completed_by_operator() -> None:
    principal_id = "exec-product-handoffs"
    client = build_operator_product_client(principal_id=principal_id, operator_id="operator-office")
    seeded = seed_product_state(client, principal_id=principal_id)
    handoff_ref = f"human_task:{seeded['human_task_id']}"

    assigned = client.post(
        f"/app/api/handoffs/{handoff_ref}/assign",
        json={"operator_id": seeded["operator_id"]},
    )
    assert assigned.status_code == 200
    assert assigned.json()["owner"] == seeded["operator_id"]

    completed = client.post(
        f"/app/api/handoffs/{handoff_ref}/complete",
        json={"operator_id": seeded["operator_id"], "resolution": "completed"},
    )
    assert completed.status_code == 200
    assert completed.json()["status"] == "returned"

    returned = client.get("/app/api/handoffs", params={"status": "returned"})
    assert returned.status_code == 200
    assert any(row["id"] == handoff_ref and row["status"] == "returned" for row in returned.json())


def test_operator_scope_hides_other_operator_handoffs_from_queue_and_browser() -> None:
    principal_id = "exec-product-operator-scope"
    client = build_operator_product_client(principal_id=principal_id, operator_id="operator-office")
    seeded = seed_product_state(client, principal_id=principal_id)
    container = client.app.state.container
    container.orchestrator.upsert_operator_profile(
        principal_id=principal_id,
        operator_id="operator-other",
        display_name="Other Operator",
        roles=("operator",),
        trust_tier="trusted",
        status="active",
        notes="Seeded to verify operator scoping.",
    )
    other_task = container.orchestrator.create_human_task(
        session_id=seeded["session_id"],
        principal_id=principal_id,
        task_type="handoff",
        role_required="operator",
        brief="Other operator-only handoff",
        why_human="Should not leak into another operator lane.",
        priority="high",
        sla_due_at="2026-03-25T14:00:00+00:00",
    )
    assigned = container.orchestrator.assign_human_task(
        other_task.human_task_id,
        principal_id=principal_id,
        operator_id="operator-other",
        assignment_source="seed",
        assigned_by_actor_id="fixture",
    )
    assert assigned is not None

    handoffs = client.get("/app/api/handoffs")
    assert handoffs.status_code == 200
    assert all(item["summary"] != "Other operator-only handoff" for item in handoffs.json())

    queue = client.get("/app/api/queue")
    assert queue.status_code == 200
    assert all(item["title"] != "Other operator-only handoff" for item in queue.json()["items"])

    activity = client.get("/app/activity")
    assert activity.status_code == 200
    assert "Other operator-only handoff" not in activity.text


def test_people_graph_correction_updates_person_detail() -> None:
    principal_id = "exec-product-people-correction"
    client = build_product_client(principal_id=principal_id)
    seeded = seed_product_state(client, principal_id=principal_id)

    corrected = client.post(
        f"/app/api/people/{seeded['stakeholder_id']}/correct",
        json={
            "preferred_tone": "warm",
            "add_theme": "board packet",
            "add_risk": "travel coordination",
        },
    )
    assert corrected.status_code == 200
    body = corrected.json()
    assert body["profile"]["preferred_tone"] == "warm"
    assert "board packet" in body["profile"]["themes"]
    assert "travel coordination" in body["profile"]["risks"]
    assert any(row["event_type"] == "memory_corrected" for row in body["history"])

    history = client.get(f"/app/api/people/{seeded['stakeholder_id']}/history")
    assert history.status_code == 200
    assert any(row["event_type"] == "memory_corrected" for row in history.json())


def test_product_diagnostics_include_value_events() -> None:
    principal_id = "exec-product-analytics"
    client = build_operator_product_client(principal_id=principal_id, operator_id="operator-office")
    seeded = seed_product_state(client, principal_id=principal_id)

    created = client.post(
        "/app/api/commitments",
        json={
            "title": "Send operator summary",
            "details": "Created from product diagnostics event test.",
            "counterparty": "Office operator",
        },
    )
    assert created.status_code == 200

    approved = client.post(
        f"/app/api/drafts/approval:{seeded['approval_id']}/approve",
        json={"reason": "Approved for analytics test"},
    )
    assert approved.status_code == 200

    closed = client.post(
        f"/app/api/queue/commitment:{seeded['commitment_id']}/resolve",
        json={"action": "close", "reason": "Closed for analytics test"},
    )
    assert closed.status_code == 200

    completed = client.post(
        f"/app/api/handoffs/human_task:{seeded['human_task_id']}/complete",
        json={"operator_id": seeded["operator_id"], "resolution": "completed"},
    )
    assert completed.status_code == 200

    corrected = client.post(
        f"/app/api/people/{seeded['stakeholder_id']}/correct",
        json={"add_theme": "board packet"},
    )
    assert corrected.status_code == 200

    diagnostics = client.get("/app/api/diagnostics")
    assert diagnostics.status_code == 200
    analytics = diagnostics.json()["analytics"]["counts"]
    assert analytics["draft_approved"] >= 1
    assert analytics["commitment_created"] >= 1
    assert analytics["commitment_closed"] >= 1
    assert analytics["handoff_completed"] >= 1
    assert analytics["memory_corrected"] >= 1

    bundle = client.get("/app/api/diagnostics/export")
    assert bundle.status_code == 200
    body = bundle.json()
    assert body["workspace"]["mode"] == "personal"
    assert body["plan"]["plan_key"] == "pilot"
    assert body["billing"]["billing_state"] == "trial"
    assert body["billing"]["renewal_owner_role"] == "principal"
    assert "pending" in body["approvals"]
    assert isinstance(body["human_tasks"], list)
    assert isinstance(body["pending_delivery"], list)
