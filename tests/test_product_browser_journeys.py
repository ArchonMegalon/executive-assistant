from __future__ import annotations

import urllib.parse

from tests.product_test_helpers import build_operator_product_client, build_product_client, seed_product_state, start_workspace


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
    assert "Draft Queue" in inbox.text
    assert "Open commitments" in inbox.text
    assert "Send board materials" in inbox.text
    assert "sofia@example.com" in inbox.text

    followups = client.get("/app/follow-ups")
    assert followups.status_code == 200
    assert "What is blocked outside the office loop" in followups.text
    assert "Prepare board follow-up handoff" in followups.text
    assert "Confirm investor meeting time" in followups.text
    assert seeded["human_task_id"] in client.get("/app/api/handoffs").text

    activity = client.get("/app/activity")
    assert activity.status_code == 200
    assert "Operator Queue" in activity.text
    assert "Queue health" in activity.text
    assert "Load score" in activity.text
    assert "Provider posture" in activity.text
    assert "Last Google sync" in activity.text
    assert "Pending sync candidates" in activity.text
    assert "Suggested next claims" in activity.text
    assert "Clear before principal" in activity.text
    assert "Exception queue" in activity.text
    assert "Prepare board follow-up handoff" in activity.text

    settings = client.get("/app/settings")
    assert settings.status_code == 200
    assert "Rules" in settings.text
    assert "Morning memo delivery" in settings.text
    assert "What is feeding the office loop" in settings.text
    assert "Office-loop proof" in settings.text
    assert "Journey gate health" in settings.text
    assert "Connect now" in settings.text
    assert "/app/settings/outcomes" in settings.text
    assert "/app/settings/google" in settings.text
    assert "/app/settings/support" not in settings.text
    assert "/app/settings/access" not in settings.text
    assert "/app/settings/invitations" not in settings.text

    invitations = client.get("/app/settings/invitations")
    assert invitations.status_code == 200
    assert "Workspace invitations" in invitations.text
    assert "Invite email failures" in invitations.text

    search_page = client.get("/app/search", params={"query": "Sofia"})
    assert search_page.status_code == 200
    assert "Workspace search" in search_page.text
    assert "Results for “Sofia”" in search_page.text
    assert "Sofia N." in search_page.text
    assert "/app/threads/" in search_page.text
    assert "/app/inbox?focus=" not in search_page.text
    assert 'name="return_to" value="/app/search?query=Sofia&amp;limit=20"' in search_page.text

    person_detail = client.get(f"/app/people/{seeded['stakeholder_id']}")
    assert person_detail.status_code == 200
    assert "Sofia N." in person_detail.text
    assert "Open commitments" in person_detail.text
    assert "Send board materials" in person_detail.text

    onboarding = client.get("/register")
    assert onboarding.status_code == 200
    assert "Create a personal workspace before you add anything else." in onboarding.text
    assert "Google Core" in onboarding.text
    assert "Workspace mode stays personal here." in onboarding.text
    assert "Current plan posture" not in onboarding.text
    assert "operator seat" not in onboarding.text

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
    assert "What just moved through the loop" in followups.text
    assert "Send board materials" in followups.text
    assert "Reopen" in followups.text
    assert "Prepare board follow-up handoff" in followups.text

    activity_after_close = client.get("/app/activity")
    assert activity_after_close.status_code == 200
    assert "What just moved through the operator lane" in activity_after_close.text
    assert "Send board materials" in activity_after_close.text

    search_after_close = client.get("/app/search", params={"query": "board materials"})
    assert search_after_close.status_code == 200
    assert "Send board materials" in search_after_close.text
    assert "Reopen" in search_after_close.text
    assert "/app/commitment-items/" in search_after_close.text
    assert "/app/follow-ups?focus=" not in search_after_close.text
    commitment_search_ref = f"commitment:{seeded['commitment_id']}"
    commitment_search_href = f"/app/commitment-items/{urllib.parse.quote(commitment_search_ref, safe='')}"
    assert search_after_close.text.count(commitment_search_href) == 1
    assert 'name="return_to" value="/app/search?query=board+materials&amp;limit=20"' in search_after_close.text


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

    reseeded_commitment = seed_product_state(client, principal_id=principal_id)
    deferred = client.post(
        f"/app/actions/queue/follow_up:{reseeded_commitment['follow_up_id']}/resolve",
        data={"action": "defer", "return_to": "/app/follow-ups"},
        follow_redirects=False,
    )
    assert deferred.status_code == 303
    assert deferred.headers["location"] == "/app/follow-ups"
    deferred_followups = client.get("/app/follow-ups")
    assert deferred_followups.status_code == 200
    assert "Confirm investor meeting time" in deferred_followups.text
    assert "Defer" in deferred_followups.text

    waiting = client.post(
        f"/app/actions/queue/follow_up:{reseeded_commitment['follow_up_id']}/resolve",
        data={
            "action": "wait",
            "reason_code": "waiting_on_external",
            "reason": "Investor needs to confirm availability.",
            "due_at": "2026-03-28T09:30:00+00:00",
            "return_to": "/app/follow-ups",
        },
        follow_redirects=False,
    )
    assert waiting.status_code == 303
    assert waiting.headers["location"] == "/app/follow-ups"
    waiting_detail = client.get(f"/app/api/commitments/follow_up:{reseeded_commitment['follow_up_id']}")
    assert waiting_detail.status_code == 200
    assert waiting_detail.json()["status"] == "waiting_on_external"
    assert waiting_detail.json()["resolution_code"] == "waiting_on_external"
    assert waiting_detail.json()["due_at"] == "2026-03-28T09:30:00+00:00"

    dropped = client.post(
        f"/app/actions/queue/follow_up:{seeded['follow_up_id']}/resolve",
        data={"action": "drop", "return_to": "/app/follow-ups"},
        follow_redirects=False,
    )
    assert dropped.status_code == 303
    assert dropped.headers["location"] == "/app/follow-ups"
    dropped_detail = client.get(f"/app/api/commitments/follow_up:{seeded['follow_up_id']}")
    assert dropped_detail.status_code == 200
    assert dropped_detail.json()["status"] == "dropped"

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
    assert "Recent threads" in person_page.text
    assert "sofia@example.com" in person_page.text
    assert "Recent relationship history" in person_page.text
    assert "Memory Corrected" in person_page.text


def test_delivery_followup_browser_actions_surface_send_and_reauth_controls() -> None:
    principal_id = "exec-browser-delivery-followup"
    client = build_operator_product_client(principal_id=principal_id, operator_id="operator-office")
    seeded = seed_product_state(client, principal_id=principal_id)

    approved = client.post(
        f"/app/api/drafts/approval:{seeded['approval_id']}/approve",
        json={"reason": "Route to manual delivery"},
    )
    assert approved.status_code == 200

    handoffs = client.get("/app/api/handoffs")
    assert handoffs.status_code == 200
    followup = next(item for item in handoffs.json() if item["task_type"] == "delivery_followup")

    assigned = client.post(
        f"/app/api/handoffs/{followup['id']}/assign",
        json={"operator_id": seeded["operator_id"]},
    )
    assert assigned.status_code == 200

    followups_page = client.get("/app/follow-ups")
    assert followups_page.status_code == 200
    assert "Retry send" in followups_page.text
    assert "Mark sent" in followups_page.text
    assert "Needs reauth" in followups_page.text
    assert "Waiting on principal" in followups_page.text
    assert "Connect Google" in followups_page.text or "Reconnect Google" in followups_page.text

    handoff_page = client.get(f"/app/handoffs/{followup['id']}")
    assert handoff_page.status_code == 200
    assert "Delivery reason" in handoff_page.text
    assert "Retry send" in handoff_page.text
    assert "Waiting on principal" in handoff_page.text
    assert "Connect Google" in handoff_page.text or "Reconnect Google" in handoff_page.text

    threads = client.get("/app/api/threads")
    assert threads.status_code == 200
    thread_id = next(item["id"] for item in threads.json()["items"] if item["status"] == "delivery_followup")
    thread_page = client.get(f"/app/threads/{thread_id}")
    assert thread_page.status_code == 200
    assert "Retry send" in thread_page.text
    assert "Open handoff" in thread_page.text
    assert "Mark sent" in thread_page.text
    assert "Waiting on principal" in thread_page.text
    assert "Connect Google" in thread_page.text or "Reconnect Google" in thread_page.text

    handoff_detail = client.get(f"/app/api/handoffs/{followup['id']}")
    assert handoff_detail.status_code == 200
    assert handoff_detail.json()["delivery_reason"].startswith("google_")


def test_thread_detail_can_resume_blocked_delivery_followup() -> None:
    principal_id = "exec-browser-thread-resume-followup"
    client = build_operator_product_client(principal_id=principal_id, operator_id="operator-office")
    seeded = seed_product_state(client, principal_id=principal_id)

    approved = client.post(
        f"/app/api/drafts/approval:{seeded['approval_id']}/approve",
        json={"reason": "Route to manual delivery"},
    )
    assert approved.status_code == 200

    handoffs = client.get("/app/api/handoffs")
    assert handoffs.status_code == 200
    followup = next(item for item in handoffs.json() if item["task_type"] == "delivery_followup")

    assigned = client.post(
        f"/app/api/handoffs/{followup['id']}/assign",
        json={"operator_id": seeded["operator_id"]},
    )
    assert assigned.status_code == 200

    completed = client.post(
        f"/app/api/handoffs/{followup['id']}/complete",
        json={"operator_id": seeded["operator_id"], "resolution": "waiting_on_principal"},
    )
    assert completed.status_code == 200

    threads = client.get("/app/api/threads")
    assert threads.status_code == 200
    thread_id = next(item["id"] for item in threads.json()["items"] if item["status"] == "waiting_on_principal")

    thread_page = client.get(f"/app/threads/{thread_id}")
    assert thread_page.status_code == 200
    assert "Resume follow-up" in thread_page.text
    assert "Open handoff" in thread_page.text

    resumed = client.post(
        f"/app/actions/threads/{thread_id}/resume-delivery",
        data={"return_to": f"/app/threads/{thread_id}"},
        follow_redirects=False,
    )
    assert resumed.status_code == 303
    assert resumed.headers["location"].endswith("send_status=resumed")

    pending_handoffs = client.get("/app/api/handoffs")
    assert pending_handoffs.status_code == 200
    reopened = next(item for item in pending_handoffs.json() if item["task_type"] == "delivery_followup")
    assert reopened["draft_ref"] == f"approval:{seeded['approval_id']}"

    reopened_thread_page = client.get(f"/app/threads/{thread_id}")
    assert reopened_thread_page.status_code == 200
    assert "Retry send" in reopened_thread_page.text
    assert "Mark sent" in reopened_thread_page.text


def test_google_settings_surface_connect_action_and_browser_connect_route(monkeypatch) -> None:
    monkeypatch.setenv("EA_GOOGLE_OAUTH_CLIENT_ID", "google-client")
    monkeypatch.setenv("EA_GOOGLE_OAUTH_CLIENT_SECRET", "google-secret")
    monkeypatch.setenv("EA_GOOGLE_OAUTH_REDIRECT_URI", "https://ea.example/v1/providers/google/oauth/callback")
    monkeypatch.setenv("EA_GOOGLE_OAUTH_STATE_SECRET", "google-state-secret")
    monkeypatch.setenv("EA_PROVIDER_SECRET_KEY", "provider-secret-key")
    principal_id = "exec-browser-google-connect"
    client = build_product_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Founder Office")

    settings = client.get("/app/settings/google")
    assert settings.status_code == 200
    assert "Connect Google" in settings.text
    assert "/app/actions/google/connect?return_to=/app/settings/google" in settings.text

    started = client.get("/app/actions/google/connect", params={"return_to": "/app/settings/google"}, follow_redirects=False)
    assert started.status_code == 303
    parsed = urllib.parse.urlparse(started.headers["location"])
    query = urllib.parse.parse_qs(parsed.query)
    assert "https://accounts.google.com/o/oauth2/v2/auth" in started.headers["location"]
    assert query["redirect_uri"][0] == "https://ea.example/v1/providers/google/oauth/callback"


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
    assert "Next action" in decision_page.text
    assert "Recent decision history" in decision_page.text
    assert "Related threads" in decision_page.text
    assert "Update decision state" in decision_page.text
    deadline_ref = f"deadline:{seeded['deadline_window_id']}"
    assert f"/app/deadlines/{deadline_ref}" in client.get("/app/briefing").text
    deadline_page = client.get(f"/app/deadlines/{deadline_ref}")
    assert deadline_page.status_code == 200
    assert "Board memo delivery window" in deadline_page.text
    assert "Deadline window" in deadline_page.text
    assert "Update deadline state" in deadline_page.text

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
    assert "Update commitment state" in commitment_page.text
    assert "Reason code" in commitment_page.text
    assert "Due at" in commitment_page.text

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
    assert "Workspace plan" in plan_page.text

    usage_page = client.get("/app/settings/usage")
    assert usage_page.status_code == 200
    assert "Usage and activation" in usage_page.text
    assert "Success metrics" in usage_page.text
    assert "Draft approvals granted" in usage_page.text

    support_page = client.get("/app/settings/support")
    assert support_page.status_code == 200
    assert "Support and diagnostics" in support_page.text
    assert "Operational reliability" in support_page.text
    assert "Fix verification" in support_page.text
    assert "Support closure grounding" in support_page.text
    assert "Weekly pulse and journey-gate truth" in support_page.text
    assert "What the published release gate is saying" in support_page.text
    assert "Open bundle" in support_page.text

    outcomes_page = client.get("/app/settings/outcomes")
    assert outcomes_page.status_code == 200
    assert "Workspace outcomes" in outcomes_page.text
    assert "How quickly the workspace reached first value" in outcomes_page.text
    assert "How the daily loop is performing" in outcomes_page.text
    assert "How the recurring memo loop is proving itself" in outcomes_page.text
    assert "What the office-loop release gate would say right now" in outcomes_page.text
    assert "Blocked send follow-ups" in outcomes_page.text
    assert "Send follow-ups closed" in outcomes_page.text

    trust_page = client.get("/app/settings/trust")
    assert trust_page.status_code == 200
    assert "Workspace trust" in trust_page.text
    assert "Get help without guessing" in trust_page.text
    assert "What the assistant recently did" in trust_page.text
    assert "Evidence, rules, and retention" in trust_page.text
    assert plan_page.status_code == 200
    assert "Commercial boundary" in plan_page.text
    assert "What this workspace includes" in plan_page.text
    assert "Billing and renewal controls" in plan_page.text
    assert "Upgrade path" in plan_page.text

    usage_page = client.get("/app/settings/usage")
    assert usage_page.status_code == 200
    assert "Usage state" in usage_page.text
    assert "Product loop signals" in usage_page.text
    assert "Delivery reliability" in usage_page.text
    assert "Success metrics" in usage_page.text
    assert "Churn risk" in usage_page.text

    support_page = client.get("/app/settings/support")
    assert support_page.status_code == 200
    assert "Support bundle" in support_page.text
    assert "Pending review and recent decisions" in support_page.text
    assert "Operational reliability" in support_page.text
    assert "Commercial escalation" in support_page.text
    assert "Workspace health" in support_page.text
    assert "Runtime posture" in support_page.text
    assert "Provider risk" in support_page.text
    assert "Load score" in support_page.text

    channel_loop = client.get("/app/channel-loop")
    assert channel_loop.status_code == 200
    assert "Inline loop" in channel_loop.text
    assert "Approve now" in channel_loop.text
    assert "Morning memo digest" in channel_loop.text
    assert "Inline approvals" in channel_loop.text
    assert "Operator handoff digest" in channel_loop.text

    memo_digest = client.get("/app/channel-loop/memo")
    assert memo_digest.status_code == 200
    assert "Morning memo digest" in memo_digest.text
    assert "Support closure grounding" in memo_digest.text
    assert "Open memo" in memo_digest.text
    memo_plain = client.get("/app/channel-loop/memo/plain")
    assert memo_plain.status_code == 200
    assert "Morning memo digest" in memo_plain.text
    assert "Support closure grounding" in memo_plain.text
    assert "Open memo:" in memo_plain.text

    operator_digest = client.get("/app/channel-loop/operator")
    assert operator_digest.status_code == 200
    assert "Operator handoff digest" in operator_digest.text
    assert "Operator memo grounding" in operator_digest.text


def test_commitment_detail_form_can_schedule_commitment() -> None:
    principal_id = "exec-browser-commitment-detail-form"
    client = build_product_client(principal_id=principal_id)
    seeded = seed_product_state(client, principal_id=principal_id)

    commitment_ref = f"commitment:{seeded['commitment_id']}"
    detail_path = f"/app/commitment-items/{commitment_ref}"
    detail_page = client.get(detail_path)
    assert detail_page.status_code == 200
    assert "Update commitment state" in detail_page.text
    assert "Reason code" in detail_page.text
    assert "Due at" in detail_page.text

    updated = client.post(
        f"/app/actions/queue/{commitment_ref}/resolve",
        data={
            "action": "schedule",
            "reason_code": "board_review_booked",
            "reason": "Board review is booked for Friday morning.",
            "due_at": "2026-03-29T08:00:00+00:00",
            "return_to": detail_path,
        },
        follow_redirects=False,
    )
    assert updated.status_code == 303
    assert updated.headers["location"] == detail_path

    detail_after_update = client.get(detail_path)
    assert detail_after_update.status_code == 200
    assert "Resolution code" in detail_after_update.text
    assert "board_review_booked" in detail_after_update.text
    assert "Scheduled" in detail_after_update.text

    refreshed = client.get(f"/app/api/commitments/{commitment_ref}")
    assert refreshed.status_code == 200
    assert refreshed.json()["status"] == "scheduled"
    assert refreshed.json()["resolution_code"] == "board_review_booked"
    assert refreshed.json()["due_at"] == "2026-03-29T08:00:00+00:00"


def test_decision_detail_form_can_resolve_and_reopen_decision() -> None:
    principal_id = "exec-browser-decision-detail-form"
    client = build_product_client(principal_id=principal_id)
    seeded = seed_product_state(client, principal_id=principal_id)

    decision_ref = f"decision:{seeded['decision_window_id']}"
    detail_path = f"/app/decisions/{decision_ref}"
    detail_page = client.get(detail_path)
    assert detail_page.status_code == 200
    assert "Update decision state" in detail_page.text
    assert "Decision deadline" in detail_page.text

    resolved = client.post(
        f"/app/actions/queue/{decision_ref}/resolve",
        data={
            "action": "resolve",
            "reason": "Principal confirmed the operator owner.",
            "due_at": "2026-03-25T11:00:00+00:00",
            "return_to": detail_path,
        },
        follow_redirects=False,
    )
    assert resolved.status_code == 303
    assert resolved.headers["location"] == detail_path

    detail_after_resolve = client.get(detail_path)
    assert detail_after_resolve.status_code == 200
    assert "Principal confirmed the operator owner." in detail_after_resolve.text
    assert "Decided" in detail_after_resolve.text

    reopened = client.post(
        f"/app/actions/queue/{decision_ref}/resolve",
        data={
            "action": "reopen",
            "reason": "Board requested another operator pass.",
            "return_to": detail_path,
        },
        follow_redirects=False,
    )
    assert reopened.status_code == 303
    assert reopened.headers["location"] == detail_path

    detail_after_reopen = client.get(detail_path)
    assert detail_after_reopen.status_code == 200
    assert "Open" in detail_after_reopen.text
    assert "No explicit resolution note yet." in detail_after_reopen.text
    assert "Board requested another operator pass." in detail_after_reopen.text


def test_deadline_detail_form_can_resolve_and_reopen_deadline() -> None:
    principal_id = "exec-browser-deadline-detail-form"
    client = build_product_client(principal_id=principal_id)
    seeded = seed_product_state(client, principal_id=principal_id)

    deadline_ref = f"deadline:{seeded['deadline_window_id']}"
    detail_path = f"/app/deadlines/{deadline_ref}"
    detail_page = client.get(detail_path)
    assert detail_page.status_code == 200
    assert "Update deadline state" in detail_page.text
    assert "Window end" in detail_page.text

    resolved = client.post(
        f"/app/actions/queue/{deadline_ref}/resolve",
        data={
            "action": "resolve",
            "reason": "Delivery window was covered in the queue.",
            "due_at": "2026-03-25T15:00:00+00:00",
            "return_to": detail_path,
        },
        follow_redirects=False,
    )
    assert resolved.status_code == 303
    assert resolved.headers["location"] == detail_path

    detail_after_resolve = client.get(detail_path)
    assert detail_after_resolve.status_code == 200
    assert "Elapsed" in detail_after_resolve.text
    assert "Delivery window was covered in the queue." in detail_after_resolve.text

    reopened = client.post(
        f"/app/actions/queue/{deadline_ref}/resolve",
        data={
            "action": "reopen",
            "reason": "Board requested a later delivery window.",
            "due_at": "2026-03-26T15:00:00+00:00",
            "return_to": detail_path,
        },
        follow_redirects=False,
    )
    assert reopened.status_code == 303
    assert reopened.headers["location"] == detail_path

    detail_after_reopen = client.get(detail_path)
    assert detail_after_reopen.status_code == 200
    assert "Open" in detail_after_reopen.text
    assert "2026-03-26" in detail_after_reopen.text
    assert "Board requested a later delivery window." in detail_after_reopen.text


def test_morning_memo_issue_surfaces_reason_and_fix_target() -> None:
    principal_id = "exec-browser-memo-issue"
    client = build_product_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Memo Issue Office")
    updated = client.post(
        "/app/actions/settings/morning-memo",
        data={
            "return_to": "/app/settings",
            "enabled": "true",
            "cadence": "daily_morning",
            "recipient_email": "tibor@myexternalbrain.com",
            "delivery_time_local": "08:00",
            "quiet_hours_start": "20:00",
            "quiet_hours_end": "07:00",
        },
        follow_redirects=False,
    )
    assert updated.status_code == 303
    client.app.state.container.channel_runtime.ingest_observation(
        principal_id=principal_id,
        channel="product",
        event_type="scheduled_morning_memo_delivery_failed",
        payload={
            "schedule_key": "pref-memo-issue",
            "local_day": "2026-03-29",
            "email_delivery_status": "failed",
            "email_delivery_error": 'registration_email_send_failed:422:{"error":"Domain not verified"}',
        },
        source_id="pref-memo-issue",
        dedupe_key=f"{principal_id}|scheduled-memo-failed",
    )

    settings = client.get("/app/settings")
    assert settings.status_code == 200
    assert "Last memo issue" in settings.text
    assert "Domain not verified" in settings.text
    assert "/app/settings/support" not in settings.text

    outcomes_page = client.get("/app/settings/outcomes")
    assert outcomes_page.status_code == 200
    assert "Last memo issue" in outcomes_page.text
    assert "Domain not verified" in outcomes_page.text
    assert "Memo delivery blocker" in outcomes_page.text
    assert "Open support" in outcomes_page.text
    assert "/app/settings/support" in outcomes_page.text


def test_manual_memo_issue_surfaces_reason_and_fix_target_even_when_schedule_disabled() -> None:
    principal_id = "exec-browser-manual-memo-issue"
    client = build_product_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Manual Memo Issue Office")
    client.app.state.container.channel_runtime.ingest_observation(
        principal_id=principal_id,
        channel="product",
        event_type="channel_digest_delivery_email_failed",
        payload={
            "delivery_id": "memo-delivery-issue",
            "digest_key": "memo",
            "recipient_email": "tibor@myexternalbrain.com",
            "error": 'registration_email_send_failed:422:{"error":"Domain not verified"}',
        },
        source_id="memo-delivery-issue",
        dedupe_key=f"{principal_id}|manual-memo-failed",
    )

    settings = client.get("/app/settings")
    assert settings.status_code == 200
    assert "Last memo issue" in settings.text
    assert "Domain not verified" in settings.text
    assert "/app/settings/support" not in settings.text

    outcomes_page = client.get("/app/settings/outcomes")
    assert outcomes_page.status_code == 200
    assert "Last memo issue" in outcomes_page.text
    assert "Domain not verified" in outcomes_page.text
    assert "Open support" in outcomes_page.text
    assert "/app/settings/support" in outcomes_page.text


def test_operator_admin_office_page_centers_the_operator_lane() -> None:
    principal_id = "exec-browser-admin-office"
    client = build_operator_product_client(principal_id=principal_id, operator_id="operator-office")
    seeded = seed_product_state(client, principal_id=principal_id)
    closed = client.post(
        f"/app/api/queue/commitment:{seeded['commitment_id']}/resolve",
        json={"action": "close", "reason": "Board packet sent from the operator lane."},
    )
    assert closed.status_code == 200

    office = client.get("/admin/office")
    assert office.status_code == 200
    assert "Office" in office.text
    assert "What the office control surface is carrying right now" in office.text
    assert "What the operator should do next" in office.text
    assert "What already belongs to this operator lane" in office.text
    assert "What can be claimed next" in office.text
    assert "Access, delivery, and Google posture" in office.text
    assert "Prepare board follow-up handoff" in office.text
    assert "Google sync freshness" in office.text
    assert "What just moved through the operator lane" in office.text
    assert "Send board materials" in office.text
    assert "Reopen" in office.text

    redirected = client.get("/app/activity", follow_redirects=False)
    assert redirected.status_code == 303
    assert redirected.headers["location"] == "/admin/office"


def test_support_page_explains_current_memo_issue_and_fix_detail() -> None:
    principal_id = "exec-browser-support-memo-issue"
    client = build_product_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Support Memo Issue Office")
    client.app.state.container.channel_runtime.ingest_observation(
        principal_id=principal_id,
        channel="product",
        event_type="channel_digest_delivery_email_failed",
        payload={
            "delivery_id": "memo-delivery-issue",
            "digest_key": "memo",
            "recipient_email": "tibor@myexternalbrain.com",
            "error": 'registration_email_send_failed:422:{"error":"Domain not verified"}',
        },
        source_id="memo-delivery-issue",
        dedupe_key=f"{principal_id}|manual-memo-failed",
    )

    support_page = client.get("/app/settings/support")
    assert support_page.status_code == 200
    assert "Last memo issue" in support_page.text
    assert "Domain not verified" in support_page.text
    assert "Memo fix detail" in support_page.text
    assert "Verify the sending domain in the email provider before the next memo cycle." in support_page.text
    assert "Memo fix target" in support_page.text
    assert "Open support" in support_page.text


def test_channel_loop_memo_digest_surfaces_memo_issue_fix_action() -> None:
    principal_id = "exec-browser-channel-loop-memo-issue"
    client = build_product_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Channel Loop Memo Issue Office")
    client.app.state.container.channel_runtime.ingest_observation(
        principal_id=principal_id,
        channel="product",
        event_type="channel_digest_delivery_email_failed",
        payload={
            "delivery_id": "memo-delivery-issue",
            "digest_key": "memo",
            "recipient_email": "tibor@myexternalbrain.com",
            "error": 'registration_email_send_failed:422:{"error":"Domain not verified"}',
        },
        source_id="memo-delivery-issue",
        dedupe_key=f"{principal_id}|manual-memo-failed",
    )

    loop_page = client.get("/app/channel-loop")
    assert loop_page.status_code == 200
    assert "Fix memo delivery blocker" in loop_page.text
    assert "Domain not verified" in loop_page.text
    assert "Open support" in loop_page.text

    memo_digest = client.get("/app/channel-loop/memo")
    assert memo_digest.status_code == 200
    assert "Fix memo delivery blocker" in memo_digest.text
    assert "Domain not verified" in memo_digest.text
    assert "Open support" in memo_digest.text


def test_channel_loop_get_actions_work() -> None:
    principal_id = "exec-browser-channel-loop"
    client = build_product_client(principal_id=principal_id)
    seeded = seed_product_state(client, principal_id=principal_id)

    signal = client.post(
        "/app/api/signals/ingest",
        json={
            "signal_type": "email_thread",
            "channel": "gmail",
            "title": "Board packet follow-up",
            "summary": "Send revised board packet to Sofia by EOD.",
            "text": "Send revised board packet to Sofia by EOD.",
            "counterparty": "Sofia N.",
            "source_ref": "gmail-thread:browser-inline-1",
            "external_id": "gmail-message:browser-inline-1",
        },
    )
    assert signal.status_code == 200

    loop_page = client.get("/app/channel-loop")
    assert loop_page.status_code == 200
    assert "Inline loop" in loop_page.text
    assert "Resolve now" in loop_page.text

    approvals_page = client.get("/app/channel-loop/approvals")
    assert approvals_page.status_code == 200
    assert "Inline approvals" in approvals_page.text
    assert "Approve draft for Sofia N." in approvals_page.text
    assert "Revised board packet to Sofia" not in approvals_page.text

    loop_payload = client.get("/app/api/channel-loop")
    assert loop_payload.status_code == 200
    approvals_digest = next(item for item in loop_payload.json()["digests"] if item["key"] == "approvals")
    assert all("board packet" not in item["title"].lower() for item in approvals_digest["items"] if item["tag"] == "Candidate")
    drafts_before = client.get("/app/api/drafts")
    assert drafts_before.status_code == 200
    draft_count_before = len(drafts_before.json())
    approved_href = next(item["action_href"] for item in approvals_digest["items"] if item["tag"] == "Draft")
    approved = client.get(approved_href, follow_redirects=False)
    assert approved.status_code == 303
    assert approved.headers["location"] == "/app/channel-loop/approvals"
    drafts_after = client.get("/app/api/drafts")
    assert drafts_after.status_code == 200
    assert len(drafts_after.json()) == draft_count_before - 1

    pending_candidates = client.get("/app/api/commitments/candidates", params={"status": "pending"})
    assert pending_candidates.status_code == 200
    assert "board packet" not in pending_candidates.text.lower()

    refreshed_approvals = next(item for item in client.get("/app/api/channel-loop").json()["digests"] if item["key"] == "approvals")
    assert all("board packet" not in item["title"].lower() for item in refreshed_approvals["items"] if item["tag"] == "Candidate")

    memo_digest = next(item for item in loop_payload.json()["digests"] if item["key"] == "memo")
    closed_href = next(item["action_href"] for item in memo_digest["items"] if item["tag"] == "Commitment")
    closed = client.get(closed_href, follow_redirects=False)
    assert closed.status_code == 303
    assert closed.headers["location"] == "/app/channel-loop/memo"
    assert "Send board materials" not in client.get("/app/inbox").text

    refreshed_loop = client.get("/app/api/channel-loop")
    approvals_after_commitment = next(item for item in refreshed_loop.json()["digests"] if item["key"] == "approvals")
    decision_href = next(item["action_href"] for item in approvals_after_commitment["items"] if item["tag"] == "Decision")
    decision_resolved = client.get(decision_href, follow_redirects=False)
    assert decision_resolved.status_code == 303
    assert decision_resolved.headers["location"] == "/app/channel-loop/approvals"
    decision_detail = client.get(f"/app/api/decisions/decision:{seeded['decision_window_id']}")
    assert decision_detail.status_code == 200
    assert decision_detail.json()["status"] == "decided"


def test_signal_reply_drafts_can_be_rejected_from_inline_channel_loop() -> None:
    principal_id = "exec-browser-signal-draft-reject"
    client = build_product_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Signal Draft Office")

    signal = client.post(
        "/app/api/signals/ingest",
        json={
            "signal_type": "email_thread",
            "channel": "gmail",
            "title": "Board packet follow-up",
            "summary": "Send revised board packet to Sofia by EOD.",
            "text": "Send revised board packet to Sofia by EOD.",
            "counterparty": "Sofia N.",
            "source_ref": "gmail-thread:browser-inline-reject",
            "external_id": "gmail-message:browser-inline-reject",
            "payload": {"from_email": "sofia@example.com", "from_name": "Sofia N."},
        },
    )
    assert signal.status_code == 200
    draft_id = signal.json()["staged_drafts"][0]["id"]

    approvals_page = client.get("/app/channel-loop/approvals")
    assert approvals_page.status_code == 200
    assert "Approve draft for Sofia N." in approvals_page.text
    assert "Reject" in approvals_page.text

    loop_payload = client.get("/app/api/channel-loop")
    assert loop_payload.status_code == 200
    approvals_digest = next(item for item in loop_payload.json()["digests"] if item["key"] == "approvals")
    reject_href = next(
        item["secondary_action_href"]
        for item in approvals_digest["items"]
        if item["tag"] == "Draft" and "Sofia N." in item["title"]
    )
    rejected = client.get(reject_href, follow_redirects=False)
    assert rejected.status_code == 303
    assert rejected.headers["location"] == "/app/channel-loop/approvals"
    assert draft_id not in client.get("/app/api/drafts").text


def test_workspace_access_and_channel_delivery_routes_issue_session_cookie() -> None:
    principal_id = "exec-browser-workspace-access"
    client = build_product_client(principal_id=principal_id)
    start_workspace(client, mode="team", workspace_name="Browser Access Office")
    seeded = seed_product_state(client, principal_id=principal_id)

    invite = client.post(
        "/app/api/invitations",
        json={
            "email": "ops-route@example.com",
            "role": "operator",
            "display_name": "Route Operator",
        },
    )
    assert invite.status_code == 200
    accepted = client.post("/app/api/invitations/accept", json={"token": invite.json()["invite_token"]})
    assert accepted.status_code == 200

    client.headers.pop("X-EA-Principal-ID", None)
    access = client.get(accepted.json()["access_url"], follow_redirects=False)
    assert access.status_code == 303
    assert access.headers["location"] == "/admin/office"
    assert "ea_workspace_session=" in str(access.headers.get("set-cookie") or "")
    session_queue = client.get("/app/api/queue")
    assert session_queue.status_code == 200
    assert any(item["id"] == f"approval:{seeded['approval_id']}" for item in session_queue.json()["items"])

    delivery = client.post(
        "/app/api/channel-loop/memo/deliveries",
        json={
            "recipient_email": "ops-route@example.com",
            "role": "operator",
            "display_name": "Route Operator",
            "operator_id": "operator-ops-route",
        },
    )
    assert delivery.status_code == 200
    opened = client.get(delivery.json()["delivery_url"], follow_redirects=False)
    assert opened.status_code == 303
    assert opened.headers["location"] == "/app/channel-loop/memo"
    assert "ea_workspace_session=" in str(opened.headers.get("set-cookie") or "")

    session_issue = client.post(
        "/app/api/access-sessions",
        json={"email": "principal@example.com", "role": "principal", "display_name": "Principal Browser Access"},
    )
    assert session_issue.status_code == 200
    session_body = session_issue.json()
    revoked = client.post(f"/app/api/access-sessions/{session_body['session_id']}/revoke")
    assert revoked.status_code == 200

    client.headers.pop("X-EA-Principal-ID", None)
    blocked = client.get(session_body["access_url"], follow_redirects=False)
    assert blocked.status_code == 404


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


def test_browser_settings_access_and_invitation_pages_render_live_workspace_state() -> None:
    principal_id = "exec-browser-access-settings"
    client = build_product_client(principal_id=principal_id)
    start_workspace(client, mode="personal")

    invite = client.post(
        "/app/api/invitations",
        json={"email": "operator@example.com", "role": "operator", "display_name": "Operator One"},
    )
    assert invite.status_code == 200

    access_session = client.post(
        "/app/api/access-sessions",
        json={"email": "principal@example.com", "role": "principal", "display_name": "Principal Access"},
    )
    assert access_session.status_code == 200

    invitations_page = client.get("/app/settings/invitations")
    assert invitations_page.status_code == 200
    assert "Workspace invitations" in invitations_page.text
    assert "Invites waiting for acceptance" in invitations_page.text
    assert "operator@example.com" in invitations_page.text

    access_page = client.get("/app/settings/access")
    assert access_page.status_code == 200
    assert "Workspace access" in access_page.text
    assert "Live workspace access links" in access_page.text
    assert "principal@example.com" in access_page.text


def test_browser_rules_page_can_update_morning_memo_schedule() -> None:
    principal_id = "exec-browser-memo-rules"
    client = build_product_client(principal_id=principal_id)
    start_workspace(client, mode="personal")
    seed_product_state(client, principal_id=principal_id)

    updated = client.post(
        "/app/actions/settings/morning-memo",
        data={
            "workspace_name": "Office Rules Lab",
            "language": "en",
            "timezone": "Europe/Vienna",
            "enabled": "true",
            "cadence": "weekdays_morning",
            "recipient_email": "briefs@example.com",
            "delivery_time_local": "07:30",
            "quiet_hours_start": "21:00",
            "quiet_hours_end": "06:30",
            "return_to": "/app/settings",
        },
        follow_redirects=False,
    )
    assert updated.status_code == 303
    assert updated.headers["location"] == "/app/settings"

    settings = client.get("/app/settings")
    assert settings.status_code == 200
    assert "Update workspace and morning memo rules" in settings.text
    assert "Office Rules Lab" in settings.text
    assert "Europe/Vienna" in settings.text
    assert "briefs@example.com" in settings.text
    assert "07:30" in settings.text

    status = client.get("/v1/onboarding/status")
    assert status.status_code == 200
    workspace = status.json()["workspace"]
    assert workspace["name"] == "Office Rules Lab"
    assert workspace["language"] == "en"
    assert workspace["timezone"] == "Europe/Vienna"
    memo = status.json()["delivery_preferences"]["morning_memo"]
    assert memo["enabled"] is True
    assert memo["cadence"] == "weekdays_morning"
    assert memo["delivery_time_local"] == "07:30"
    assert memo["quiet_hours_start"] == "21:00"
    assert memo["quiet_hours_end"] == "06:30"
    assert memo["recipient_email"] == "briefs@example.com"


def test_browser_google_settings_page_and_run_now_action_work() -> None:
    principal_id = "exec-browser-google-settings"
    client = build_product_client(principal_id=principal_id)
    seed_product_state(client, principal_id=principal_id)

    sync_page = client.get("/app/settings/google")
    assert sync_page.status_code == 200
    assert "Google sync" in sync_page.text
    assert "Latest sync run and queued follow-up work" in sync_page.text

    triggered = client.get("/app/actions/signals/google/sync?return_to=/app/settings/google", follow_redirects=False)
    assert triggered.status_code == 303
    assert triggered.headers["location"].startswith("/app/settings/google")
