from __future__ import annotations

from tests.product_test_helpers import build_operator_product_client, build_product_client, seed_product_state, start_workspace


def test_product_api_projects_real_runtime_objects() -> None:
    principal_id = "exec-product-api"
    client = build_product_client(principal_id=principal_id)
    seeded = seed_product_state(client, principal_id=principal_id)

    brief = client.get("/app/api/brief")
    assert brief.status_code == 200
    brief_body = brief.json()
    assert brief_body["total"] >= 1
    assert any(item["title"] == "Send board materials" for item in brief_body["items"])
    commitment_brief = next(item for item in brief_body["items"] if item["title"] == "Send board materials")
    assert commitment_brief["object_ref"] == f"commitment:{seeded['commitment_id']}"
    assert commitment_brief["evidence_count"] >= 1
    assert commitment_brief["confidence"] > 0

    queue = client.get("/app/api/queue")
    assert queue.status_code == 200
    queue_body = queue.json()
    assert queue_body["total"] >= 3
    assert any(item["id"] == f"approval:{seeded['approval_id']}" for item in queue_body["items"])
    assert any(item["id"] == f"commitment:{seeded['commitment_id']}" for item in queue_body["items"])

    decisions = client.get("/app/api/decisions")
    assert decisions.status_code == 200
    decisions_body = decisions.json()
    assert decisions_body["total"] >= 1
    assert any(item["id"] == f"decision:{seeded['decision_window_id']}" for item in decisions_body["items"])
    decision_detail = client.get(f"/app/api/decisions/decision:{seeded['decision_window_id']}")
    assert decision_detail.status_code == 200
    assert decision_detail.json()["title"] == "Choose board memo owner"
    assert decision_detail.json()["decision_type"] == "owner_assignment"
    assert decision_detail.json()["next_action"]
    assert seeded["session_id"] in decision_detail.json()["linked_thread_ids"]
    assert decision_detail.json()["impact_summary"]
    assert decision_detail.json()["sla_status"] in {"due_now", "due_soon", "on_track", "unscheduled", "resolved"}

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

    threads = client.get("/app/api/threads")
    assert threads.status_code == 200
    threads_body = threads.json()
    assert threads_body["total"] >= 1
    assert any(item["title"] == "sofia@example.com" for item in threads_body["items"])
    thread_ref = threads_body["items"][0]["id"]
    thread_detail = client.get(f"/app/api/threads/{thread_ref}")
    assert thread_detail.status_code == 200
    assert thread_detail.json()["channel"] == "email"

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

    evidence = client.get("/app/api/evidence")
    assert evidence.status_code == 200
    evidence_body = evidence.json()
    assert evidence_body["total"] >= 1
    evidence_detail = client.get(f"/app/api/evidence/{evidence_body['items'][0]['id']}")
    assert evidence_detail.status_code == 200

    rules = client.get("/app/api/rules")
    assert rules.status_code == 200
    rules_body = rules.json()
    assert rules_body["total"] >= 4
    assert any(item["id"] == "rule:draft_approval" for item in rules_body["items"])
    simulated = client.post("/app/api/rules/rule:messaging_scope/simulate", json={"proposed_value": "telegram"})
    assert simulated.status_code == 200
    assert "Upgrade" in simulated.json()["simulated_effect"]

    diagnostics = client.get("/app/api/diagnostics")
    assert diagnostics.status_code == 200
    diagnostics_body = diagnostics.json()
    assert diagnostics_body["workspace"]["mode"] == "personal"
    assert diagnostics_body["plan"]["plan_key"] == "pilot"
    assert diagnostics_body["billing"]["billing_state"] == "trial"
    assert diagnostics_body["billing"]["support_tier"] == "guided"
    assert diagnostics_body["billing"]["invoice_status"] in {"trial_active", "current", "upgrade_required"}
    assert diagnostics_body["billing"]["billing_portal_path"]
    assert diagnostics_body["entitlements"]["principal_seats"] == 1
    assert "warnings" in diagnostics_body["commercial"]
    assert "blocked_actions" in diagnostics_body["commercial"]
    assert "blocked_action_message" in diagnostics_body["commercial"]
    assert "upgrade_path_label" in diagnostics_body["commercial"]
    assert "recommended_plan_key" in diagnostics_body["commercial"]
    assert diagnostics_body["usage"]["queue_items"] >= 1
    assert "risk_state" in diagnostics_body["providers"]
    assert "lanes_with_fallback" in diagnostics_body["providers"]
    assert "load_score" in diagnostics_body["queue_health"]
    assert "retrying_delivery" in diagnostics_body["queue_health"]

    plan = client.get("/app/api/plan")
    assert plan.status_code == 200
    plan_body = plan.json()
    assert plan_body["plan"]["plan_key"] == "pilot"
    assert plan_body["billing"]["support_tier"] == "guided"
    assert plan_body["billing"]["invoice_window_label"]
    assert plan_body["billing"]["billing_portal_state"]
    assert plan_body["entitlements"]["operator_seats"] == 1
    assert "blocked_action_message" in plan_body["commercial"]

    usage = client.get("/app/api/usage")
    assert usage.status_code == 200
    usage_body = usage.json()
    assert usage_body["usage"]["queue_items"] >= 1
    assert "counts" in usage_body["analytics"]
    assert int(dict(usage_body["analytics"]["counts"]).get("usage_opened") or 0) >= 1
    assert "churn_risk" in usage_body["analytics"]
    assert "commitment_close_rate" in usage_body["analytics"]

    support = client.get("/app/api/support")
    assert support.status_code == 200
    support_body = support.json()
    assert support_body["plan"]["display_name"] == "Pilot"
    assert support_body["billing"]["invoice_status"] in {"trial_active", "current", "upgrade_required"}
    assert "pending" in support_body["approvals"]
    assert isinstance(support_body["human_tasks"], list)
    assert "risk_state" in support_body["providers"]
    assert "load_score" in support_body["queue_health"]
    assert "blocked_action_message" in support_body["commercial"]
    assert "success_summary" in support_body["analytics"]

    channel_loop = client.get("/app/api/channel-loop")
    assert channel_loop.status_code == 200
    channel_loop_body = channel_loop.json()
    assert channel_loop_body["headline"] == "Inline loop"
    assert any(item["action_label"] == "Approve now" for item in channel_loop_body["items"])
    assert any("/app/channel-actions/" in item.get("action_href", "") for item in channel_loop_body["items"])
    digests = {item["key"]: item for item in channel_loop_body["digests"]}
    assert {"memo", "approvals", "operator"} <= set(digests)
    assert digests["memo"]["preview_text"]
    assert any(item["action_label"] == "Approve now" for item in digests["approvals"]["items"])
    assert any(item["tag"] == "Handoff" for item in digests["operator"]["items"])
    memo_plain = client.get("/app/api/channel-loop/memo/plain")
    assert memo_plain.status_code == 200
    assert "Morning memo digest" in memo_plain.text
    assert "/app/channel-actions/" in memo_plain.text

    webhook = client.post(
        "/app/api/webhooks",
        json={
            "label": "Office sink",
            "target_url": "https://example.invalid/office-hook",
            "event_types": ["office_signal_email_thread", "workspace_search_performed"],
        },
    )
    assert webhook.status_code == 200
    webhook_body = webhook.json()
    assert webhook_body["label"] == "Office sink"
    assert webhook_body["target_url"] == "https://example.invalid/office-hook"
    webhook_id = webhook_body["webhook_id"]

    webhooks = client.get("/app/api/webhooks")
    assert webhooks.status_code == 200
    assert any(item["webhook_id"] == webhook_id for item in webhooks.json()["items"])

    signal = client.post(
        "/app/api/signals/ingest",
        json={
            "signal_type": "email_thread",
            "channel": "gmail",
            "title": "Investor follow-up",
            "summary": "Send the revised board packet to Sofia tomorrow morning.",
            "counterparty": "Sofia N.",
            "source_ref": "gmail-thread-123",
            "external_id": "gmail-msg-123",
        },
    )
    assert signal.status_code == 200
    signal_body = signal.json()
    assert signal_body["channel"] == "gmail"
    assert signal_body["event_type"] == "office_signal_email_thread"
    assert signal_body["staged_count"] >= 1

    events = client.get("/app/api/events")
    assert events.status_code == 200
    events_body = events.json()
    assert events_body["total"] >= 1
    assert any(item["event_type"] == "office_signal_email_thread" for item in events_body["items"])
    assert any(item["source_id"] == "gmail-thread-123" for item in events_body["items"])
    gmail_events = client.get("/app/api/events", params={"channel": "gmail"})
    assert gmail_events.status_code == 200
    assert all(item["channel"] == "gmail" for item in gmail_events.json()["items"])

    deliveries = client.get("/app/api/webhooks/deliveries", params={"webhook_id": webhook_id})
    assert deliveries.status_code == 200
    deliveries_body = deliveries.json()
    assert deliveries_body["total"] >= 1
    assert any(item["matched_event_type"] == "office_signal_email_thread" for item in deliveries_body["items"])
    assert any(item["webhook_id"] == webhook_id for item in deliveries_body["items"])

    search = client.get("/app/api/search", params={"query": "Sofia"})
    assert search.status_code == 200
    search_body = search.json()
    assert search_body["total"] >= 2
    assert any(item["kind"] == "person" and item["title"] == "Sofia N." for item in search_body["items"])
    assert any(item["kind"] == "thread" and item["title"] == "sofia@example.com" for item in search_body["items"])
    assert all(item["score"] > 0 for item in search_body["items"])

    board_search = client.get("/app/api/search", params={"query": "board", "limit": 5})
    assert board_search.status_code == 200
    board_body = board_search.json()
    assert board_body["total"] >= 2
    assert any(item["kind"] == "decision" for item in board_body["items"])
    assert any(item["kind"] == "commitment" for item in board_body["items"])
    assert all(item["href"] for item in board_body["items"])

    webhook_test = client.post(f"/app/api/webhooks/{webhook_id}/test")
    assert webhook_test.status_code == 200
    assert webhook_test.json()["webhook"]["webhook_id"] == webhook_id
    assert webhook_test.json()["delivery"]["delivery_kind"] == "test"

    draft_action = next(item["action_href"] for item in channel_loop_body["items"] if item["tag"] == "Draft")
    redeemed = client.get(draft_action, follow_redirects=False)
    assert redeemed.status_code == 303
    assert redeemed.headers["location"] == "/app/channel-loop"
    assert f"approval:{seeded['approval_id']}" not in client.get("/app/api/drafts").text

    diagnostics_after_channel_action = client.get("/app/api/diagnostics")
    assert diagnostics_after_channel_action.status_code == 200
    assert int(dict(diagnostics_after_channel_action.json()["analytics"]["counts"]).get("channel_action_redeemed") or 0) >= 1


def test_product_commitment_detail_and_queue_resolution() -> None:
    principal_id = "exec-product-resolve"
    client = build_product_client(principal_id=principal_id)
    seeded = seed_product_state(client, principal_id=principal_id)
    commitment_ref = f"commitment:{seeded['commitment_id']}"

    detail = client.get(f"/app/api/commitments/{commitment_ref}")
    assert detail.status_code == 200
    assert detail.json()["statement"] == "Send board materials"
    assert detail.json()["channel_hint"] == "email"

    resolved = client.post(
        f"/app/api/queue/{commitment_ref}/resolve",
        json={"action": "close", "reason": "Materials sent", "reason_code": "sent"},
    )
    assert resolved.status_code == 200
    assert resolved.json()["resolution_state"] == "completed"

    updated = client.get(f"/app/api/commitments/{commitment_ref}")
    assert updated.status_code == 200
    assert updated.json()["status"] == "completed"
    assert updated.json()["resolution_code"] == "sent"
    assert updated.json()["resolution_reason"] == "Materials sent"
    history = client.get(f"/app/api/commitments/{commitment_ref}/history")
    assert history.status_code == 200
    assert any(row["event_type"] == "commitment_closed" for row in history.json())

    reopened = client.post(
        f"/app/api/commitments/{commitment_ref}/resolve",
        json={"action": "reopen", "reason": "Board asked for another revision"},
    )
    assert reopened.status_code == 200
    assert reopened.json()["status"] == "open"
    assert reopened.json()["resolution_code"] == ""

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
        f"/app/api/decisions/decision:{seeded['decision_window_id']}/resolve",
        json={"action": "resolve", "reason": "Principal chose the owner"},
    )
    assert decision_resolved.status_code == 200
    assert decision_resolved.json()["status"] == "decided"
    assert decision_resolved.json()["resolution_reason"] == "Principal chose the owner"
    assert decision_resolved.json()["sla_status"] == "resolved"

    decision_reopened = client.post(
        f"/app/api/decisions/decision:{seeded['decision_window_id']}/resolve",
        json={"action": "reopen", "reason": "Need another pass with the operator"},
    )
    assert decision_reopened.status_code == 200
    assert decision_reopened.json()["status"] == "open"
    assert decision_reopened.json()["resolution_reason"] == ""
    decision_history = client.get(f"/app/api/decisions/decision:{seeded['decision_window_id']}/history")
    assert decision_history.status_code == 200
    assert any(row["event_type"] == "decision_resolved" for row in decision_history.json())
    assert any(row["event_type"] == "decision_reopened" for row in decision_history.json())

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
    assert all(row["status"] in {"pending", "duplicate"} for row in listed.json())

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


def test_commitment_duplicate_detection_and_merge_acceptance() -> None:
    principal_id = "exec-product-commitment-duplicates"
    client = build_product_client(principal_id=principal_id)
    seeded = seed_product_state(client, principal_id=principal_id)
    commitment_ref = f"commitment:{seeded['commitment_id']}"

    staged = client.post(
        "/app/api/commitments/candidates/stage",
        json={
            "text": "Please send board materials to Sofia tomorrow.",
            "counterparty": "Sofia N.",
        },
    )
    assert staged.status_code == 200
    staged_body = staged.json()
    assert staged_body
    duplicate = next(row for row in staged_body if row["duplicate_of_ref"] == commitment_ref)
    assert duplicate["status"] == "duplicate"
    assert duplicate["duplicate_of_ref"] == commitment_ref
    assert duplicate["merge_strategy"] == "merge"

    duplicate_list = client.get("/app/api/commitments/candidates", params={"status": "duplicate"})
    assert duplicate_list.status_code == 200
    assert any(row["candidate_id"] == duplicate["candidate_id"] for row in duplicate_list.json())

    merged = client.post(
        f"/app/api/commitments/candidates/{duplicate['candidate_id']}/accept",
        json={"reviewer": "operator-office"},
    )
    assert merged.status_code == 200
    merged_body = merged.json()
    assert merged_body["id"] == commitment_ref
    assert duplicate["candidate_id"] in merged_body["merged_from_refs"]


def test_commitment_defer_and_follow_up_reopen_preserve_reason_codes() -> None:
    principal_id = "exec-product-commitment-lifecycle"
    client = build_product_client(principal_id=principal_id)
    seeded = seed_product_state(client, principal_id=principal_id)

    deferred = client.post(
        f"/app/api/commitments/commitment:{seeded['commitment_id']}/resolve",
        json={
            "action": "defer",
            "reason": "Waiting for final finance inputs",
            "reason_code": "waiting_on_dependency",
            "due_at": "2026-03-27T09:30:00+00:00",
        },
    )
    assert deferred.status_code == 200
    assert deferred.json()["status"] == "open"
    assert deferred.json()["resolution_code"] == "waiting_on_dependency"
    assert deferred.json()["due_at"] == "2026-03-27T09:30:00+00:00"

    dropped = client.post(
        f"/app/api/commitments/follow_up:{seeded['follow_up_id']}/resolve",
        json={"action": "drop", "reason": "Meeting cancelled", "reason_code": "cancelled_event"},
    )
    assert dropped.status_code == 200
    assert dropped.json()["status"] == "dropped"
    assert dropped.json()["resolution_code"] == "cancelled_event"

    reopened = client.post(
        f"/app/api/commitments/follow_up:{seeded['follow_up_id']}/resolve",
        json={"action": "reopen", "reason": "Investor asked to reschedule"},
    )
    assert reopened.status_code == 200
    assert reopened.json()["status"] == "open"
    assert reopened.json()["resolution_code"] == ""


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


def test_workspace_invitation_lifecycle_is_seat_aware() -> None:
    principal_id = "exec-workspace-invites"
    client = build_product_client(principal_id=principal_id)
    start_workspace(client, mode="team", workspace_name="Executive Office")
    seed_product_state(client, principal_id=principal_id)

    created = client.post(
        "/app/api/invitations",
        json={
            "email": "ops-partner@example.com",
            "role": "operator",
            "display_name": "Ops Partner",
            "note": "Board prep backup.",
            "expires_in_days": 7,
        },
    )
    assert created.status_code == 200
    invite = created.json()
    assert invite["status"] == "pending"
    assert invite["invite_url"].startswith("/workspace-invites/")
    assert invite["invite_token"]

    listed = client.get("/app/api/invitations")
    assert listed.status_code == 200
    assert any(item["invitation_id"] == invite["invitation_id"] for item in listed.json()["items"])

    preview = client.get(invite["invite_url"])
    assert preview.status_code == 200
    assert "workspace invitation" in preview.text.lower()

    accepted = client.post("/app/api/invitations/accept", json={"token": invite["invite_token"]})
    assert accepted.status_code == 200
    accepted_body = accepted.json()
    assert accepted_body["status"] == "accepted"
    assert accepted_body["accepted_by"]

    diagnostics = client.get("/app/api/diagnostics")
    assert diagnostics.status_code == 200
    assert int(diagnostics.json()["operators"]["seats_used"]) == 2
    assert int(diagnostics.json()["operators"]["seats_remaining"]) == 0

    revoked = client.post(f"/app/api/invitations/{invite['invitation_id']}/revoke")
    assert revoked.status_code == 200
    assert revoked.json()["status"] == "revoked"
    assert revoked.json()["invitation_id"] == invite["invitation_id"]
