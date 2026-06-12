from __future__ import annotations

from tests.product_test_helpers import build_product_client, seed_product_state, start_workspace


def test_ea_core_first_value_journey_reaches_reviewable_office_loop() -> None:
    principal_id = "exec-first-value-journey"
    client = build_product_client(principal_id=principal_id)

    start_workspace(client, mode="executive_ops", workspace_name="Founder Office")
    seeded = seed_product_state(client, principal_id=principal_id)

    onboarding = client.get("/register")
    assert onboarding.status_code == 200
    assert "Start a workspace that shows the first useful loop." in onboarding.text
    assert "Google sign-in" in onboarding.text
    assert "Workspace shape" in onboarding.text
    assert 'href="/app/today"' in onboarding.text

    settings = client.get("/app/settings")
    assert settings.status_code == 200
    assert "Connect now" in settings.text
    assert "What is feeding the office loop" in settings.text

    today = client.get("/app/today")
    assert today.status_code == 200
    assert "Morning Memo" in today.text
    assert "Send board materials" in today.text
    assert "Approve reply to Sofia N." in today.text

    queue = client.get("/app/queue")
    assert queue.status_code == 200
    assert "Queue" in queue.text
    assert "Choose board memo owner" in queue.text
    assert "Board memo delivery window" in queue.text

    commitments = client.get("/app/commitments")
    assert commitments.status_code == 200
    assert "Confirm investor meeting time" in commitments.text
    assert "Prepare board follow-up handoff" in commitments.text
    assert "Send board materials" in commitments.text

    pending = client.get("/v1/policy/approvals/pending", params={"limit": 10})
    assert pending.status_code == 200
    assert any(row["approval_id"] == seeded["approval_id"] for row in pending.json())

    approve = client.post(
        f"/app/api/drafts/approval:{seeded['approval_id']}/approve",
        json={"reason": "Reviewed in the first-value journey; keep manual-send boundary explicit."},
    )
    assert approve.status_code == 200
    queue_after_approval = client.get("/app/queue")
    assert "Approve reply to Sofia N." not in queue_after_approval.text
