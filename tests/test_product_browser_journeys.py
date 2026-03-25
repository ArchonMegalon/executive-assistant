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

    person_detail = client.get(f"/app/people/{seeded['stakeholder_id']}")
    assert person_detail.status_code == 200
    assert "Sofia N." in person_detail.text
    assert "Open commitments" in person_detail.text
    assert "Send board materials" in person_detail.text


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
