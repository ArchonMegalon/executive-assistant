from __future__ import annotations

from tests.product_test_helpers import build_product_client, seed_product_state


def test_workspace_pages_render_seeded_product_objects() -> None:
    principal_id = "exec-browser-journey"
    client = build_product_client(principal_id=principal_id)
    seeded = seed_product_state(client, principal_id=principal_id)

    today = client.get("/app/today")
    assert today.status_code == 200
    assert "Morning Memo" in today.text
    assert "Send board materials" in today.text
    assert "Approve reply to Sofia N." in today.text
    assert "Sofia N." in today.text

    briefing = client.get("/app/briefing")
    assert briefing.status_code == 200
    assert "Decision Queue" in briefing.text
    assert "Choose board memo owner" in briefing.text
    assert "Board memo delivery window" in briefing.text

    inbox = client.get("/app/inbox")
    assert inbox.status_code == 200
    assert "Commitments" in inbox.text
    assert "Send board materials" in inbox.text
    assert "sofia@example.com" in inbox.text

    followups = client.get("/app/follow-ups")
    assert followups.status_code == 200
    assert "Handoffs" in followups.text
    assert "Prepare board follow-up handoff" in followups.text
    assert "Confirm investor meeting time" in followups.text
    assert seeded["human_task_id"] in client.get("/app/api/handoffs").text

    activity = client.get("/app/activity")
    assert activity.status_code == 200
    assert "Operator Queue" in activity.text
    assert "Queue health" in activity.text
    assert "Suggested next claims" in activity.text
    assert "Prepare board follow-up handoff" in activity.text

    settings = client.get("/app/settings")
    assert settings.status_code == 200
    assert "Rules" in settings.text
    assert "Workspace diagnostics bundle" in settings.text
    assert "Billing state" in settings.text
    assert "Messaging scope" in settings.text
    assert "Feature flags" in settings.text
    assert "/app/settings/plan" in settings.text
    assert "/app/settings/usage" in settings.text
    assert "/app/settings/support" in settings.text

    person_detail = client.get(f"/app/people/{seeded['stakeholder_id']}")
    assert person_detail.status_code == 200
    assert "Sofia N." in person_detail.text
    assert "Open commitments" in person_detail.text
    assert "Send board materials" in person_detail.text

    onboarding = client.get("/get-started")
    assert onboarding.status_code == 200
    assert "Current plan posture" in onboarding.text
    assert "Open workspace diagnostics" in onboarding.text

    diagnostics = client.get("/app/api/diagnostics")
    assert diagnostics.status_code == 200
    counts = diagnostics.json()["analytics"]["counts"]
    assert int(counts.get("memo_opened") or 0) >= 1
    assert int(counts.get("rules_opened") or 0) >= 1


def test_browser_journey_updates_after_approval_and_commitment_closure() -> None:
    principal_id = "exec-browser-journey-resolve"
    client = build_product_client(principal_id=principal_id)
    seeded = seed_product_state(client, principal_id=principal_id)

    approved = client.post(
        f"/app/api/drafts/approval:{seeded['approval_id']}/approve",
        json={"reason": "Ready to send"},
    )
    assert approved.status_code == 200

    queue_after_approval = client.get("/app/briefing")
    assert queue_after_approval.status_code == 200
    assert "Approve reply to Sofia N." not in queue_after_approval.text

    closed = client.post(
        f"/app/api/queue/commitment:{seeded['commitment_id']}/resolve",
        json={"action": "close", "reason": "Materials sent"},
    )
    assert closed.status_code == 200

    inbox_after_close = client.get("/app/inbox")
    assert inbox_after_close.status_code == 200
    assert "Send board materials" not in inbox_after_close.text

    followups = client.get("/app/follow-ups")
    assert followups.status_code == 200
    assert "Prepare board follow-up handoff" in followups.text


def test_browser_action_routes_match_rendered_forms() -> None:
    principal_id = "exec-browser-action-routes"
    client = build_product_client(principal_id=principal_id)
    seeded = seed_product_state(client, principal_id=principal_id)

    approved = client.post(
        f"/app/actions/drafts/approval:{seeded['approval_id']}/approve",
        data={"return_to": "/app/inbox"},
        follow_redirects=False,
    )
    assert approved.status_code == 303
    assert approved.headers["location"] == "/app/inbox"
    assert "Approve reply to Sofia N." not in client.get("/app/briefing").text

    closed = client.post(
        f"/app/actions/queue/commitment:{seeded['commitment_id']}/resolve",
        data={"action": "close", "return_to": "/app/inbox"},
        follow_redirects=False,
    )
    assert closed.status_code == 303
    assert closed.headers["location"] == "/app/inbox"
    assert "Send board materials" not in client.get("/app/inbox").text

    dropped = client.post(
        f"/app/actions/queue/follow_up:{seeded['follow_up_id']}/resolve",
        data={"action": "drop", "return_to": "/app/follow-ups"},
        follow_redirects=False,
    )
    assert dropped.status_code == 303
    assert dropped.headers["location"] == "/app/follow-ups"
    assert "Confirm investor meeting time" not in client.get("/app/follow-ups").text

    reseeded = seed_product_state(client, principal_id=principal_id)
    rejected = client.post(
        f"/app/actions/drafts/approval:{reseeded['approval_id']}/reject",
        data={"return_to": "/app/inbox"},
        follow_redirects=False,
    )
    assert rejected.status_code == 303
    assert rejected.headers["location"] == "/app/inbox"
    assert f"approval:{reseeded['approval_id']}" not in client.get("/app/api/drafts").text


def test_browser_handoff_and_people_memory_actions_work() -> None:
    principal_id = "exec-browser-person-memory"
    client = build_product_client(principal_id=principal_id)
    seeded = seed_product_state(client, principal_id=principal_id)

    assigned = client.post(
        f"/app/actions/handoffs/human_task:{seeded['human_task_id']}/assign",
        data={"return_to": "/app/follow-ups"},
        follow_redirects=False,
    )
    assert assigned.status_code == 303
    assert assigned.headers["location"] == "/app/follow-ups"

    completed = client.post(
        f"/app/actions/handoffs/human_task:{seeded['human_task_id']}/complete",
        data={"return_to": "/app/follow-ups", "action": "completed"},
        follow_redirects=False,
    )
    assert completed.status_code == 303
    assert completed.headers["location"] == "/app/follow-ups"
    activity_page = client.get("/app/activity")
    assert activity_page.status_code == 200
    assert "Recently completed" in activity_page.text
    assert "Prepare board follow-up handoff" in activity_page.text

    corrected = client.post(
        f"/app/actions/people/{seeded['stakeholder_id']}/correct",
        data={
            "return_to": f"/app/people/{seeded['stakeholder_id']}",
            "preferred_tone": "warm",
            "add_theme": "board packet",
            "add_risk": "travel coordination",
        },
        follow_redirects=False,
    )
    assert corrected.status_code == 303
    person_page = client.get(f"/app/people/{seeded['stakeholder_id']}")
    assert person_page.status_code == 200
    assert "warm" in person_page.text
    assert "board packet" in person_page.text
    assert "travel coordination" in person_page.text
    assert "Recent relationship history" in person_page.text
    assert "Memory Corrected" in person_page.text


def test_object_detail_routes_render_core_product_objects() -> None:
    principal_id = "exec-browser-object-details"
    client = build_product_client(principal_id=principal_id)
    seeded = seed_product_state(client, principal_id=principal_id)

    decisions = client.get("/app/api/decisions")
    assert decisions.status_code == 200
    decision_id = decisions.json()["items"][0]["id"]
    assert f"/app/decisions/{decision_id}" in client.get("/app/briefing").text
    decision_page = client.get(f"/app/decisions/{decision_id}")
    assert decision_page.status_code == 200
    assert "Choose board memo owner" in decision_page.text
    assert "Decision queue" in decision_page.text
    assert "Impact" in decision_page.text
    assert "SLA" in decision_page.text

    threads = client.get("/app/api/threads")
    assert threads.status_code == 200
    thread_id = threads.json()["items"][0]["id"]
    assert f"/app/threads/{thread_id}" in client.get("/app/inbox").text
    thread_page = client.get(f"/app/threads/{thread_id}")
    assert thread_page.status_code == 200
    assert "Conversation thread" in thread_page.text
    assert "sofia@example.com" in thread_page.text

    assert f"/app/commitment-items/commitment:{seeded['commitment_id']}" in client.get("/app/follow-ups").text
    commitment_page = client.get(f"/app/commitment-items/commitment:{seeded['commitment_id']}")
    assert commitment_page.status_code == 200
    assert "Commitment ledger" in commitment_page.text
    assert "Recent ledger activity" in commitment_page.text

    handoffs = client.get("/app/api/handoffs")
    assert handoffs.status_code == 200
    handoff_id = handoffs.json()[0]["id"]
    assert handoff_id in client.get("/app/activity").text
    handoff_page = client.get(f"/app/handoffs/{handoff_id}")
    assert handoff_page.status_code == 200
    assert "Handoffs" in handoff_page.text
    assert "Recent assignment events" in handoff_page.text

    evidence = client.get("/app/api/evidence")
    assert evidence.status_code == 200
    evidence_id = evidence.json()["items"][0]["id"]
    assert f"/app/evidence/{evidence_id}" in client.get("/app/contacts").text
    evidence_page = client.get(f"/app/evidence/{evidence_id}")
    assert evidence_page.status_code == 200
    assert "Evidence" in evidence_page.text
    assert "Objects linked to this evidence" in evidence_page.text

    rules = client.get("/app/api/rules")
    assert rules.status_code == 200
    rule_id = rules.json()["items"][0]["id"]
    assert f"/app/rules/{rule_id}" in client.get("/app/settings").text
    rule_page = client.get(f"/app/rules/{rule_id}")
    assert rule_page.status_code == 200
    assert "Rules" in rule_page.text
    assert "Expected effect" in rule_page.text
    assert seeded["decision_window_id"] in decisions.text

    plan_page = client.get("/app/settings/plan")
    assert plan_page.status_code == 200
    assert "Commercial boundary" in plan_page.text
    assert "What this workspace includes" in plan_page.text

    usage_page = client.get("/app/settings/usage")
    assert usage_page.status_code == 200
    assert "Usage state" in usage_page.text
    assert "Product loop signals" in usage_page.text

    support_page = client.get("/app/settings/support")
    assert support_page.status_code == 200
    assert "Support bundle" in support_page.text
    assert "Pending review and recent decisions" in support_page.text


def test_browser_commitment_capture_actions_work() -> None:
    principal_id = "exec-browser-capture"
    client = build_product_client(principal_id=principal_id)
    seeded = seed_product_state(client, principal_id=principal_id)

    created = client.post(
        "/app/actions/commitments/create",
        data={
            "title": "Confirm board dinner date",
            "details": "Manual follow-up from the browser surface.",
            "counterparty": "Sofia N.",
            "kind": "follow_up",
            "stakeholder_id": seeded["stakeholder_id"],
            "return_to": "/app/follow-ups",
        },
        follow_redirects=False,
    )
    assert created.status_code == 303
    followups = client.get("/app/follow-ups")
    assert followups.status_code == 200
    assert "Confirm board dinner date" in followups.text

    extracted = client.post(
        "/app/actions/commitments/extract",
        data={
            "source_text": "Please send the revised board packet to Sofia tomorrow morning.",
            "counterparty": "Sofia N.",
            "return_to": "/app/inbox",
        },
        follow_redirects=False,
    )
    assert extracted.status_code == 303
    inbox = client.get("/app/inbox")
    assert inbox.status_code == 200
    assert "Accept" in inbox.text
    assert "revised board packet" in inbox.text.lower()
