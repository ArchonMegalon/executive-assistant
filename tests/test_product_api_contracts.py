from __future__ import annotations

from app.product.service import ProductService
from app.services import google_oauth as google_oauth_service
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
    assert "reliability" in usage_body["analytics"]
    assert "delivery_reliability_state" in usage_body["analytics"]["reliability"]
    assert "sync" in usage_body["analytics"]
    assert "google_sync_freshness_state" in usage_body["analytics"]["sync"]
    assert "pending_commitment_candidates" in usage_body["analytics"]["sync"]
    outcomes = client.get("/app/api/outcomes")
    assert outcomes.status_code == 200
    outcomes_body = outcomes.json()
    assert "memo_open_rate" in outcomes_body
    assert "approval_action_rate" in outcomes_body
    assert "commitment_close_rate" in outcomes_body
    assert "memo_loop" in outcomes_body
    assert "office_loop_proof" in outcomes_body
    assert "counts" in outcomes_body
    trust = client.get("/app/api/trust")
    assert trust.status_code == 200
    trust_body = trust.json()
    assert "workspace_summary" in trust_body
    assert "provider_posture" in trust_body
    assert "reliability" in trust_body

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
    assert "reliability" in support_body["analytics"]
    assert "sync_reliability_state" in support_body["analytics"]["reliability"]
    assert "sync" in support_body["analytics"]
    assert "google_token_status" in support_body["analytics"]["sync"]

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
    assert any(item["kind"] == "draft" for item in search_body["items"])
    assert all(item["score"] > 0 for item in search_body["items"])

    board_search = client.get("/app/api/search", params={"query": "board", "limit": 5})
    assert board_search.status_code == 200
    board_body = board_search.json()
    assert board_body["total"] >= 2
    assert any(item["kind"] == "decision" for item in board_body["items"])
    assert any(item["kind"] == "commitment" for item in board_body["items"])
    assert any(item["kind"] == "handoff" for item in board_body["items"])
    assert all(item["href"] for item in board_body["items"])
    decision_result = next(item for item in board_body["items"] if item["kind"] == "decision")
    assert decision_result["action_label"] in {"Resolve", "Review"}
    assert decision_result["action_href"].startswith("/app/actions/queue/")
    commitment_result = next(item for item in board_body["items"] if item["kind"] == "commitment")
    assert commitment_result["action_label"] in {"Close", "Reopen", "Review"}
    assert commitment_result["action_href"].startswith("/app/actions/queue/")

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


def test_google_signal_sync_ingests_recent_gmail_and_calendar_activity(monkeypatch) -> None:
    principal_id = "exec-product-google-sync"
    client = build_product_client(principal_id=principal_id)
    seeded = seed_product_state(client, principal_id=principal_id)

    monkeypatch.setattr(
        google_oauth_service,
        "list_recent_workspace_signals",
        lambda **_: google_oauth_service.GoogleWorkspaceSignalSync(
            account_email="exec@example.com",
            granted_scopes=(
                google_oauth_service.GOOGLE_SCOPE_METADATA,
                google_oauth_service.GOOGLE_SCOPE_CALENDAR_READONLY,
            ),
            signals=(
                google_oauth_service.GoogleWorkspaceSignal(
                    signal_type="email_thread",
                    channel="gmail",
                    title="Investor follow-up",
                    summary="Send the revised board packet to Sofia tomorrow morning.",
                    text="Send the revised board packet to Sofia tomorrow morning.",
                    source_ref="gmail-thread:abc123",
                    external_id="gmail-message:def456",
                    counterparty="Sofia N.",
                    due_at=None,
                    payload={"thread_id": "abc123", "message_id": "def456"},
                ),
                google_oauth_service.GoogleWorkspaceSignal(
                    signal_type="calendar_note",
                    channel="calendar",
                    title="Board prep",
                    summary="Starts 2026-03-28T09:00:00+00:00",
                    text="Board prep with Sofia N. before the memo review.",
                    source_ref="calendar-event:prep-1",
                    external_id="calendar-event:prep-1",
                    counterparty="Sofia N.",
                    due_at="2026-03-28T09:00:00+00:00",
                    payload={"event_id": "prep-1"},
                ),
            ),
        ),
    )

    synced = client.post("/app/api/signals/google/sync", params={"email_limit": 2, "calendar_limit": 2})
    assert synced.status_code == 200
    body = synced.json()
    assert body["account_email"] == "exec@example.com"
    assert body["total"] == 2
    assert body["synced_total"] == 2
    assert body["deduplicated_total"] == 0
    assert {item["channel"] for item in body["items"]} == {"gmail", "calendar"}
    assert any(item["event_type"] == "office_signal_email_thread" and item["staged_count"] >= 1 for item in body["items"])
    assert all(item["deduplicated"] is False for item in body["items"])

    events = client.get("/app/api/events")
    assert events.status_code == 200
    event_types = {item["event_type"] for item in events.json()["items"]}
    assert "office_signal_email_thread" in event_types

    candidates = client.get("/app/api/commitments/candidates")
    assert candidates.status_code == 200
    candidates_body = candidates.json()
    gmail_candidate = next(row for row in candidates_body if row["source_ref"] == "gmail-thread:abc123")
    assert gmail_candidate["channel_hint"] == "gmail"
    assert gmail_candidate["signal_type"] == "email_thread"
    calendar_candidate = next(row for row in candidates_body if row["source_ref"] == "calendar-event:prep-1")
    assert calendar_candidate["channel_hint"] == "calendar"
    assert calendar_candidate["signal_type"] == "calendar_note"
    assert calendar_candidate["kind"] == "follow_up"
    assert calendar_candidate["stakeholder_id"] == seeded["stakeholder_id"]

    accepted = client.post(
        f"/app/api/commitments/candidates/{calendar_candidate['candidate_id']}/accept",
        json={"reviewer": "operator-office"},
    )
    assert accepted.status_code == 200
    accepted_body = accepted.json()
    assert accepted_body["id"].startswith("follow_up:")
    assert accepted_body["channel_hint"] == "calendar"
    assert accepted_body["source_type"] == "office_signal"
    assert accepted_body["source_ref"] == "calendar-event:prep-1"
    assert "office_signal_calendar_note" in event_types

    candidates = client.get("/app/api/commitments/candidates")
    assert candidates.status_code == 200
    assert any("board packet" in item["title"].lower() for item in candidates.json())

    deduplicated = client.post("/app/api/signals/google/sync", params={"email_limit": 2, "calendar_limit": 2})
    assert deduplicated.status_code == 200
    deduplicated_body = deduplicated.json()
    assert deduplicated_body["total"] == 2
    assert deduplicated_body["synced_total"] == 0
    assert deduplicated_body["deduplicated_total"] == 2
    assert all(item["deduplicated"] is True for item in deduplicated_body["items"])
    diagnostics = client.get("/app/api/usage")
    assert diagnostics.status_code == 200
    sync_analytics = diagnostics.json()["analytics"]["sync"]
    assert sync_analytics["google_account_email"] == "exec@example.com"
    assert sync_analytics["google_sync_freshness_state"] == "clear"
    assert sync_analytics["google_sync_last_completed_at"]
    assert sync_analytics["pending_commitment_candidates"] >= 1
    sync_status = client.get("/app/api/signals/google/status")
    assert sync_status.status_code == 200
    sync_status_body = sync_status.json()
    assert sync_status_body["connected"] is True
    assert sync_status_body["account_email"] == "exec@example.com"
    assert sync_status_body["freshness_state"] == "clear"
    assert sync_status_body["last_completed_at"]
    assert sync_status_body["pending_commitment_candidates"] >= 1

    events_after_repeat = client.get("/app/api/events")
    assert events_after_repeat.status_code == 200
    repeat_event_types = [item["event_type"] for item in events_after_repeat.json()["items"]]
    assert repeat_event_types.count("office_signal_email_thread") == 1
    assert repeat_event_types.count("office_signal_calendar_note") == 1

    candidates_after_repeat = client.get("/app/api/commitments/candidates")
    assert candidates_after_repeat.status_code == 200
    board_packet_matches = [
        item for item in candidates_after_repeat.json() if "board packet" in str(item.get("title") or "").lower()
    ]
    assert len(board_packet_matches) == 1


def test_channel_loop_approvals_digest_can_accept_and_reject_signal_candidates() -> None:
    principal_id = "exec-product-channel-loop-candidates"
    client = build_product_client(principal_id=principal_id)
    seed_product_state(client, principal_id=principal_id)

    first_signal = client.post(
        "/app/api/signals/ingest",
        json={
            "signal_type": "email_thread",
            "channel": "gmail",
            "title": "Board packet follow-up",
            "summary": "Send revised board packet to Sofia by EOD.",
            "text": "Send revised board packet to Sofia by EOD.",
            "counterparty": "Sofia N.",
            "source_ref": "gmail-thread:inline-1",
            "external_id": "gmail-message:inline-1",
        },
    )
    assert first_signal.status_code == 200
    second_signal = client.post(
        "/app/api/signals/ingest",
        json={
            "signal_type": "email_thread",
            "channel": "gmail",
            "title": "Investor note",
            "summary": "Reply to Sofia about the investor note today.",
            "text": "Reply to Sofia about the investor note today.",
            "counterparty": "Sofia N.",
            "source_ref": "gmail-thread:inline-2",
            "external_id": "gmail-message:inline-2",
        },
    )
    assert second_signal.status_code == 200

    loop = client.get("/app/api/channel-loop")
    assert loop.status_code == 200
    approvals_digest = next(item for item in loop.json()["digests"] if item["key"] == "approvals")
    assert approvals_digest["stats"]["pending_commitment_candidates"] >= 2
    candidate_items = [item for item in approvals_digest["items"] if item["tag"] == "Candidate"]
    assert len(candidate_items) >= 2
    assert all("/app/channel-actions/" in item["action_href"] for item in candidate_items)
    assert any(item["secondary_action_label"] == "Reject" for item in candidate_items)

    accepted_item = next(item for item in candidate_items if "board packet" in item["title"].lower())
    accepted = client.get(accepted_item["action_href"], follow_redirects=False)
    assert accepted.status_code == 303
    assert accepted.headers["location"] == "/app/channel-loop/approvals"

    commitments = client.get("/app/api/commitments")
    assert commitments.status_code == 200
    accepted_commitment = next(item for item in commitments.json() if "board packet" in item["statement"].lower())
    assert accepted_commitment["source_type"] == "office_signal"
    assert accepted_commitment["channel_hint"] == "gmail"
    assert accepted_commitment["source_ref"] == "gmail-thread:inline-1"
    assert accepted_commitment["due_at"]

    pending_after_accept = client.get("/app/api/commitments/candidates", params={"status": "pending"})
    assert pending_after_accept.status_code == 200
    assert all("board packet" not in str(item.get("title") or "").lower() for item in pending_after_accept.json())

    rejected_item = next(item for item in candidate_items if "investor note" in item["title"].lower())
    rejected = client.get(rejected_item["secondary_action_href"], follow_redirects=False)
    assert rejected.status_code == 303
    assert rejected.headers["location"] == "/app/channel-loop/approvals"

    rejected_candidates = client.get("/app/api/commitments/candidates", params={"status": "rejected"})
    assert rejected_candidates.status_code == 200
    assert any("investor note" in str(item.get("title") or "").lower() for item in rejected_candidates.json())

    diagnostics = client.get("/app/api/diagnostics")
    assert diagnostics.status_code == 200
    assert int(dict(diagnostics.json()["analytics"]["counts"]).get("channel_action_redeemed") or 0) >= 2


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


def test_office_signal_duplicate_merge_upgrades_commitment_provenance() -> None:
    principal_id = "exec-product-duplicate-signal-merge"
    client = build_product_client(principal_id=principal_id)
    seeded = seed_product_state(client, principal_id=principal_id)
    commitment_ref = f"commitment:{seeded['commitment_id']}"

    signal = client.post(
        "/app/api/signals/ingest",
        json={
            "signal_type": "email_thread",
            "channel": "gmail",
            "text": "Please send board materials to Sofia tomorrow.",
            "counterparty": "Sofia N.",
            "source_ref": "gmail-thread:dup-1",
            "external_id": "gmail-message:dup-1",
        },
    )
    assert signal.status_code == 200
    signal_body = signal.json()
    duplicate = next(row for row in signal_body["staged_candidates"] if row["duplicate_of_ref"] == commitment_ref)
    assert duplicate["channel_hint"] == "gmail"
    assert duplicate["source_ref"] == "gmail-thread:dup-1"

    merged = client.post(
        f"/app/api/commitments/candidates/{duplicate['candidate_id']}/accept",
        json={"reviewer": "operator-office"},
    )
    assert merged.status_code == 200
    merged_body = merged.json()
    assert merged_body["id"] == commitment_ref
    assert merged_body["channel_hint"] == "gmail"
    assert merged_body["source_type"] == "office_signal"
    assert merged_body["source_ref"] == "gmail-thread:dup-1"
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


def test_brief_ranking_surfaces_repeated_deferrals() -> None:
    principal_id = "exec-brief-deferrals"
    client = build_product_client(principal_id=principal_id)
    seeded = seed_product_state(client, principal_id=principal_id)

    initial_brief = client.get("/app/api/brief")
    assert initial_brief.status_code == 200
    initial_item = next(item for item in initial_brief.json()["items"] if item["object_ref"] == f"commitment:{seeded['commitment_id']}")
    initial_score = float(initial_item["score"])
    assert "Deferred" not in initial_item["why_now"]

    first_defer = client.post(
        f"/app/api/commitments/commitment:{seeded['commitment_id']}/resolve",
        json={"action": "defer", "reason_code": "waiting_on_dependency", "reason": "Waiting on the revised board pack."},
    )
    assert first_defer.status_code == 200

    first_brief = client.get("/app/api/brief")
    assert first_brief.status_code == 200
    first_item = next(item for item in first_brief.json()["items"] if item["object_ref"] == f"commitment:{seeded['commitment_id']}")
    assert "Deferred 1 time" in first_item["why_now"]
    assert float(first_item["score"]) > initial_score

    second_defer = client.post(
        f"/app/api/commitments/commitment:{seeded['commitment_id']}/resolve",
        json={"action": "defer", "reason_code": "waiting_on_dependency", "reason": "Still waiting on the revised board pack."},
    )
    assert second_defer.status_code == 200

    second_brief = client.get("/app/api/brief")
    assert second_brief.status_code == 200
    second_item = next(item for item in second_brief.json()["items"] if item["object_ref"] == f"commitment:{seeded['commitment_id']}")
    assert "Deferred 2 times" in second_item["why_now"]
    assert float(second_item["score"]) > float(first_item["score"])


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
    outcomes = client.get("/app/api/outcomes")
    assert outcomes.status_code == 200
    outcomes_body = outcomes.json()
    assert outcomes_body["counts"]["draft_approved"] >= 1
    assert outcomes_body["counts"]["commitment_closed"] >= 1
    assert outcomes_body["success_summary"]
    assert "memo_loop" in outcomes_body
    assert outcomes_body["office_loop_proof"]["state"] in {"clear", "watch", "critical"}

    bundle = client.get("/app/api/diagnostics/export")
    assert bundle.status_code == 200
    body = bundle.json()
    assert body["workspace"]["mode"] == "personal"
    assert body["plan"]["plan_key"] == "pilot"
    assert body["billing"]["billing_state"] == "trial"
    assert body["billing"]["renewal_owner_role"] == "principal"
    assert "pending" in body["approvals"]
    assert isinstance(body["human_tasks"], list)


def test_channel_digest_delivery_uses_public_host_fallback(monkeypatch) -> None:
    principal_id = "exec-product-delivery-public-host"
    client = build_product_client(principal_id=principal_id)
    seed_product_state(client, principal_id=principal_id)
    monkeypatch.delenv("EA_PUBLIC_APP_BASE_URL", raising=False)
    monkeypatch.setenv("EA_GOOGLE_OAUTH_REDIRECT_URI", "https://public.example.com/google/callback")

    delivery = client.post(
        "/app/api/channel-loop/memo/deliveries",
        json={
            "recipient_email": "operator@example.com",
            "role": "operator",
            "display_name": "Operator Digest",
            "operator_id": "operator-office",
            "delivery_channel": "link_only",
            "expires_in_hours": 24,
        },
    )
    assert delivery.status_code == 200
    delivery_body = delivery.json()
    assert "https://public.example.com/channel-loop/deliveries/" in delivery_body["plain_text"]


def test_memo_digest_delivery_refreshes_stale_google_signals_before_issue(monkeypatch) -> None:
    principal_id = "exec-product-memo-refresh"
    client = build_product_client(principal_id=principal_id)
    seed_product_state(client, principal_id=principal_id)
    sync_calls: list[tuple[str, str]] = []

    monkeypatch.setattr(
        ProductService,
        "google_signal_sync_status",
        lambda self, *, principal_id: {
            "connected": True,
            "freshness_state": "watch",
        },
    )

    def _fake_sync(self, *, principal_id: str, actor: str, email_limit: int = 5, calendar_limit: int = 5):
        sync_calls.append((principal_id, actor))
        self.stage_extracted_commitments(
            principal_id=principal_id,
            text="Send revised board packet to Sofia by EOD.",
            counterparty="Sofia N.",
            channel_hint="gmail",
            source_ref="gmail-thread:memo-refresh",
            signal_type="email_thread",
            reference_at="2026-03-28T10:15:00+00:00",
        )
        return {"total": 1, "synced_total": 1, "deduplicated_total": 0}

    monkeypatch.setattr(ProductService, "sync_google_workspace_signals", _fake_sync)

    delivery = client.post(
        "/app/api/channel-loop/memo/deliveries",
        json={
            "recipient_email": "principal@example.com",
            "role": "principal",
            "display_name": "Principal Digest",
            "delivery_channel": "link_only",
        },
    )
    assert delivery.status_code == 200
    assert sync_calls == [(principal_id, "channel_digest:memo")]

    candidates = client.get("/app/api/commitments/candidates", params={"status": "pending"})
    assert candidates.status_code == 200
    refreshed_candidate = next(item for item in candidates.json() if "board packet" in item["title"].lower())
    assert refreshed_candidate["suggested_due_at"] == "2026-03-28T17:00:00+00:00"

    diagnostics = client.get("/app/api/diagnostics")
    assert diagnostics.status_code == 200
    counts = dict(diagnostics.json()["analytics"]["counts"])
    assert int(counts.get("channel_digest_signal_refresh_completed") or 0) >= 1


def test_operator_center_surfaces_delivery_sync_and_claim_lanes(monkeypatch) -> None:
    principal_id = "exec-operator-center"
    client = build_operator_product_client(principal_id=principal_id, operator_id="operator-office")
    seeded = seed_product_state(client, principal_id=principal_id)

    monkeypatch.setattr(
        google_oauth_service,
        "list_recent_workspace_signals",
        lambda **_: google_oauth_service.GoogleWorkspaceSignalSync(
            account_email="exec@example.com",
            granted_scopes=(
                google_oauth_service.GOOGLE_SCOPE_METADATA,
                google_oauth_service.GOOGLE_SCOPE_CALENDAR_READONLY,
            ),
            signals=(
                google_oauth_service.GoogleWorkspaceSignal(
                    signal_type="email_thread",
                    channel="gmail",
                    title="Investor follow-up",
                    summary="Send the revised board packet to Sofia tomorrow morning.",
                    text="Send the revised board packet to Sofia tomorrow morning.",
                    source_ref="gmail-thread:lane123",
                    external_id="gmail-message:lane456",
                    counterparty="Sofia N.",
                    due_at=None,
                    payload={"thread_id": "lane123", "message_id": "lane456"},
                ),
            ),
        ),
    )

    register = client.post("/v1/register/start", json={"email": "lane@example.com"})
    assert register.status_code == 200

    access_session = client.post(
        "/app/api/access-sessions",
        json={"email": "lane@example.com", "role": "operator", "display_name": "Lane Operator", "operator_id": "operator-office"},
    )
    assert access_session.status_code == 200
    access_url = access_session.json()["access_url"]

    client.headers.pop("X-EA-Principal-ID", None)
    opened_access = client.get(access_url, follow_redirects=False)
    assert opened_access.status_code == 303
    client.headers["X-EA-Principal-ID"] = principal_id

    revoked_access = client.post(f"/app/api/access-sessions/{access_session.json()['session_id']}/revoke")
    assert revoked_access.status_code == 200

    synced = client.post("/app/api/signals/google/sync", params={"email_limit": 1, "calendar_limit": 0})
    assert synced.status_code == 200

    center = client.get("/app/api/operator-center")
    assert center.status_code == 200
    body = center.json()
    lane_keys = {item["key"] for item in body["lanes"]}
    assert {"sla", "claims", "preclear", "principal", "delivery", "access", "exceptions", "sync"} <= lane_keys
    assert "registration_sent" in body["delivery"] or "registration_failed" in body["delivery"]
    assert body["access"]["issued"] >= 1
    assert body["access"]["opened"] >= 1
    assert body["access"]["revoked"] >= 1
    assert body["sync"]["google_sync_completed"] >= 1
    assert body["sync"]["office_signal_ingested"] >= 1
    assert body["sync"]["google_account_email"] == "exec@example.com"
    assert body["sync"]["google_sync_freshness_state"] == "clear"
    assert body["sync"]["pending_commitment_candidates"] >= 1
    assert any(item["label"] for item in body["next_actions"])
    assert "snapshot" in body
    assert body["snapshot"]["clearable_queue_items"] >= 1
    assert body["snapshot"]["exception_count"] >= 0
    assert body["snapshot"]["pending_drafts"] >= 1
    assert any(
        str(item.get("event_type") or "") in {
            "registration_email_sent",
            "registration_email_failed",
            "workspace_access_session_opened",
            "workspace_access_session_revoked",
            "google_workspace_signal_sync_completed",
        }
        for item in body["recent_runtime"]
    )


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
    assert accepted_body["access_url"].startswith("/workspace-access/")
    assert accepted_body["access_token"]
    assert accepted_body["access_expires_at"]

    client.headers.pop("X-EA-Principal-ID", None)
    access = client.get(accepted_body["access_url"], follow_redirects=False)
    assert access.status_code == 303
    assert access.headers["location"] == "/admin/office"
    assert "ea_workspace_session=" in str(access.headers.get("set-cookie") or "")
    session_loop = client.get("/app/api/channel-loop")
    assert session_loop.status_code == 200
    assert session_loop.json()["headline"] == "Inline loop"

    diagnostics = client.get("/app/api/diagnostics")
    assert diagnostics.status_code == 200
    assert int(diagnostics.json()["operators"]["seats_used"]) == 2
    assert int(diagnostics.json()["operators"]["seats_remaining"]) == 0

    revoked = client.post(f"/app/api/invitations/{invite['invitation_id']}/revoke")
    assert revoked.status_code == 200
    assert revoked.json()["status"] == "revoked"
    assert revoked.json()["invitation_id"] == invite["invitation_id"]


def test_workspace_access_sessions_and_channel_digest_deliveries_issue_cookie_ready_links() -> None:
    principal_id = "exec-access-sessions"
    client = build_product_client(principal_id=principal_id)
    seeded = seed_product_state(client, principal_id=principal_id)

    access_session = client.post(
        "/app/api/access-sessions",
        json={
            "email": "principal@example.com",
            "role": "principal",
            "display_name": "Principal Access",
            "expires_in_hours": 24,
        },
    )
    assert access_session.status_code == 200
    access_body = access_session.json()
    assert access_body["access_url"].startswith("/workspace-access/")
    assert access_body["default_target"] == "/app/today"
    assert access_body["status"] == "active"
    assert access_body["issued_at"]

    listed = client.get("/app/api/access-sessions")
    assert listed.status_code == 200
    listed_body = listed.json()
    listed_session = next(item for item in listed_body["items"] if item["session_id"] == access_body["session_id"])
    assert listed_session["status"] == "active"

    client.headers.pop("X-EA-Principal-ID", None)
    opened_access = client.get(access_body["access_url"], follow_redirects=False)
    assert opened_access.status_code == 303
    assert opened_access.headers["location"] == "/app/today"
    assert "ea_workspace_session=" in str(opened_access.headers.get("set-cookie") or "")
    session_drafts = client.get("/app/api/drafts")
    assert session_drafts.status_code == 200
    assert session_drafts.json()[0]["id"] == f"approval:{seeded['approval_id']}"
    client.headers["X-EA-Principal-ID"] = principal_id

    revoked_access = client.post(f"/app/api/access-sessions/{access_body['session_id']}/revoke")
    assert revoked_access.status_code == 200
    assert revoked_access.json()["status"] == "revoked"
    assert revoked_access.json()["revoked_at"]

    listed_revoked = client.get("/app/api/access-sessions", params={"status": "revoked"})
    assert listed_revoked.status_code == 200
    revoked_session = next(item for item in listed_revoked.json()["items"] if item["session_id"] == access_body["session_id"])
    assert revoked_session["status"] == "revoked"

    client.headers.pop("X-EA-Principal-ID", None)
    blocked_access = client.get(access_body["access_url"], follow_redirects=False)
    assert blocked_access.status_code == 404

    delivery = client.post(
        "/app/api/channel-loop/memo/deliveries",
        json={
            "recipient_email": "operator@example.com",
            "role": "operator",
            "display_name": "Operator Digest",
            "operator_id": "operator-office",
            "delivery_channel": "email",
            "expires_in_hours": 24,
        },
    )
    assert delivery.status_code == 200
    delivery_body = delivery.json()
    assert delivery_body["delivery_url"].startswith("/channel-loop/deliveries/")
    assert delivery_body["open_url"] == "/app/channel-loop/memo"
    assert "Morning memo digest" in delivery_body["plain_text"]
    assert "Open digest:" in delivery_body["plain_text"]

    opened_delivery = client.get(delivery_body["delivery_url"], follow_redirects=False)
    assert opened_delivery.status_code == 303
    assert opened_delivery.headers["location"] == "/app/channel-loop/memo"
    assert "ea_workspace_session=" in str(opened_delivery.headers.get("set-cookie") or "")
    delivered_loop = client.get("/app/api/channel-loop")
    assert delivered_loop.status_code == 200
    delivered_body = delivered_loop.json()
    assert delivered_body["headline"] == "Inline loop"
    assert any(item["key"] == "operator" for item in delivered_body["digests"])
