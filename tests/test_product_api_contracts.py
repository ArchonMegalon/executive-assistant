from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import urlparse
from uuid import uuid4

import app.product.service as product_service
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
    deadlines = client.get("/app/api/deadlines")
    assert deadlines.status_code == 200
    deadlines_body = deadlines.json()
    assert deadlines_body["total"] >= 1
    assert any(item["id"] == f"deadline:{seeded['deadline_window_id']}" for item in deadlines_body["items"])
    deadline_detail = client.get(f"/app/api/deadlines/deadline:{seeded['deadline_window_id']}")
    assert deadline_detail.status_code == 200
    assert deadline_detail.json()["title"] == "Board memo delivery window"
    assert deadline_detail.json()["status"] == "open"

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
    assert any(item["title"] == "sofia@example.com" for item in person_graph_detail.json()["threads"])

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
    assert diagnostics_body["product_control"]["summary"]
    assert "journey_gate_health" in diagnostics_body["product_control"]
    assert "provider_route_stewardship" in diagnostics_body["product_control"]
    assert "launch_readiness" in diagnostics_body["product_control"]
    assert "support_fallout" in diagnostics_body["product_control"]
    assert "public_guide_freshness" in diagnostics_body["product_control"]
    assert "state" in diagnostics_body["support_verification"]
    assert "analytics" in diagnostics_body
    assert "access" in diagnostics_body["analytics"]
    assert "invitations" in diagnostics_body["analytics"]
    assert "active" in diagnostics_body["analytics"]["access"]
    assert "pending" in diagnostics_body["analytics"]["invitations"]

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
    assert "approval_coverage_rate" in outcomes_body
    assert "approval_action_rate" in outcomes_body
    assert "delivery_followup_closeout_count" in outcomes_body
    assert "delivery_followup_blocked_count" in outcomes_body
    assert "delivery_followup_resolution_rate" in outcomes_body
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
    assert trust_body["public_help_grounding"]["id"] == "public_help"
    assert trust_body["public_help_grounding"]["actions"]
    assert any(item["label"] == "PUBLIC_TRUST_CONTENT.yaml" for item in trust_body["public_help_grounding"]["sources"])

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
    assert support_body["product_control"]["summary"]
    assert "journey_highlights" in support_body["product_control"]
    assert "support_fallout" in support_body["product_control"]
    assert "public_guide_freshness" in support_body["product_control"]
    assert "state" in support_body["support_verification"]
    assert support_body["support_assistant_grounding"]["id"] == "support_assistant"
    assert support_body["support_assistant_grounding"]["bullets"]
    assert any(item["label"] == "PRODUCT_HEALTH_SCORECARD.yaml" for item in support_body["support_assistant_grounding"]["sources"])

    channel_loop = client.get("/app/api/channel-loop")
    assert channel_loop.status_code == 200
    channel_loop_body = channel_loop.json()
    assert channel_loop_body["headline"] == "Inline loop"
    assert any(item["action_label"] == "Approve now" for item in channel_loop_body["items"])
    assert any("/app/channel-actions/" in item.get("action_href", "") for item in channel_loop_body["items"])
    digests = {item["key"]: item for item in channel_loop_body["digests"]}
    assert {"memo", "approvals", "operator"} <= set(digests)
    assert digests["memo"]["preview_text"]
    assert any(item["title"] == "Support closure grounding" for item in digests["memo"]["items"])
    assert any(item["action_label"] == "Approve now" for item in digests["approvals"]["items"])
    assert any(item["secondary_action_label"] == "Reject" for item in digests["approvals"]["items"] if item["tag"] == "Draft")
    assert any(item["tag"] == "Handoff" for item in digests["operator"]["items"])
    assert any(item["title"] == "Operator memo grounding" for item in digests["operator"]["items"])
    memo_plain = client.get("/app/api/channel-loop/memo/plain")
    assert memo_plain.status_code == 200
    assert "Morning memo digest" in memo_plain.text
    assert "Support closure grounding" in memo_plain.text
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
    assert signal_body["draft_count"] >= 1
    assert signal_body["staged_drafts"]
    assert "board packet" in signal_body["staged_drafts"][0]["draft_text"].lower()
    assert signal_body["ooda_loop"]["reviewed"] is True
    assert signal_body["ooda_loop"]["observe"]["signal_type"] == "email_thread"
    assert signal_body["ooda_loop"]["ltd_review"]["recommended_count"] >= 0

    events = client.get("/app/api/events")
    assert events.status_code == 200
    events_body = events.json()
    assert events_body["total"] >= 1
    assert any(item["event_type"] == "office_signal_email_thread" for item in events_body["items"])
    assert any(item["source_id"] == "gmail-thread-123" for item in events_body["items"])
    assert any(item["event_type"] == "office_signal_ooda_evaluated" and item["source_id"] == "gmail-thread-123" for item in events_body["items"])
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
    draft_result = next(item for item in search_body["items"] if item["kind"] == "draft")
    assert draft_result["href"].startswith("/app/threads/")
    assert "?focus=" not in draft_result["href"]

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
    assert commitment_result["href"].startswith("/app/commitment-items/")
    assert "?focus=" not in commitment_result["href"]
    assert commitment_result["action_label"] in {"Close", "Reopen", "Review"}
    assert commitment_result["action_href"].startswith("/app/actions/queue/")
    deadline_search = client.get("/app/api/search", params={"query": "delivery window", "limit": 10})
    assert deadline_search.status_code == 200
    deadline_body = deadline_search.json()
    assert any(item["kind"] == "deadline" and item["title"] == "Board memo delivery window" for item in deadline_body["items"])
    deadline_result = next(item for item in deadline_body["items"] if item["kind"] == "deadline")
    assert deadline_result["href"].startswith("/app/deadlines/")
    assert deadline_result["action_label"] in {"Resolve", "Reopen"}
    assert deadline_result["action_href"].startswith("/app/actions/queue/")

    webhook_test = client.post(f"/app/api/webhooks/{webhook_id}/test")
    assert webhook_test.status_code == 200
    assert webhook_test.json()["webhook"]["webhook_id"] == webhook_id
    assert webhook_test.json()["delivery"]["delivery_kind"] == "test"

    drafts_before_channel_action = client.get("/app/api/drafts")
    assert drafts_before_channel_action.status_code == 200
    draft_count_before = len(drafts_before_channel_action.json())
    draft_action = next(item["action_href"] for item in channel_loop_body["items"] if item["tag"] == "Draft")
    redeemed = client.get(draft_action, follow_redirects=False)
    assert redeemed.status_code == 303
    assert redeemed.headers["location"] == "/app/channel-loop"
    drafts_after_channel_action = client.get("/app/api/drafts")
    assert drafts_after_channel_action.status_code == 200
    assert len(drafts_after_channel_action.json()) == draft_count_before - 1

    diagnostics_after_channel_action = client.get("/app/api/diagnostics")
    assert diagnostics_after_channel_action.status_code == 200
    assert int(dict(diagnostics_after_channel_action.json()["analytics"]["counts"]).get("channel_action_redeemed") or 0) >= 1

    invalid_action = client.get("/app/channel-actions/bad-token")
    assert invalid_action.status_code == 404
    assert "This action link is no longer valid." in invalid_action.text
    assert "Request new sign-in link" in invalid_action.text


def test_public_channel_action_links_preview_before_applying_changes() -> None:
    principal_id = f"exec-public-channel-action-confirm-{uuid4().hex[:8]}"
    client = build_product_client(principal_id=principal_id)
    seed_product_state(client, principal_id=principal_id)

    loop = client.get("/app/api/channel-loop")
    assert loop.status_code == 200
    approvals_digest = next(item for item in loop.json()["digests"] if item["key"] == "approvals")
    draft_action = next(item["action_href"] for item in approvals_digest["items"] if item["tag"] == "Draft")

    drafts_before = client.get("/app/api/drafts")
    assert drafts_before.status_code == 200
    draft_count_before = len(drafts_before.json())

    client.headers.pop("X-EA-Principal-ID", None)
    preview = client.get(draft_action)
    assert preview.status_code == 200
    assert "Review this secure action before applying it." in preview.text
    assert "Email scanners and previews will not apply this action." in preview.text

    preview_head = client.head(draft_action, follow_redirects=False)
    assert preview_head.status_code == 200

    client.headers["X-EA-Principal-ID"] = principal_id
    drafts_after_preview = client.get("/app/api/drafts")
    assert drafts_after_preview.status_code == 200
    assert len(drafts_after_preview.json()) == draft_count_before

    client.headers.pop("X-EA-Principal-ID", None)
    confirmed = client.post(draft_action, follow_redirects=False)
    assert confirmed.status_code == 200
    assert "The requested action was recorded." in confirmed.text
    assert "Open related workspace surface" in confirmed.text

    client.headers["X-EA-Principal-ID"] = principal_id
    drafts_after_confirm = client.get("/app/api/drafts")
    assert drafts_after_confirm.status_code == 200
    assert len(drafts_after_confirm.json()) == draft_count_before - 1

    diagnostics = client.get("/app/api/diagnostics")
    assert diagnostics.status_code == 200
    assert int(dict(diagnostics.json()["analytics"]["counts"]).get("channel_action_redeemed") or 0) >= 1


def test_signal_ingest_stages_reviewable_reply_draft_and_metrics() -> None:
    principal_id = "exec-product-signal-draft"
    client = build_product_client(principal_id=principal_id)
    seed_product_state(client, principal_id=principal_id)

    signal = client.post(
        "/app/api/signals/ingest",
        json={
            "signal_type": "email_thread",
            "channel": "gmail",
            "title": "Board packet follow-up",
            "summary": "Send revised board packet to Sofia by EOD.",
            "text": "Send revised board packet to Sofia by EOD.",
            "counterparty": "Sofia N.",
            "source_ref": "gmail-thread:signal-draft-1",
            "external_id": "gmail-message:signal-draft-1",
        },
    )
    assert signal.status_code == 200
    body = signal.json()
    assert body["draft_count"] == 1
    assert body["staged_drafts"][0]["recipient_summary"] == "Sofia N."
    assert body["staged_drafts"][0]["intent"] == "reply"
    assert "revised board packet" in body["staged_drafts"][0]["draft_text"].lower()

    drafts = client.get("/app/api/drafts")
    assert drafts.status_code == 200
    assert any(item["id"] == body["staged_drafts"][0]["id"] for item in drafts.json())

    channel_loop = client.get("/app/api/channel-loop")
    assert channel_loop.status_code == 200
    approvals_digest = next(item for item in channel_loop.json()["digests"] if item["key"] == "approvals")
    assert any(item["tag"] == "Draft" and "Sofia N." in item["title"] for item in approvals_digest["items"])
    assert all("board packet" not in item["title"].lower() for item in approvals_digest["items"] if item["tag"] == "Candidate")
    assert approvals_digest["stats"]["pending_commitment_candidates"] == 0

    diagnostics = client.get("/app/api/diagnostics")
    assert diagnostics.status_code == 200
    counts = dict(diagnostics.json()["analytics"]["counts"])
    assert int(counts.get("approval_requested") or 0) >= 1

    duplicate = client.post(
        "/app/api/signals/ingest",
        json={
            "signal_type": "email_thread",
            "channel": "gmail",
            "title": "Board packet follow-up",
            "summary": "Send revised board packet to Sofia by EOD.",
            "text": "Send revised board packet to Sofia by EOD.",
            "counterparty": "Sofia N.",
            "source_ref": "gmail-thread:signal-draft-1",
            "external_id": "gmail-message:signal-draft-1",
        },
    )
    assert duplicate.status_code == 200
    duplicate_body = duplicate.json()
    assert duplicate_body["deduplicated"] is True
    assert duplicate_body["staged_count"] >= 1
    assert duplicate_body["draft_count"] == 1
    assert duplicate_body["staged_drafts"][0]["id"] == body["staged_drafts"][0]["id"]
    assert duplicate_body["ooda_loop"]["reviewed"] is True


def test_signal_ingest_email_thread_records_ooda_ltd_recommendations_for_property_workflows() -> None:
    principal_id = "exec-product-signal-ooda-property"
    client = build_product_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Signal OODA Office")

    signal = client.post(
        "/app/api/signals/ingest",
        json={
            "signal_type": "email_thread",
            "channel": "gmail",
            "title": "Apartment shortlist",
            "summary": "Please send a tour for this Willhaben apartment and share the link with Tibor.",
            "text": "Please send a tour for this Willhaben apartment and share the link with Tibor. https://www.willhaben.at/iad/immobilien/d/mietwohnungen/wien/garden-apartment-789",
            "counterparty": "Elisabeth G.",
            "source_ref": "gmail-thread:ooda-property-1",
            "external_id": "gmail-message:ooda-property-1",
            "payload": {
                "property_url": "https://www.willhaben.at/iad/immobilien/d/mietwohnungen/wien/garden-apartment-789",
                "delivery_recipient_email": "tibor.girschele@gmail.com",
            },
        },
    )
    assert signal.status_code == 200
    body = signal.json()
    assert body["ooda_loop"]["reviewed"] is True
    recommendations = body["ooda_loop"]["ltd_review"]["recommended_actions"]
    assert any(item["service_name"] == "Crezlo Tours" and item["action_key"] == "create_property_tour" for item in recommendations)
    assert any(item["service_name"] == "Emailit" and item["action_key"] == "delivery_outbox" for item in recommendations)

    events = client.get("/app/api/events", params={"channel": "product", "event_type": "office_signal_ooda_evaluated"})
    assert events.status_code == 200
    evaluated = next(item for item in events.json()["items"] if item["source_id"] == "gmail-thread:ooda-property-1")
    evaluated_actions = evaluated["payload"]["ooda_loop"]["ltd_review"]["recommended_actions"]
    assert any(item["task_key"].startswith("ltd_runtime__crezlo_tours__create_property_tour") for item in evaluated_actions)


def test_signal_ingest_willhaben_search_agent_mail_skips_commitment_staging_but_keeps_ooda_ltd_review() -> None:
    principal_id = "exec-product-signal-ooda-willhaben-agent"
    client = build_product_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Willhaben OODA Office")

    signal = client.post(
        "/app/api/signals/ingest",
        json={
            "signal_type": "email_thread",
            "channel": "gmail",
            "title": "\"Mietwohnungen 2,20, 09\" hat 1 neue Anzeige für dich gefunden",
            "summary": "\"Mietwohnungen 2,20, 09\" hat 1 neue Anzeige für dich gefunden",
            "text": "\"Mietwohnungen 2,20, 09\" hat 1 neue Anzeige für dich gefunden",
            "counterparty": "willhaben-Suchagent",
            "source_ref": "gmail-thread:elisabeth.girschele@gmail.com:test-willhaben-agent-1",
            "external_id": "gmail-message:elisabeth.girschele@gmail.com:test-willhaben-agent-1",
            "payload": {
                "from_email": "no-reply@agent.willhaben.at",
                "from_name": "willhaben-Suchagent",
                "account_email": "elisabeth.girschele@gmail.com",
                "labels": ["CATEGORY_UPDATES", "INBOX"],
            },
        },
    )
    assert signal.status_code == 200
    body = signal.json()
    assert body["staged_count"] == 0
    assert body["draft_count"] == 0
    assert body["ooda_loop"]["reviewed"] is True
    recommendations = body["ooda_loop"]["ltd_review"]["recommended_actions"]
    assert any(item["service_name"] == "Crezlo Tours" and item["action_key"] == "create_property_tour" for item in recommendations)
    automated_actions = body["ooda_loop"]["act"]["automated_actions"]
    review_action = next(item for item in automated_actions if item["action_key"] == "review_property_alert")
    assert review_action["task_type"] == "property_alert_review"
    assert review_action["human_task_id"].startswith("human_task:")
    queue = client.get("/app/api/queue")
    assert queue.status_code == 200
    assert any(item["id"] == review_action["human_task_id"] for item in queue.json()["items"])
    handoffs = client.get("/app/api/handoffs")
    assert handoffs.status_code == 200
    handoff = next(item for item in handoffs.json() if item["id"] == review_action["human_task_id"])
    assert handoff["task_type"] == "property_alert_review"
    assert handoff["summary"].startswith("Review apartment alert:")


def test_signal_ingest_willhaben_search_agent_mail_can_auto_create_and_send_to_tibor(monkeypatch) -> None:
    from app.domain.models import Artifact
    from app.services.registration_email import RegistrationEmailReceipt

    monkeypatch.setenv("EA_WILLHABEN_SEARCH_AGENT_AUTO_CREATE_PROPERTY_TOUR", "1")
    monkeypatch.setenv("EA_WILLHABEN_PROPERTY_TOUR_DEFAULT_RECIPIENT_EMAIL", "tibor.girschele@gmail.com")
    monkeypatch.setenv(
        "EA_WILLHABEN_PROPERTY_TOUR_RECIPIENT_MAP_JSON",
        '{"elisabeth.girschele@gmail.com":"tibor.girschele@gmail.com"}',
    )
    monkeypatch.setenv("EMAILIT_API_KEY", "test-emailit-key")

    principal_id = "cf-email:elisabeth.girschele@gmail.com"
    client = build_product_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Willhaben Auto Tour Office")

    monkeypatch.setattr(
        product_service,
        "_load_willhaben_property_packet",
        lambda url: {
            "property_url": url,
            "listing_id": "listing-auto-555",
            "title": "Search agent apartment",
            "property_facts_json": {},
            "media_urls_json": ["https://cdn.example.com/apartment-auto/photo-1.jpg"],
            "floorplan_urls_json": [],
            "tour_variants_json": [
                {
                    "variant_key": "layout_first",
                    "scene_strategy": "layout_first",
                    "theme_name": "clean_light",
                    "tour_style": "guided_layout_walkthrough",
                    "audience": "tenant_screening",
                    "creative_brief": "Lead with the floor plan.",
                    "call_to_action": "Open the tour.",
                    "scene_selection_json": {},
                    "tour_settings_json": {},
                }
            ],
        },
    )

    observed_email: dict[str, object] = {}

    def _fake_send_property_tour_email(**kwargs) -> RegistrationEmailReceipt:
        observed_email.update(kwargs)
        return RegistrationEmailReceipt(
            provider="emailit",
            message_id="property-tour-message-auto-agent",
            accepted_at="2026-05-02T00:00:00+00:00",
        )

    monkeypatch.setattr(product_service, "send_property_tour_email", _fake_send_property_tour_email)

    def _fake_execute_task_artifact(request):  # type: ignore[no-untyped-def]
        assert request.input_json["binding_id"] == "browseract-binding-auto-agent"
        return Artifact(
            artifact_id="artifact-property-tour-auto-agent",
            kind="property_tour_packet",
            content="Property tour created.",
            execution_session_id="session-property-tour-auto-agent",
            principal_id=principal_id,
            structured_output_json={
                "public_url": "https://myexternalbrain.com/tours/search-agent-apartment",
                "crezlo_public_url": "https://vendor.example.com/tours/search-agent-apartment",
            },
        )

    client.app.state.container.orchestrator.execute_task_artifact = _fake_execute_task_artifact

    signal = client.post(
        "/app/api/signals/ingest",
        json={
            "signal_type": "email_thread",
            "channel": "gmail",
            "title": "\"Mietwohnungen 2,20, 09\" hat 1 neue Anzeige für dich gefunden",
            "summary": "\"Mietwohnungen 2,20, 09\" hat 1 neue Anzeige für dich gefunden",
            "text": "\"Mietwohnungen 2,20, 09\" hat 1 neue Anzeige für dich gefunden",
            "counterparty": "willhaben-Suchagent",
            "source_ref": "gmail-thread:elisabeth.girschele@gmail.com:auto-willhaben-agent-1",
            "external_id": "gmail-message:elisabeth.girschele@gmail.com:auto-willhaben-agent-1",
            "payload": {
                "from_email": "no-reply@agent.willhaben.at",
                "from_name": "willhaben-Suchagent",
                "account_email": "elisabeth.girschele@gmail.com",
                "body_text_excerpt": (
                    "Neue Anzeige gefunden. "
                    "https://www.willhaben.at/iad/immobilien/d/mietwohnungen/wien/search-agent-apartment-555"
                ),
                "binding_id": "browseract-binding-auto-agent",
                "labels": ["CATEGORY_UPDATES", "INBOX"],
            },
        },
    )
    assert signal.status_code == 200
    body = signal.json()
    assert body["staged_count"] == 0
    assert body["draft_count"] == 0
    assert observed_email["recipient_email"] == "tibor.girschele@gmail.com"
    assert observed_email["property_url"] == (
        "https://www.willhaben.at/iad/immobilien/d/mietwohnungen/wien/search-agent-apartment-555"
    )
    automated_actions = body["ooda_loop"]["act"]["automated_actions"]
    assert not any(item.get("task_type") == "property_alert_review" for item in automated_actions)

    events = client.get(
        "/app/api/events",
        params={"channel": "product", "event_type": "willhaben_property_tour_email_sent"},
    )
    assert events.status_code == 200
    sent = next(
        item
        for item in events.json()["items"]
        if item["payload"]["source_ref"] == "gmail-thread:elisabeth.girschele@gmail.com:auto-willhaben-agent-1"
    )
    assert sent["payload"]["delivery_email"] == "tibor.girschele@gmail.com"

    handoffs = client.get("/app/api/handoffs")
    assert handoffs.status_code == 200
    assert not any(item["task_type"] == "property_alert_review" for item in handoffs.json())


def test_willhaben_property_tour_route_generates_tour_and_sends_email(monkeypatch) -> None:
    from app.domain.models import Artifact
    from app.services.registration_email import RegistrationEmailReceipt

    monkeypatch.setenv("EMAILIT_API_KEY", "test-emailit-key")
    principal_id = "cf-email:tibor.girschele@gmail.com"
    client = build_product_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Executive Office")

    packet = {
        "property_url": "https://www.willhaben.at/iad/immobilien/d/mietwohnungen/wien/wien-1200-brigittenau/apartment-a-123",
        "listing_id": "listing-123",
        "listing_uuid": "listing-uuid-123",
        "title": "Bright Brigittenau apartment",
        "property_facts_json": {
            "area_label": "74 m²",
            "rooms_label": "3 rooms",
            "total_rent_eur": 1890.0,
        },
        "media_urls_json": ["https://cdn.example.com/apartment-a/photo-1.jpg"],
        "floorplan_urls_json": ["https://cdn.example.com/apartment-a/floorplan-1.jpg"],
        "tour_variants_json": [
            {
                "variant_key": "layout_first",
                "scene_strategy": "layout_first",
                "theme_name": "clean_light",
                "tour_style": "guided_layout_walkthrough",
                "audience": "tenant_screening",
                "creative_brief": "Lead with the floor plan.",
                "call_to_action": "Open the tour.",
                "scene_selection_json": {"include_floorplans": True},
                "tour_settings_json": {"showSceneNumbers": True},
            }
        ],
    }
    monkeypatch.setattr(product_service, "_load_willhaben_property_packet", lambda url: dict(packet))

    observed_email: dict[str, object] = {}

    def _fake_send_property_tour_email(**kwargs) -> RegistrationEmailReceipt:
        observed_email.update(kwargs)
        return RegistrationEmailReceipt(
            provider="emailit",
            message_id="property-tour-message-1",
            accepted_at="2026-05-02T00:00:00+00:00",
        )

    monkeypatch.setattr(product_service, "send_property_tour_email", _fake_send_property_tour_email)

    def _fake_execute_task_artifact(request):  # type: ignore[no-untyped-def]
        assert request.task_key in {
            "create_property_tour",
            "ltd_runtime__crezlo_tours__create_property_tour",
        }
        assert request.input_json["binding_id"] == "browseract-binding-1"
        assert request.input_json["force_ui_worker"] is True
        assert request.input_json["property_url"] == packet["property_url"]
        return Artifact(
            artifact_id="artifact-property-tour-1",
            kind="property_tour_packet",
            content="Property tour created.",
            execution_session_id="session-property-tour-1",
            principal_id=principal_id,
            structured_output_json={
                "hosted_url": "https://myexternalbrain.com/tours/brigittenau-apartment-a",
                "public_url": "https://myexternalbrain.com/tours/brigittenau-apartment-a",
                "crezlo_public_url": "https://vendor.example.com/tours/brigittenau-apartment-a",
                "editor_url": "https://vendor.example.com/editor/brigittenau-apartment-a",
                "tour_id": "tour-123",
            },
        )

    client.app.state.container.orchestrator.execute_task_artifact = _fake_execute_task_artifact

    created = client.post(
        "/app/api/signals/willhaben/property-tour",
        json={
            "property_url": packet["property_url"],
            "binding_id": "browseract-binding-1",
        },
    )
    assert created.status_code == 200
    body = created.json()
    assert body["status"] == "sent"
    assert body["listing_id"] == "listing-123"
    assert body["tour_url"] == "https://myexternalbrain.com/tours/brigittenau-apartment-a"
    assert body["vendor_tour_url"] == "https://vendor.example.com/tours/brigittenau-apartment-a"
    assert body["editor_url"] == "https://vendor.example.com/editor/brigittenau-apartment-a"
    assert body["artifact_id"] == "artifact-property-tour-1"
    assert body["execution_session_id"] == "session-property-tour-1"
    assert body["delivery_email"] == "tibor.girschele@gmail.com"
    assert body["delivery_status"] == "sent"
    assert observed_email["recipient_email"] == "tibor.girschele@gmail.com"
    assert observed_email["tour_url"] == "https://myexternalbrain.com/tours/brigittenau-apartment-a"

    events = client.get(
        "/app/api/events",
        params={"channel": "product", "event_type": "willhaben_property_tour_email_sent"},
    )
    assert events.status_code == 200
    assert any(item["payload"]["delivery_email"] == "tibor.girschele@gmail.com" for item in events.json()["items"])


def test_willhaben_property_tour_route_falls_back_to_projected_crezlo_task_when_base_contract_missing(monkeypatch) -> None:
    from app.domain.models import Artifact

    principal_id = "cf-email:tibor.girschele@gmail.com"
    client = build_product_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Executive Office")

    packet = {
        "property_url": "https://www.willhaben.at/iad/immobilien/d/mietwohnungen/wien/live-apartment-456",
        "listing_id": "listing-456",
        "listing_uuid": "listing-uuid-456",
        "title": "Projected Crezlo apartment",
        "property_facts_json": {},
        "media_urls_json": ["https://cdn.example.com/apartment-live/photo-1.jpg"],
        "floorplan_urls_json": [],
        "tour_variants_json": [
            {
                "variant_key": "layout_first",
                "scene_strategy": "layout_first",
                "theme_name": "clean_light",
                "tour_style": "guided_layout_walkthrough",
                "audience": "tenant_screening",
                "creative_brief": "Lead with the floor plan.",
                "call_to_action": "Open the tour.",
                "scene_selection_json": {},
                "tour_settings_json": {},
            }
        ],
    }
    monkeypatch.setattr(product_service, "_load_willhaben_property_packet", lambda url: dict(packet))
    monkeypatch.setattr(client.app.state.container.task_contracts, "get_contract", lambda key: object() if key == "ltd_runtime__crezlo_tours__create_property_tour" else None)

    def _fake_execute_task_artifact(request):  # type: ignore[no-untyped-def]
        assert request.task_key == "ltd_runtime__crezlo_tours__create_property_tour"
        assert request.input_json["force_ui_worker"] is True
        return Artifact(
            artifact_id="artifact-property-tour-projected-1",
            kind="property_tour_packet",
            content="Property tour created.",
            execution_session_id="session-property-tour-projected-1",
            principal_id=principal_id,
            structured_output_json={
                "public_url": "https://myexternalbrain.com/tours/projected-crezlo-apartment",
                "crezlo_public_url": "https://vendor.example.com/tours/projected-crezlo-apartment",
            },
        )

    client.app.state.container.orchestrator.execute_task_artifact = _fake_execute_task_artifact

    created = client.post(
        "/app/api/signals/willhaben/property-tour",
        json={
            "property_url": packet["property_url"],
            "binding_id": "browseract-binding-projected-1",
            "auto_deliver": False,
        },
    )
    assert created.status_code == 200
    assert created.json()["status"] == "created"
    assert created.json()["tour_url"] == "https://myexternalbrain.com/tours/projected-crezlo-apartment"


def test_property_tour_binding_bootstraps_crezlo_metadata_from_runtime_state(monkeypatch, tmp_path: Path) -> None:
    principal_id = "cf-email:tibor.girschele@gmail.com"
    client = build_product_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Executive Office")

    runtime_root = tmp_path / "runtime"
    publish_dir = runtime_root / "crezlo_property_tour_operator_publish"
    publish_dir.mkdir(parents=True)
    (publish_dir / "result.json").write_text(
        json.dumps(
            {
                "status": "ok",
                "workflow_id": "86048166080352916",
                "workflow_name": "crezlo_property_tour_operator_live",
            }
        ),
        encoding="utf-8",
    )
    worker_dir = runtime_root / "crezlo_property_tour_runs_smoke4"
    worker_dir.mkdir(parents=True)
    (worker_dir / "sample.worker_input.json").write_text(
        json.dumps(
            {
                "login_email": "tour-operator@example.com",
                "login_password": "secret-password",
                "workspace_id": "workspace-123",
                "workspace_domain": "ea-property-tours.example.com",
                "workspace_base_url": "https://ea-property-tours.example.com",
                "workspace_tours_url": "https://ea-property-tours.example.com/admin/tours",
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setenv("BROWSERACT_API_KEY", "browseract-key")
    monkeypatch.setenv("EA_CREZLO_PROPERTY_TOUR_STATE_ROOT", str(runtime_root))

    service = ProductService(client.app.state.container)
    binding_id = service._resolve_browseract_property_tour_binding_id(principal_id=principal_id)
    binding = client.app.state.container.tool_runtime.get_connector_binding(binding_id)

    assert binding is not None
    metadata = dict(binding.auth_metadata_json or {})
    assert metadata["crezlo_property_tour_workflow_id"] == "86048166080352916"
    assert metadata["browseract_crezlo_property_tour_workflow_id"] == "86048166080352916"
    assert metadata["crezlo_login_email"] == "tour-operator@example.com"
    assert metadata["crezlo_login_password"] == "secret-password"
    assert metadata["crezlo_workspace_id"] == "workspace-123"
    assert metadata["crezlo_workspace_domain"] == "ea-property-tours.example.com"
    assert metadata["crezlo_workspace_base_url"] == "https://ea-property-tours.example.com"
    assert metadata["crezlo_workspace_tours_url"] == "https://ea-property-tours.example.com/admin/tours"


def test_property_tour_url_resolver_prefers_branded_link_even_when_legacy_fields_are_swapped(monkeypatch) -> None:
    monkeypatch.setenv("EA_PUBLIC_APP_BASE_URL", "https://myexternalbrain.com")
    branded_url, vendor_url = product_service._resolve_property_tour_urls(
        {
            "crezlo_public_url": "https://myexternalbrain.com/tours/brigittenau-apartment-a",
            "public_url": "https://vendor.example.com/tours/brigittenau-apartment-a",
            "share_url": "https://vendor.example.com/share/brigittenau-apartment-a",
        }
    )
    assert branded_url == "https://myexternalbrain.com/tours/brigittenau-apartment-a"
    assert vendor_url == "https://vendor.example.com/tours/brigittenau-apartment-a"


def test_willhaben_property_packet_script_path_supports_container_layout(monkeypatch, tmp_path: Path) -> None:
    container_root = tmp_path / "app"
    service_path = container_root / "app" / "product" / "service.py"
    service_path.parent.mkdir(parents=True)
    service_path.write_text("# container service stub\n", encoding="utf-8")
    script_path = container_root / "scripts" / "willhaben_property_packet.py"
    script_path.parent.mkdir(parents=True)
    script_path.write_text("#!/usr/bin/env python3\n", encoding="utf-8")

    monkeypatch.delenv("EA_WILLHABEN_PROPERTY_PACKET_SCRIPT", raising=False)
    monkeypatch.setattr(product_service, "__file__", str(service_path))

    assert product_service._willhaben_property_packet_script_path() == script_path.resolve()


def test_willhaben_property_tour_route_blocks_with_handoff_when_connector_missing(monkeypatch) -> None:
    monkeypatch.delenv("BROWSERACT_API_KEY", raising=False)
    principal_id = "cf-email:tibor.girschele@gmail.com"
    client = build_product_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Executive Office")

    monkeypatch.setattr(
        product_service,
        "_load_willhaben_property_packet",
        lambda url: {
            "property_url": url,
            "listing_id": "listing-456",
            "title": "Riverside apartment",
            "property_facts_json": {},
            "media_urls_json": ["https://cdn.example.com/apartment-b/photo-1.jpg"],
            "floorplan_urls_json": [],
            "tour_variants_json": [
                {
                    "variant_key": "layout_first",
                    "scene_strategy": "layout_first",
                    "theme_name": "clean_light",
                    "tour_style": "guided_layout_walkthrough",
                    "audience": "tenant_screening",
                    "creative_brief": "Lead with the floor plan.",
                    "call_to_action": "Open the tour.",
                    "scene_selection_json": {},
                    "tour_settings_json": {},
                }
            ],
        },
    )

    created = client.post(
        "/app/api/signals/willhaben/property-tour",
        json={
            "property_url": "https://www.willhaben.at/iad/immobilien/d/mietwohnungen/wien/apartment-b-456",
        },
    )
    assert created.status_code == 200
    body = created.json()
    assert body["status"] == "blocked"
    assert body["blocked_reason"] == "browseract_connector_unconfigured"
    assert body["human_task_id"].startswith("human_task:")

    handoffs = client.get("/app/api/handoffs")
    assert handoffs.status_code == 200
    assert any(item["id"] == body["human_task_id"] for item in handoffs.json())


def test_willhaben_property_tour_followup_can_be_recreated_once_connector_is_available(monkeypatch) -> None:
    from app.domain.models import Artifact
    from app.services.registration_email import RegistrationEmailReceipt

    monkeypatch.delenv("BROWSERACT_API_KEY", raising=False)
    monkeypatch.setenv("EMAILIT_API_KEY", "test-emailit-key")
    principal_id = "cf-email:tibor.girschele@gmail.com"
    client = build_operator_product_client(principal_id=principal_id, operator_id="operator-office")
    start_workspace(client, mode="personal", workspace_name="Executive Office")
    seed_product_state(client, principal_id=principal_id)

    packet = {
        "property_url": "https://www.willhaben.at/iad/immobilien/d/mietwohnungen/wien/apartment-recreate-001",
        "listing_id": "listing-recreate-001",
        "title": "Quiet district apartment",
        "listing_uuid": "listing-recreate-uuid-001",
        "property_facts_json": {
            "area_label": "64 m²",
            "rooms_label": "2 rooms",
            "total_rent_eur": 1690.0,
        },
        "media_urls_json": ["https://cdn.example.com/apartment-c/photo-1.jpg"],
        "floorplan_urls_json": ["https://cdn.example.com/apartment-c/floorplan-1.jpg"],
        "tour_variants_json": [
            {
                "variant_key": "layout_first",
                "scene_strategy": "layout_first",
                "theme_name": "clean_light",
                "tour_style": "guided_layout_walkthrough",
                "audience": "tenant_screening",
            }
        ],
    }
    monkeypatch.setattr(product_service, "_load_willhaben_property_packet", lambda url: dict(packet))

    blocked = client.post(
        "/app/api/signals/willhaben/property-tour",
        json={
            "property_url": packet["property_url"],
        },
    )
    assert blocked.status_code == 200
    blocked_body = blocked.json()
    assert blocked_body["status"] == "blocked"
    assert blocked_body["blocked_reason"] == "browseract_connector_unconfigured"
    handoff_id = blocked_body["human_task_id"]

    send_calls: list[dict[str, object]] = []

    def _fake_execute_task_artifact(request):  # type: ignore[no-untyped-def]
        assert request.task_key in {
            "create_property_tour",
            "ltd_runtime__crezlo_tours__create_property_tour",
        }
        return Artifact(
            artifact_id="artifact-property-tour-recreated-1",
            kind="property_tour_packet",
            content="Property tour recreated.",
            execution_session_id="session-property-tour-recreated-1",
            principal_id=principal_id,
            structured_output_json={
                "public_url": "https://myexternalbrain.com/tours/recreated-apartment",
                "crezlo_public_url": "https://vendor.example.com/tours/recreated-apartment",
                "editor_url": "https://vendor.example.com/editor/recreated-apartment",
            },
        )

    def _fake_send_property_tour_email(**kwargs: object) -> RegistrationEmailReceipt:
        send_calls.append(dict(kwargs))
        return RegistrationEmailReceipt(
            provider="emailit",
            message_id="property-tour-message-recreated",
            accepted_at="2026-05-02T00:00:00+00:00",
        )

    client.app.state.container.orchestrator.execute_task_artifact = _fake_execute_task_artifact
    monkeypatch.setattr(product_service, "send_property_tour_email", _fake_send_property_tour_email)
    monkeypatch.setenv("BROWSERACT_API_KEY", "browseract-key")

    recreated = client.post(
        f"/app/api/handoffs/{handoff_id}/recreate",
        json={"operator_id": "operator-office"},
    )
    assert recreated.status_code == 200
    recreated_body = recreated.json()
    assert recreated_body["id"] == handoff_id
    assert recreated_body["resolution"] == "sent"
    assert recreated_body["task_type"] == "property_tour_followup"
    assert send_calls and send_calls[0]["property_url"] == packet["property_url"]

    events = client.get(
        "/app/api/events",
        params={"channel": "product", "event_type": "willhaben_property_tour_email_sent"},
    )
    assert events.status_code == 200
    assert any(
        item["payload"]["tour_url"] == "https://myexternalbrain.com/tours/recreated-apartment"
        for item in events.json()["items"]
    )


def test_office_signal_can_auto_create_willhaben_property_tour(monkeypatch) -> None:
    from app.domain.models import Artifact
    from app.services.registration_email import RegistrationEmailReceipt

    monkeypatch.setenv("EMAILIT_API_KEY", "test-emailit-key")
    principal_id = "cf-email:tibor.girschele@gmail.com"
    client = build_product_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Executive Office")

    monkeypatch.setattr(
        product_service,
        "_load_willhaben_property_packet",
        lambda url: {
            "property_url": url,
            "listing_id": "listing-789",
            "title": "Garden apartment",
            "property_facts_json": {},
            "media_urls_json": ["https://cdn.example.com/apartment-c/photo-1.jpg"],
            "floorplan_urls_json": [],
            "tour_variants_json": [
                {
                    "variant_key": "layout_first",
                    "scene_strategy": "layout_first",
                    "theme_name": "clean_light",
                    "tour_style": "guided_layout_walkthrough",
                    "audience": "tenant_screening",
                    "creative_brief": "Lead with the floor plan.",
                    "call_to_action": "Open the tour.",
                    "scene_selection_json": {},
                    "tour_settings_json": {},
                }
            ],
        },
    )
    monkeypatch.setattr(
        product_service,
        "send_property_tour_email",
        lambda **kwargs: RegistrationEmailReceipt(
            provider="emailit",
            message_id="property-tour-message-2",
            accepted_at="2026-05-02T00:00:00+00:00",
        ),
    )

    def _fake_execute_task_artifact(request):  # type: ignore[no-untyped-def]
        return Artifact(
            artifact_id="artifact-property-tour-2",
            kind="property_tour_packet",
            content="Property tour created.",
            execution_session_id="session-property-tour-2",
            principal_id=principal_id,
            structured_output_json={"crezlo_public_url": "https://myexternalbrain.com/tours/garden-apartment"},
        )

    client.app.state.container.orchestrator.execute_task_artifact = _fake_execute_task_artifact

    ingested = client.post(
        "/app/api/signals/ingest",
        json={
            "signal_type": "saved_link",
            "channel": "office_api",
            "title": "Willhaben alert",
            "summary": "A new apartment matches the search.",
            "text": "A new apartment matches the search.",
            "source_ref": "willhaben-alert:listing-789",
            "external_id": "listing-789",
            "payload": {
                "captured_url": "https://www.willhaben.at/iad/immobilien/d/mietwohnungen/wien/garden-apartment-789",
                "auto_create_property_tour": True,
                "binding_id": "browseract-binding-2",
            },
        },
    )
    assert ingested.status_code == 200
    assert ingested.json()["event_type"] == "office_signal_saved_link"

    events = client.get(
        "/app/api/events",
        params={"channel": "product", "event_type": "willhaben_property_tour_email_sent"},
    )
    assert events.status_code == 200
    assert any(item["payload"]["source_ref"] == "willhaben-alert:listing-789" for item in events.json()["items"])


def test_pocket_signal_upload_url_uses_public_host_and_ingests_saved_link(monkeypatch) -> None:
    principal_id = "exec-product-pocket-signal"
    client = build_product_client(principal_id=principal_id)
    seed_product_state(client, principal_id=principal_id)
    monkeypatch.setenv("EA_PUBLIC_APP_BASE_URL", "https://myexternalbrain.com")

    issued = client.post("/app/api/signals/pocket/upload-url", json={})
    assert issued.status_code == 200
    issued_body = issued.json()
    assert issued_body["channel"] == "pocket"
    assert issued_body["signal_type"] == "saved_link"
    assert issued_body["counterparty"] == "Pocket"
    assert issued_body["upload_url"].startswith("https://myexternalbrain.com/signals/pocket/")
    upload_path = urlparse(issued_body["upload_url"]).path

    preview = client.get(upload_path)
    assert preview.status_code == 200
    preview_body = preview.json()
    assert preview_body["endpoint_id"] == issued_body["endpoint_id"]
    assert preview_body["upload_url"] == issued_body["upload_url"]

    ingested = client.post(
        upload_path,
        content="url=https%3A%2F%2Fexample.com%2Fboard-packet&title=Board+packet&excerpt=Send+the+revised+board+packet+to+Sofia+tomorrow+morning.&item_id=pocket-123&tags=board%2Csofia",
        headers={"content-type": "application/x-www-form-urlencoded"},
    )
    assert ingested.status_code == 200
    ingested_body = ingested.json()
    assert ingested_body["channel"] == "pocket"
    assert ingested_body["event_type"] == "office_signal_saved_link"
    assert ingested_body["source_id"] == "pocket:pocket-123"
    assert ingested_body["external_id"] == "pocket-123"
    assert ingested_body["staged_count"] >= 1

    duplicate = client.post(
        upload_path,
        json={
            "url": "https://example.com/board-packet",
            "title": "Board packet",
            "excerpt": "Send the revised board packet to Sofia tomorrow morning.",
            "item_id": "pocket-123",
            "tags": ["board", "sofia"],
        },
    )
    assert duplicate.status_code == 200
    duplicate_body = duplicate.json()
    assert duplicate_body["deduplicated"] is True

    events = client.get("/app/api/events", params={"channel": "pocket"})
    assert events.status_code == 200
    events_body = events.json()
    assert any(item["event_type"] == "office_signal_saved_link" for item in events_body["items"])
    pocket_event = next(item for item in events_body["items"] if item["source_id"] == "pocket:pocket-123")
    assert pocket_event["external_id"] == "pocket-123"
    assert pocket_event["payload"]["captured_url"] == "https://example.com/board-packet"
    assert pocket_event["payload"]["captured_tags"] in {"board, sofia", "board,sofia"}


def test_pocket_signal_upload_url_includes_signal_ooda_evaluated() -> None:
    principal_id = "exec-product-pocket-signal-ooda"
    client = build_product_client(principal_id=principal_id)
    seed_product_state(client, principal_id=principal_id)

    issued = client.post("/app/api/signals/pocket/upload-url", json={"signal_type": "saved_link"})
    assert issued.status_code == 200
    upload_path = urlparse(issued.json()["upload_url"]).path

    ingested = client.post(
        upload_path,
        json={
            "url": "https://www.willhaben.at/iad/immobilien/d/mietwohnungen/wien/demo-flat-123",
            "title": "Willhaben apartment follow-up",
            "excerpt": "Please create a tour for this apartment and send it to the owner.",
            "item_id": "pocket-ooda-1",
            "counterparty": "Property Watch",
        },
    )
    assert ingested.status_code == 200
    ingested_body = ingested.json()
    assert ingested_body["channel"] == "pocket"
    assert ingested_body["event_type"] == "office_signal_saved_link"
    assert ingested_body["source_id"] == "pocket:pocket-ooda-1"
    assert ingested_body["external_id"] == "pocket-ooda-1"
    assert ingested_body["ooda_loop"]["reviewed"] is True
    assert ingested_body["ooda_loop"]["observe"]["signal_type"] == "saved_link"
    assert ingested_body["ooda_loop"]["observe"]["counterparty"] == "Property Watch"
    assert ingested_body["ooda_loop"]["ltd_review"]["recommended_count"] >= 0

    events = client.get("/app/api/events", params={"channel": "product", "event_type": "office_signal_ooda_evaluated"})
    assert events.status_code == 200
    assert any(
        item["source_id"] == "pocket:pocket-ooda-1" and item["payload"]["signal_type"] == "saved_link"
        for item in events.json()["items"]
    )


def test_signal_ingest_calendar_note_includes_ooda_loop() -> None:
    principal_id = "exec-product-calendar-ooda"
    client = build_product_client(principal_id=principal_id)
    seed_product_state(client, principal_id=principal_id)

    signal = client.post(
        "/app/api/signals/ingest",
        json={
            "signal_type": "calendar_note",
            "channel": "calendar",
            "title": "Prep with Sofia",
            "summary": "Follow up after stand-up; draft the decision notes and share them by EOD.",
            "text": "Follow up with Sofia and share the decision notes by end of day.",
            "source_ref": "calendar-event:prep-ooda-1",
            "external_id": "calendar-event:prep-ooda-1",
            "counterparty": "Sofia N.",
        },
    )
    assert signal.status_code == 200
    body = signal.json()
    assert body["channel"] == "calendar"
    assert body["event_type"] == "office_signal_calendar_note"
    assert body["staged_count"] >= 0
    assert body["ooda_loop"]["reviewed"] is True
    assert body["ooda_loop"]["observe"]["signal_type"] == "calendar_note"
    assert body["ooda_loop"]["ltd_review"]["reviewed"] is True

    events = client.get("/app/api/events", params={"channel": "product", "event_type": "office_signal_ooda_evaluated"})
    assert events.status_code == 200
    assert any(
        item["source_id"] == "calendar-event:prep-ooda-1" and item["payload"]["signal_type"] == "calendar_note"
        for item in events.json()["items"]
    )


def test_pocket_saved_link_import_from_local_json_archive(tmp_path) -> None:
    principal_id = "exec-product-pocket-import"
    client = build_product_client(principal_id=principal_id)
    seed_product_state(client, principal_id=principal_id)
    export_path = tmp_path / "ril_export.json"
    export_path.write_text(
        json.dumps(
            [
                {
                    "item_id": "pocket-import-1",
                    "resolved_url": "https://example.com/board-packet",
                    "resolved_title": "Board packet",
                    "excerpt": "Send the revised board packet to Sofia tomorrow morning.",
                    "tags": {"board": {"tag": "board"}, "sofia": {"tag": "sofia"}},
                    "time_added": "1714585500",
                },
                {
                    "item_id": "pocket-import-2",
                    "resolved_url": "https://example.com/follow-up",
                    "resolved_title": "Follow-up note",
                    "excerpt": "Confirm the follow-up plan with Sofia before lunch.",
                    "tags": ["follow-up", "sofia"],
                    "time_added": "1714585600",
                },
            ]
        ),
        encoding="utf-8",
    )

    imported = client.post("/app/api/signals/pocket/import-local", json={"path": str(export_path)})
    assert imported.status_code == 200
    body = imported.json()
    assert body["source_path"] == str(export_path)
    assert body["source_formats"] == ["json"]
    assert body["parsed_entry_total"] == 2
    assert body["total"] == 2
    assert body["synced_total"] == 2
    assert body["deduplicated_total"] == 0
    assert all(item["channel"] == "pocket" for item in body["items"])
    assert all(item["event_type"] == "office_signal_saved_link" for item in body["items"])

    events = client.get("/app/api/events", params={"channel": "pocket"})
    assert events.status_code == 200
    events_body = events.json()
    assert any(item["source_id"] == "pocket:pocket-import-1" for item in events_body["items"])
    imported_event = next(item for item in events_body["items"] if item["source_id"] == "pocket:pocket-import-1")
    assert imported_event["payload"]["captured_url"] == "https://example.com/board-packet"
    assert imported_event["payload"]["captured_tags"] == "board, sofia"
    assert imported_event["payload"]["import_channel"] == "pocket_export"

    repeated = client.post("/app/api/signals/pocket/import-local", json={"path": str(export_path)})
    assert repeated.status_code == 200
    repeated_body = repeated.json()
    assert repeated_body["total"] == 2
    assert repeated_body["synced_total"] == 0
    assert repeated_body["deduplicated_total"] == 2


def test_pocket_api_sync_ingests_completed_recordings(monkeypatch) -> None:
    principal_id = "exec-product-pocket-sync"
    client = build_product_client(principal_id=principal_id)
    seed_product_state(client, principal_id=principal_id)

    monkeypatch.setattr(
        product_service,
        "_pocket_list_recordings",
        lambda *, limit, page=1: {
            "success": True,
            "data": [
                {"id": "pending-1", "title": "Pending pocket item", "state": "pending"},
                {"id": "done-1", "title": "Pocket meeting", "state": "completed"},
            ],
            "pagination": {"total": 2},
        },
    )
    monkeypatch.setattr(
        product_service,
        "_pocket_get_recording_details",
        lambda recording_id: {
            "success": True,
            "data": {
                "id": recording_id,
                "title": "Pocket meeting",
                "state": "completed",
                "duration": 62.0,
                "language": "en",
                "recording_at": "2026-05-01T08:00:00Z",
                "created_at": "2026-05-01T08:01:00Z",
                "updated_at": "2026-05-01T08:02:00Z",
                "tags": ["meeting", "sofia"],
                "transcript": {
                    "text": "Discuss the board packet and send the revised version to Sofia.",
                    "segments": [{"start": 0.0, "end": 5.0, "text": "Discuss the board packet."}],
                    "metadata": {"source": "api"},
                },
                "summarizations": {
                    "summary-1": {
                        "id": "summary-1",
                        "v2": {"summary": {"markdown": "Send the revised board packet to Sofia today."}},
                    }
                },
            },
        },
    )
    synced = client.post("/app/api/signals/pocket/sync", params={"limit": 5})
    assert synced.status_code == 200
    body = synced.json()
    assert body["recording_total"] == 2
    assert body["total"] == 1
    assert body["synced_total"] == 1
    assert body["deduplicated_total"] == 0
    assert body["suppressed_total"] == 1
    assert body["failed_total"] == 0
    assert body["cursor_recording_id"] == "pending-1"
    assert body["cursor_updated_at"] == ""
    assert body["cursor_advanced"] is True
    assert body["items"][0]["channel"] == "pocket"
    assert body["items"][0]["event_type"] == "office_signal_audio_recording"
    assert body["items"][0]["source_id"] == "pocket-recording:done-1"

    events = client.get("/app/api/events", params={"channel": "pocket"})
    assert events.status_code == 200
    event = next(item for item in events.json()["items"] if item["source_id"] == "pocket-recording:done-1")
    assert event["payload"]["summary_markdown"] == "Send the revised board packet to Sofia today."
    assert event["payload"]["transcript_excerpt"] == "Discuss the board packet and send the revised version to Sofia."
    assert "audio_download_url" not in event["payload"]


def test_pocket_api_sync_uses_cursor_and_suppresses_non_actionable_audio_candidates(monkeypatch) -> None:
    principal_id = "exec-product-pocket-sync-cursor"
    client = build_product_client(principal_id=principal_id)
    seed_product_state(client, principal_id=principal_id)

    responses = [
        {
            "success": True,
            "data": [
                {
                    "id": "noise-1",
                    "title": "Pocket play",
                    "state": "completed",
                    "created_at": "2026-05-01T08:00:00Z",
                    "updated_at": "2026-05-01T08:04:00Z",
                    "recording_at": "2026-05-01T08:00:00Z",
                },
                {
                    "id": "work-1",
                    "title": "Pocket meeting",
                    "state": "completed",
                    "created_at": "2026-05-01T07:58:00Z",
                    "updated_at": "2026-05-01T08:02:00Z",
                    "recording_at": "2026-05-01T07:57:00Z",
                },
            ],
            "pagination": {"total": 2, "has_more": False},
        },
        {
            "success": True,
            "data": [
                {
                    "id": "work-2",
                    "title": "Pocket follow-up",
                    "state": "completed",
                    "created_at": "2026-05-01T08:05:00Z",
                    "updated_at": "2026-05-01T08:06:00Z",
                    "recording_at": "2026-05-01T08:05:00Z",
                },
                {
                    "id": "noise-1",
                    "title": "Pocket play",
                    "state": "completed",
                    "created_at": "2026-05-01T08:00:00Z",
                    "updated_at": "2026-05-01T08:04:00Z",
                    "recording_at": "2026-05-01T08:00:00Z",
                },
                {
                    "id": "work-1",
                    "title": "Pocket meeting",
                    "state": "completed",
                    "created_at": "2026-05-01T07:58:00Z",
                    "updated_at": "2026-05-01T08:02:00Z",
                    "recording_at": "2026-05-01T07:57:00Z",
                },
            ],
            "pagination": {"total": 3, "has_more": False},
        },
    ]
    call_index = {"value": 0}

    def _list_recordings(*, limit, page=1):
        assert page == 1
        response = responses[min(call_index["value"], len(responses) - 1)]
        call_index["value"] += 1
        return response

    details = {
        "noise-1": {
            "success": True,
            "data": {
                "id": "noise-1",
                "title": "Pocket play",
                "state": "completed",
                "duration": 180.0,
                "language": "en",
                "recording_at": "2026-05-01T08:00:00Z",
                "created_at": "2026-05-01T08:00:00Z",
                "updated_at": "2026-05-01T08:04:00Z",
                "tags": ["family"],
                "transcript": {
                    "text": "I need a communicator for the game and then we should eat.",
                    "segments": [{"start": 0.0, "end": 5.0, "text": "Play transcript"}],
                    "metadata": {"source": "api"},
                },
                "summarizations": {
                    "summary-noise": {
                        "id": "summary-noise",
                        "v2": {
                            "summary": {
                                "markdown": "The transcript captures a playful role-playing session between an adult and a child."
                            }
                        },
                    }
                },
            },
        },
        "work-1": {
            "success": True,
            "data": {
                "id": "work-1",
                "title": "Pocket meeting",
                "state": "completed",
                "duration": 62.0,
                "language": "en",
                "recording_at": "2026-05-01T07:57:00Z",
                "created_at": "2026-05-01T07:58:00Z",
                "updated_at": "2026-05-01T08:02:00Z",
                "tags": ["meeting", "sofia"],
                "transcript": {
                    "text": "Discuss the board packet and send the revised version to Sofia.",
                    "segments": [{"start": 0.0, "end": 5.0, "text": "Discuss the board packet."}],
                    "metadata": {"source": "api"},
                },
                "summarizations": {
                    "summary-1": {
                        "id": "summary-1",
                        "v2": {"summary": {"markdown": "Send the revised board packet to Sofia today."}},
                    }
                },
            },
        },
        "work-2": {
            "success": True,
            "data": {
                "id": "work-2",
                "title": "Pocket follow-up",
                "state": "completed",
                "duration": 32.0,
                "language": "en",
                "recording_at": "2026-05-01T08:05:00Z",
                "created_at": "2026-05-01T08:05:00Z",
                "updated_at": "2026-05-01T08:06:00Z",
                "tags": ["follow-up"],
                "transcript": {
                    "text": "Review the term sheet and email the signed notes today.",
                    "segments": [{"start": 0.0, "end": 5.0, "text": "Review the term sheet."}],
                    "metadata": {"source": "api"},
                },
                "summarizations": {
                    "summary-2": {
                        "id": "summary-2",
                        "v2": {"summary": {"markdown": "Review the term sheet and email the signed notes today."}},
                    }
                },
            },
        },
    }

    monkeypatch.setattr(product_service, "_pocket_list_recordings", _list_recordings)
    monkeypatch.setattr(product_service, "_pocket_get_recording_details", lambda recording_id: details[recording_id])

    first_sync = client.post("/app/api/signals/pocket/sync", params={"limit": 5})
    assert first_sync.status_code == 200
    first_body = first_sync.json()
    assert first_body["recording_total"] == 2
    assert first_body["cursor_recording_id"] == "noise-1"
    items_by_source = {item["source_id"]: item for item in first_body["items"]}
    assert items_by_source["pocket-recording:noise-1"]["staged_count"] == 0
    assert items_by_source["pocket-recording:work-1"]["staged_count"] >= 1

    events = client.get("/app/api/events", params={"channel": "pocket"})
    assert events.status_code == 200
    noise_event = next(item for item in events.json()["items"] if item["source_id"] == "pocket-recording:noise-1")
    assert noise_event["payload"]["suppress_candidate_staging"] is True
    assert noise_event["payload"]["staging_suppression_reason"] == "non_actionable_context"
    assert "adult and a child" in noise_event["payload"]["text"]

    second_sync = client.post("/app/api/signals/pocket/sync", params={"limit": 5})
    assert second_sync.status_code == 200
    second_body = second_sync.json()
    assert second_body["recording_total"] == 1
    assert second_body["total"] == 1
    assert second_body["items"][0]["source_id"] == "pocket-recording:work-2"
    assert second_body["cursor_recording_id"] == "work-2"


def test_pocket_api_sync_suppresses_performance_recordings_even_with_action_verbs(monkeypatch) -> None:
    principal_id = "exec-product-pocket-performance-noise"
    client = build_product_client(principal_id=principal_id)
    seed_product_state(client, principal_id=principal_id)

    monkeypatch.setattr(
        product_service,
        "_pocket_list_recordings",
        lambda *, limit, page=1: {
            "success": True,
            "data": [
                {
                    "id": "performance-1",
                    "title": "Pocket rehearsal",
                    "state": "completed",
                    "created_at": "2026-05-01T08:10:00Z",
                    "updated_at": "2026-05-01T08:11:00Z",
                    "recording_at": "2026-05-01T08:10:00Z",
                }
            ],
            "pagination": {"total": 1, "has_more": False},
        },
    )
    monkeypatch.setattr(
        product_service,
        "_pocket_get_recording_details",
        lambda recording_id: {
            "success": True,
            "data": {
                "id": recording_id,
                "title": "Pocket rehearsal",
                "state": "completed",
                "duration": 120.0,
                "language": "en",
                "recording_at": "2026-05-01T08:10:00Z",
                "created_at": "2026-05-01T08:10:00Z",
                "updated_at": "2026-05-01T08:11:00Z",
                "tags": ["music"],
                "transcript": {
                    "text": "Review the chorus, start again, and thank you for watching.",
                    "segments": [{"start": 0.0, "end": 5.0, "text": "Review the chorus."}],
                    "metadata": {"source": "api"},
                },
                "summarizations": {
                    "summary-performance": {
                        "id": "summary-performance",
                        "v2": {
                            "summary": {
                                "markdown": "This recording captures a vocal performance or rehearsal focused on repetitive phonetic patterns."
                            }
                        },
                    }
                },
            },
        },
    )

    synced = client.post("/app/api/signals/pocket/sync", params={"limit": 5})
    assert synced.status_code == 200
    body = synced.json()
    assert body["total"] == 1
    assert body["staging_suppressed_total"] == 1
    assert body["items"][0]["staged_count"] == 0

    events = client.get("/app/api/events", params={"channel": "pocket"})
    assert events.status_code == 200
    event = next(item for item in events.json()["items"] if item["source_id"] == "pocket-recording:performance-1")
    assert event["payload"]["suppress_candidate_staging"] is True
    assert event["payload"]["staging_suppression_reason"] == "non_actionable_context"


def test_pocket_api_sync_suppresses_personal_medical_recordings(monkeypatch) -> None:
    principal_id = "exec-product-pocket-medical-noise"
    client = build_product_client(principal_id=principal_id)
    seed_product_state(client, principal_id=principal_id)

    monkeypatch.setattr(
        product_service,
        "_pocket_list_recordings",
        lambda *, limit, page=1: {
            "success": True,
            "data": [
                {
                    "id": "medical-1",
                    "title": "Pocket medical update",
                    "state": "completed",
                    "created_at": "2026-05-01T08:20:00Z",
                    "updated_at": "2026-05-01T08:21:00Z",
                    "recording_at": "2026-05-01T08:20:00Z",
                }
            ],
            "pagination": {"total": 1, "has_more": False},
        },
    )
    monkeypatch.setattr(
        product_service,
        "_pocket_get_recording_details",
        lambda recording_id: {
            "success": True,
            "data": {
                "id": recording_id,
                "title": "Pocket medical update",
                "state": "completed",
                "duration": 240.0,
                "language": "en",
                "recording_at": "2026-05-01T08:20:00Z",
                "created_at": "2026-05-01T08:20:00Z",
                "updated_at": "2026-05-01T08:21:00Z",
                "tags": ["health"],
                "transcript": {
                    "text": "Schedule the next therapy session after the colonoscopy and review the chemo timeline.",
                    "segments": [{"start": 0.0, "end": 5.0, "text": "Medical transcript"}],
                    "metadata": {"source": "api"},
                },
                "summarizations": {
                    "summary-medical": {
                        "id": "summary-medical",
                        "v2": {
                            "summary": {
                                "markdown": "Therapy session scheduling and health update after chemo delay and an upcoming colonoscopy."
                            }
                        },
                    }
                },
            },
        },
    )

    synced = client.post("/app/api/signals/pocket/sync", params={"limit": 5})
    assert synced.status_code == 200
    body = synced.json()
    assert body["total"] == 1
    assert body["staging_suppressed_total"] == 1
    assert body["items"][0]["staged_count"] == 0

    events = client.get("/app/api/events", params={"channel": "pocket"})
    assert events.status_code == 200
    event = next(item for item in events.json()["items"] if item["source_id"] == "pocket-recording:medical-1")
    assert event["payload"]["suppress_candidate_staging"] is True
    assert event["payload"]["staging_suppression_reason"] == "non_actionable_context"


def test_pocket_api_backfill_rejects_existing_candidates_when_recording_is_now_non_actionable(monkeypatch) -> None:
    principal_id = "exec-product-pocket-cleanup"
    client = build_product_client(principal_id=principal_id)
    seed_product_state(client, principal_id=principal_id)
    service = ProductService(client.app.state.container)

    seeded = service.stage_extracted_commitments(
        principal_id=principal_id,
        text="Review the toy plan and start the next round.",
        counterparty="Pocket",
        channel_hint="pocket",
        source_ref="pocket-recording:noise-1",
        signal_type="audio_recording",
    )
    assert len(seeded) >= 1
    client.app.state.container.channel_runtime.ingest_observation(
        principal_id=principal_id,
        channel="pocket",
        event_type="office_signal_audio_recording",
        payload={
            "signal_type": "audio_recording",
            "title": "Pocket play",
            "summary": "Review the toy plan and start the next round.",
            "text": "Review the toy plan and start the next round.",
            "counterparty": "Pocket",
            "recording_id": "noise-1",
            "summary_markdown": "Review the toy plan and start the next round.",
            "transcript_excerpt": "Review the toy plan and start the next round.",
            "transcript_segment_count": 1,
            "staged_candidate_ids": [row.candidate_id for row in seeded],
        },
        source_id="pocket-recording:noise-1",
        external_id="noise-1",
        dedupe_key="office-signal|exec-product-pocket-cleanup|audio_recording|noise-1|pocket-recording:noise-1|Review the toy plan and start the next round.",
    )

    candidates = client.get("/app/api/commitments/candidates", params={"status": "pending"})
    assert candidates.status_code == 200
    assert any(item["source_ref"] == "pocket-recording:noise-1" for item in candidates.json())

    monkeypatch.setattr(
        product_service,
        "_pocket_list_recordings",
        lambda *, limit, page=1: {
            "success": True,
            "data": [
                {
                    "id": "noise-1",
                    "title": "Pocket play",
                    "state": "completed",
                    "created_at": "2026-05-01T08:00:00Z",
                    "updated_at": "2026-05-01T08:04:00Z",
                    "recording_at": "2026-05-01T08:00:00Z",
                }
            ],
            "pagination": {"total": 1, "has_more": False},
        },
    )
    monkeypatch.setattr(
        product_service,
        "_pocket_get_recording_details",
        lambda recording_id: {
            "success": True,
            "data": {
                "id": recording_id,
                "title": "Pocket play",
                "state": "completed",
                "duration": 180.0,
                "language": "en",
                "recording_at": "2026-05-01T08:00:00Z",
                "created_at": "2026-05-01T08:00:00Z",
                "updated_at": "2026-05-01T08:04:00Z",
                "tags": ["family"],
                "transcript": {
                    "text": "I need a communicator for the game and then we should eat.",
                    "segments": [{"start": 0.0, "end": 5.0, "text": "Play transcript"}],
                    "metadata": {"source": "api"},
                },
                "summarizations": {
                    "summary-noise": {
                        "id": "summary-noise",
                        "v2": {
                            "summary": {
                                "markdown": "The transcript captures a playful role-playing session between an adult and a child."
                            }
                        },
                    }
                },
            },
        },
    )

    backfill = client.post("/app/api/signals/pocket/backfill", params={"limit": 1})
    assert backfill.status_code == 200
    body = backfill.json()
    assert body["mode"] == "backfill"
    assert body["items"][0]["deduplicated"] is True
    assert body["staging_suppressed_total"] == 1

    pending = client.get("/app/api/commitments/candidates", params={"status": "pending"})
    assert pending.status_code == 200
    assert not any(item["source_ref"] == "pocket-recording:noise-1" for item in pending.json())

    rejected = client.get("/app/api/commitments/candidates", params={"status": "rejected"})
    assert rejected.status_code == 200
    assert any(item["source_ref"] == "pocket-recording:noise-1" for item in rejected.json())

def test_pocket_api_sync_continues_after_recording_failure_without_advancing_cursor(monkeypatch) -> None:
    principal_id = "exec-product-pocket-sync-failure"
    client = build_product_client(principal_id=principal_id)
    seed_product_state(client, principal_id=principal_id)

    monkeypatch.setattr(
        product_service,
        "_pocket_list_recordings",
        lambda *, limit, page=1: {
            "success": True,
            "data": [
                {
                    "id": "bad-1",
                    "title": "Pocket blocked item",
                    "state": "completed",
                    "created_at": "2026-05-01T08:10:00Z",
                    "updated_at": "2026-05-01T08:11:00Z",
                    "recording_at": "2026-05-01T08:10:00Z",
                },
                {
                    "id": "good-1",
                    "title": "Pocket good item",
                    "state": "completed",
                    "created_at": "2026-05-01T08:08:00Z",
                    "updated_at": "2026-05-01T08:09:00Z",
                    "recording_at": "2026-05-01T08:08:00Z",
                },
            ],
            "pagination": {"total": 2, "has_more": False},
        },
    )

    attempts = {"bad-1": 0}

    def _detail(recording_id: str):
        if recording_id == "bad-1":
            attempts["bad-1"] += 1
            if attempts["bad-1"] == 1:
                raise RuntimeError("pocket_api_http_503:temporary upstream issue")
        return {
            "success": True,
            "data": {
                "id": recording_id,
                "title": f"Pocket {recording_id}",
                "state": "completed",
                "duration": 22.0,
                "language": "en",
                "recording_at": "2026-05-01T08:08:00Z",
                "created_at": "2026-05-01T08:08:10Z",
                "updated_at": "2026-05-01T08:09:10Z" if recording_id == "good-1" else "2026-05-01T08:11:10Z",
                "tags": ["ops"],
                "transcript": {
                    "text": "Review the notes and send the follow-up today.",
                    "segments": [{"start": 0.0, "end": 1.0, "text": "Review the notes."}],
                    "metadata": {"source": "api"},
                },
                "summarizations": {
                    f"summary-{recording_id}": {
                        "id": f"summary-{recording_id}",
                        "v2": {"summary": {"markdown": "Review the notes and send the follow-up today."}},
                    }
                },
            },
        }

    monkeypatch.setattr(product_service, "_pocket_get_recording_details", _detail)

    first_sync = client.post("/app/api/signals/pocket/sync", params={"limit": 5})
    assert first_sync.status_code == 200
    first_body = first_sync.json()
    assert first_body["total"] == 1
    assert first_body["synced_total"] == 1
    assert first_body["failed_total"] == 1
    assert first_body["cursor_advanced"] is False

    second_sync = client.post("/app/api/signals/pocket/sync", params={"limit": 5})
    assert second_sync.status_code == 200
    second_body = second_sync.json()
    assert second_body["total"] == 2
    assert second_body["synced_total"] == 1
    assert second_body["deduplicated_total"] == 1
    assert second_body["failed_total"] == 0
    assert second_body["cursor_recording_id"] == "bad-1"


def test_pocket_api_backfill_ignores_cursor_but_preserves_incremental_position(monkeypatch) -> None:
    principal_id = "exec-product-pocket-backfill"
    client = build_product_client(principal_id=principal_id)
    seed_product_state(client, principal_id=principal_id)

    calls = {"count": 0}

    def _list_recordings(*, limit, page=1):
        calls["count"] += 1
        if calls["count"] == 1:
            return {
                "success": True,
                "data": [
                    {
                        "id": "new-1",
                        "title": "Pocket newest item",
                        "state": "completed",
                        "created_at": "2026-05-01T09:10:00Z",
                        "updated_at": "2026-05-01T09:11:00Z",
                        "recording_at": "2026-05-01T09:10:00Z",
                    }
                ],
                "pagination": {"total": 1, "has_more": False},
            }
        return {
            "success": True,
            "data": [
                {
                    "id": "new-1",
                    "title": "Pocket newest item",
                    "state": "completed",
                    "created_at": "2026-05-01T09:10:00Z",
                    "updated_at": "2026-05-01T09:11:00Z",
                    "recording_at": "2026-05-01T09:10:00Z",
                },
                {
                    "id": "old-1",
                    "title": "Pocket older item",
                    "state": "completed",
                    "created_at": "2026-05-01T09:00:00Z",
                    "updated_at": "2026-05-01T09:01:00Z",
                    "recording_at": "2026-05-01T09:00:00Z",
                },
                {
                    "id": "old-2",
                    "title": "Pocket oldest item",
                    "state": "completed",
                    "created_at": "2026-05-01T08:50:00Z",
                    "updated_at": "2026-05-01T08:51:00Z",
                    "recording_at": "2026-05-01T08:50:00Z",
                },
            ],
            "pagination": {"total": 3, "has_more": False},
        }

    def _detail(recording_id: str):
        return {
            "success": True,
            "data": {
                "id": recording_id,
                "title": f"Pocket {recording_id}",
                "state": "completed",
                "duration": 18.0,
                "language": "en",
                "recording_at": "2026-05-01T09:00:00Z",
                "created_at": "2026-05-01T09:00:10Z",
                "updated_at": {
                    "new-1": "2026-05-01T09:11:00Z",
                    "old-1": "2026-05-01T09:01:00Z",
                    "old-2": "2026-05-01T08:51:00Z",
                }[recording_id],
                "tags": ["ops"],
                "transcript": {
                    "text": "Review the notes and send the follow-up today.",
                    "segments": [{"start": 0.0, "end": 1.0, "text": "Review the notes."}],
                    "metadata": {"source": "api"},
                },
                "summarizations": {
                    f"summary-{recording_id}": {
                        "id": f"summary-{recording_id}",
                        "v2": {"summary": {"markdown": "Review the notes and send the follow-up today."}},
                    }
                },
            },
        }

    monkeypatch.setattr(product_service, "_pocket_list_recordings", _list_recordings)
    monkeypatch.setattr(product_service, "_pocket_get_recording_details", _detail)

    first_sync = client.post("/app/api/signals/pocket/sync", params={"limit": 1})
    assert first_sync.status_code == 200
    first_body = first_sync.json()
    assert first_body["cursor_recording_id"] == "new-1"
    assert first_body["cursor_persisted"] is True

    backfill = client.post("/app/api/signals/pocket/backfill", params={"limit": 10})
    assert backfill.status_code == 200
    backfill_body = backfill.json()
    assert backfill_body["mode"] == "backfill"
    assert backfill_body["cursor_used"] is False
    assert backfill_body["cursor_persisted"] is False
    assert backfill_body["cursor_recording_id"] == "new-1"
    assert backfill_body["total"] == 3
    assert backfill_body["synced_total"] == 2
    assert backfill_body["deduplicated_total"] == 1

    events = client.get("/app/api/events", params={"channel": "pocket"})
    assert events.status_code == 200
    source_ids = {item["source_id"] for item in events.json()["items"]}
    assert {"pocket-recording:new-1", "pocket-recording:old-1", "pocket-recording:old-2"} <= source_ids


def test_pocket_api_reset_cursor_allows_historical_rescan(monkeypatch) -> None:
    principal_id = "exec-product-pocket-reset"
    client = build_product_client(principal_id=principal_id)
    seed_product_state(client, principal_id=principal_id)

    monkeypatch.setattr(
        product_service,
        "_pocket_list_recordings",
        lambda *, limit, page=1: {
            "success": True,
            "data": [
                {
                    "id": "new-1",
                    "title": "Pocket newest item",
                    "state": "completed",
                    "created_at": "2026-05-01T09:10:00Z",
                    "updated_at": "2026-05-01T09:11:00Z",
                    "recording_at": "2026-05-01T09:10:00Z",
                },
                {
                    "id": "old-1",
                    "title": "Pocket older item",
                    "state": "completed",
                    "created_at": "2026-05-01T09:00:00Z",
                    "updated_at": "2026-05-01T09:01:00Z",
                    "recording_at": "2026-05-01T09:00:00Z",
                },
            ],
            "pagination": {"total": 2, "has_more": False},
        },
    )

    monkeypatch.setattr(
        product_service,
        "_pocket_get_recording_details",
        lambda recording_id: {
            "success": True,
            "data": {
                "id": recording_id,
                "title": f"Pocket {recording_id}",
                "state": "completed",
                "duration": 18.0,
                "language": "en",
                "recording_at": "2026-05-01T09:00:00Z",
                "created_at": "2026-05-01T09:00:10Z",
                "updated_at": "2026-05-01T09:11:00Z" if recording_id == "new-1" else "2026-05-01T09:01:00Z",
                "tags": ["ops"],
                "transcript": {
                    "text": "Review the notes and send the follow-up today.",
                    "segments": [{"start": 0.0, "end": 1.0, "text": "Review the notes."}],
                    "metadata": {"source": "api"},
                },
                "summarizations": {
                    f"summary-{recording_id}": {
                        "id": f"summary-{recording_id}",
                        "v2": {"summary": {"markdown": "Review the notes and send the follow-up today."}},
                    }
                },
            },
        },
    )

    first_sync = client.post("/app/api/signals/pocket/sync", params={"limit": 1})
    assert first_sync.status_code == 200
    assert first_sync.json()["cursor_recording_id"] == "new-1"

    reset = client.post("/app/api/signals/pocket/reset-cursor", json={"reason": "historical replay"})
    assert reset.status_code == 200
    reset_body = reset.json()
    assert reset_body["cursor_cleared"] is True
    assert reset_body["reason"] == "historical replay"
    assert reset_body["cursor_recording_id"] == ""

    replay = client.post("/app/api/signals/pocket/sync", params={"limit": 5})
    assert replay.status_code == 200
    replay_body = replay.json()
    assert replay_body["mode"] == "incremental"
    assert replay_body["total"] == 2
    assert replay_body["synced_total"] == 1
    assert replay_body["deduplicated_total"] == 1
    assert replay_body["cursor_recording_id"] == "new-1"


def test_pocket_api_sync_surfaces_rate_limits(monkeypatch) -> None:
    principal_id = "exec-product-pocket-sync-rate-limit"
    client = build_product_client(principal_id=principal_id)
    seed_product_state(client, principal_id=principal_id)

    def _raise_rate_limit(*, limit, page=1):
        raise RuntimeError('pocket_api_http_429:{"success":false,"error":"rate limit exceeded"}')

    monkeypatch.setattr(product_service, "_pocket_list_recordings", _raise_rate_limit)

    synced = client.post("/app/api/signals/pocket/sync", params={"limit": 5})
    assert synced.status_code == 429
    assert "rate limit exceeded" in synced.json()["error"]["details"]


def test_pocket_recording_detail_returns_transcript_summary_and_audio(monkeypatch) -> None:
    principal_id = "exec-product-pocket-detail"
    client = build_product_client(principal_id=principal_id)
    seed_product_state(client, principal_id=principal_id)

    monkeypatch.setattr(
        product_service,
        "_pocket_get_recording_details",
        lambda recording_id: {
            "success": True,
            "data": {
                "id": recording_id,
                "title": "Pocket detail item",
                "state": "completed",
                "duration": 25.0,
                "language": "en",
                "recording_at": "2026-05-01T07:00:00Z",
                "created_at": "2026-05-01T07:00:10Z",
                "updated_at": "2026-05-01T07:00:20Z",
                "tags": ["detail"],
                "transcript": {
                    "text": "Transcript body",
                    "segments": [{"start": 0.0, "end": 1.0, "text": "Transcript body"}],
                    "metadata": {"source": "api"},
                },
                "summarizations": {
                    "summary-9": {
                        "summarizationId": "summary-9",
                        "v2": {"summary": {"markdown": "Summary body"}},
                    }
                },
            },
        },
    )
    monkeypatch.setattr(
        product_service,
        "_pocket_get_audio_download_url",
        lambda recording_id: {
            "success": True,
            "data": {
                "signed_url": f"https://audio.example/{recording_id}.mp3",
                "expires_at": "2026-05-01T08:00:00Z",
                "expires_in": 3600,
            },
        },
    )

    detail = client.get("/app/api/signals/pocket/recordings/rec-9")
    assert detail.status_code == 200
    body = detail.json()
    assert body["recording_id"] == "rec-9"
    assert body["transcript_text"] == "Transcript body"
    assert body["transcript_segment_count"] == 1
    assert body["summary_markdown"] == "Summary body"
    assert body["summary_id"] == "summary-9"
    assert body["audio_download_url"] == "https://audio.example/rec-9.mp3"
    assert body["audio_expires_at"] == "2026-05-01T08:00:00Z"


def test_approving_signal_reply_draft_promotes_linked_commitment_candidate() -> None:
    principal_id = "exec-product-signal-draft-approve"
    client = build_product_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Signal Draft Approval Office")

    signal = client.post(
        "/app/api/signals/ingest",
        json={
            "signal_type": "email_thread",
            "channel": "gmail",
            "title": "Board packet follow-up",
            "summary": "Send revised board packet to Sofia by EOD.",
            "text": "Send revised board packet to Sofia by EOD.",
            "counterparty": "Sofia N.",
            "source_ref": "gmail-thread:signal-draft-approve",
            "external_id": "gmail-message:signal-draft-approve",
            "payload": {"from_email": "sofia@example.com", "from_name": "Sofia N."},
        },
    )
    assert signal.status_code == 200
    signal_body = signal.json()
    draft_ref = signal_body["staged_drafts"][0]["id"]
    candidate_id = signal_body["staged_candidates"][0]["candidate_id"]

    pending_before = client.get("/app/api/commitments/candidates", params={"status": "pending"})
    assert pending_before.status_code == 200
    assert candidate_id in pending_before.text

    approved = client.post(
        f"/app/api/drafts/{draft_ref}/approve",
        json={"reason": "Send it and track the follow-up."},
    )
    assert approved.status_code == 200
    approved_body = approved.json()
    assert approved_body["id"] == draft_ref
    assert approved_body["approval_status"] == "approved"

    pending_after = client.get("/app/api/commitments/candidates", params={"status": "pending"})
    assert pending_after.status_code == 200
    assert candidate_id not in pending_after.text

    commitments = client.get("/app/api/commitments")
    assert commitments.status_code == 200
    promoted = next(item for item in commitments.json() if "board packet" in str(item.get("statement") or "").lower())
    assert promoted["source_ref"] == "gmail-thread:signal-draft-approve"
    assert promoted["channel_hint"] == "gmail"

    events = client.get("/app/api/events")
    assert events.status_code == 200
    approved_event = next(item for item in events.json()["items"] if item["event_type"] == "draft_approved" and item["source_id"] == draft_ref.split(":", 1)[1])
    assert candidate_id in approved_event["payload"]["accepted_candidate_ids"]
    assert approved_event["payload"]["delivery"]["status"] == "skipped"
    assert approved_event["payload"]["delivery"]["reason"].startswith("google_")
    assert approved_event["payload"]["followup_ref"].startswith("human_task:")
    assert approved_event["payload"]["source_ref"] == "gmail-thread:signal-draft-approve"
    assert approved_event["payload"]["thread_ref"] == "gmail-thread:signal-draft-approve"

    handoffs = client.get("/app/api/handoffs")
    assert handoffs.status_code == 200
    assert any(item["id"] == approved_event["payload"]["followup_ref"] for item in handoffs.json())

    threads = client.get("/app/api/threads")
    assert threads.status_code == 200
    projected_thread = next(item for item in threads.json()["items"] if item["id"] == "thread:gmail-thread:signal-draft-approve")
    assert projected_thread["status"] == "delivery_followup"

    thread_history = client.get("/app/api/threads/gmail-thread:signal-draft-approve/history")
    assert thread_history.status_code == 200
    assert any(row["event_type"] == "draft_send_followup_created" for row in thread_history.json())


def test_approving_signal_reply_draft_records_gmail_send_when_delivery_succeeds(monkeypatch) -> None:
    principal_id = "exec-product-signal-draft-send"
    client = build_product_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Signal Draft Send Office")
    stakeholder = client.app.state.container.memory_runtime.upsert_stakeholder(
        principal_id=principal_id,
        display_name="Sofia N.",
        channel_ref="sofia@example.com",
        authority_level="board",
        importance="high",
        tone_pref="direct",
        open_loops_json={"board_packet": True},
        friction_points_json={},
        last_interaction_at="2026-03-29T08:45:00+00:00",
    )
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        google_oauth_service,
        "send_google_gmail_message",
        lambda **kwargs: captured.update(kwargs) or google_oauth_service.GoogleGmailSendResult(
            binding=None,
            sender_email="tibor@myexternalbrain.com",
            recipient_email="sofia@example.com",
            subject="Re: Board packet follow-up",
            rfc822_message_id="<ea-draft-test@ea.local>",
            gmail_message_id="gmail-sent-123",
            sent_at="2026-03-29T09:30:00Z",
        ),
    )

    signal = client.post(
        "/app/api/signals/ingest",
        json={
            "signal_type": "email_thread",
            "channel": "gmail",
            "title": "Board packet follow-up",
            "summary": "Send revised board packet to Sofia by EOD.",
            "text": "Send revised board packet to Sofia by EOD.",
            "counterparty": "Sofia N.",
            "stakeholder_id": stakeholder.stakeholder_id,
            "source_ref": "gmail-thread:signal-draft-send",
            "external_id": "gmail-message:signal-draft-send",
            "payload": {
                "from_email": "sofia@example.com",
                "from_name": "Sofia N.",
                "thread_id": "thread-123",
                "message_id": "message-123",
                "rfc822_message_id": "<sofia-thread@example.com>",
                "references": "<older@example.com> <sofia-thread@example.com>",
            },
        },
    )
    assert signal.status_code == 200
    signal_body = signal.json()
    draft_ref = signal_body["staged_drafts"][0]["id"]

    approved = client.post(
        f"/app/api/drafts/{draft_ref}/approve",
        json={"reason": "Send it now."},
    )
    assert approved.status_code == 200

    events = client.get("/app/api/events")
    assert events.status_code == 200
    sent_event = next(item for item in events.json()["items"] if item["event_type"] == "draft_sent")
    assert sent_event["payload"]["recipient_email"] == "sofia@example.com"
    assert sent_event["payload"]["gmail_message_id"] == "gmail-sent-123"
    assert sent_event["payload"]["subject"] == "Re: Board packet follow-up"
    assert sent_event["payload"]["source_ref"] == "gmail-thread:signal-draft-send"
    assert sent_event["payload"]["thread_ref"] == "gmail-thread:signal-draft-send"
    assert captured["reply_to_message_id"] == "<sofia-thread@example.com>"
    assert captured["references"] == "<older@example.com> <sofia-thread@example.com>"

    approved_event = next(item for item in events.json()["items"] if item["event_type"] == "draft_approved")
    assert approved_event["payload"]["delivery"]["status"] == "sent"
    assert approved_event["payload"]["delivery"]["gmail_message_id"] == "gmail-sent-123"
    assert approved_event["payload"]["followup_ref"] == ""

    threads = client.get("/app/api/threads")
    assert threads.status_code == 200
    projected_thread = next(item for item in threads.json()["items"] if item["id"] == "thread:gmail-thread:signal-draft-send")
    assert projected_thread["status"] == "sent"

    thread_history = client.get("/app/api/threads/gmail-thread:signal-draft-send/history")
    assert thread_history.status_code == 200
    assert any(row["event_type"] == "draft_sent" for row in thread_history.json())

    person_detail = client.get(f"/app/api/people/{stakeholder.stakeholder_id}/detail")
    assert person_detail.status_code == 200
    assert any(item["id"] == "thread:gmail-thread:signal-draft-send" for item in person_detail.json()["threads"])
    assert any(item["event_type"] == "draft_sent" for item in person_detail.json()["history"])


def test_approving_signal_reply_draft_uses_originating_google_inbox_binding(monkeypatch) -> None:
    principal_id = "exec-product-signal-draft-send-secondary"
    client = build_product_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Signal Draft Secondary Inbox")
    stakeholder = client.app.state.container.memory_runtime.upsert_stakeholder(
        principal_id=principal_id,
        display_name="Sofia N.",
        channel_ref="sofia@example.com",
        authority_level="board",
        importance="high",
        tone_pref="direct",
        open_loops_json={"board_packet": True},
        friction_points_json={},
        last_interaction_at="2026-03-29T08:45:00+00:00",
    )

    monkeypatch.setattr(
        google_oauth_service,
        "list_google_accounts",
        lambda **kwargs: [
            google_oauth_service.GoogleOAuthAccount(
                binding=google_oauth_service.ProviderBindingRecord(
                    binding_id="exec-product-signal-draft-send-secondary:google_gmail:acct:google-sub-2",
                    principal_id=principal_id,
                    provider_key="google_gmail",
                    status="enabled",
                    priority=80,
                    probe_state="ready",
                    probe_details_json={},
                    scope_json={"bundle": "core"},
                    auth_metadata_json={"google_email": "office@girschele.com"},
                    created_at="2026-03-29T08:00:00Z",
                    updated_at="2026-03-29T08:00:00Z",
                ),
                connector_binding=None,
                google_email="office@girschele.com",
                google_subject="google-sub-2",
                google_hosted_domain="girschele.com",
                granted_scopes=(
                    google_oauth_service.GOOGLE_SCOPE_SEND,
                    google_oauth_service.GOOGLE_SCOPE_METADATA,
                ),
                consent_stage="verify",
                workspace_mode="user_oauth",
                token_status="active",
                last_refresh_at="2026-03-29T08:00:00Z",
                reauth_required_reason="",
            )
        ],
    )

    captured: dict[str, object] = {}

    monkeypatch.setattr(
        google_oauth_service,
        "send_google_gmail_message",
        lambda **kwargs: captured.update(kwargs) or google_oauth_service.GoogleGmailSendResult(
            binding=None,
            sender_email="office@girschele.com",
            recipient_email="sofia@example.com",
            subject="Re: Board packet follow-up",
            rfc822_message_id="<ea-draft-test-secondary@ea.local>",
            gmail_message_id="gmail-sent-secondary",
            sent_at="2026-03-29T09:30:00Z",
        ),
    )

    signal = client.post(
        "/app/api/signals/ingest",
        json={
            "signal_type": "email_thread",
            "channel": "gmail",
            "title": "Board packet follow-up",
            "summary": "Send revised board packet to Sofia by EOD.",
            "text": "Send revised board packet to Sofia by EOD.",
            "counterparty": "Sofia N.",
            "stakeholder_id": stakeholder.stakeholder_id,
            "source_ref": "gmail-thread:office@girschele.com:signal-draft-send",
            "external_id": "gmail-message:office@girschele.com:signal-draft-send",
            "payload": {
                "account_email": "office@girschele.com",
                "from_email": "sofia@example.com",
                "from_name": "Sofia N.",
                "thread_id": "thread-123",
                "message_id": "message-123",
                "rfc822_message_id": "<sofia-thread@example.com>",
                "references": "<older@example.com> <sofia-thread@example.com>",
            },
        },
    )
    assert signal.status_code == 200
    draft_ref = signal.json()["staged_drafts"][0]["id"]

    approved = client.post(
        f"/app/api/drafts/{draft_ref}/approve",
        json={"reason": "Send it now."},
    )
    assert approved.status_code == 200
    assert captured["binding_id"] == "exec-product-signal-draft-send-secondary:google_gmail:acct:google-sub-2"

    events = client.get("/app/api/events")
    assert events.status_code == 200
    sent_event = next(item for item in events.json()["items"] if item["event_type"] == "draft_sent")
    assert sent_event["payload"]["sender_email"] == "office@girschele.com"
    assert sent_event["payload"]["google_binding_id"] == "exec-product-signal-draft-send-secondary:google_gmail:acct:google-sub-2"
    assert sent_event["payload"]["google_account_email"] == "office@girschele.com"


def test_queue_approval_resolution_uses_draft_delivery_runtime() -> None:
    principal_id = "exec-product-queue-draft-delivery"
    client = build_product_client(principal_id=principal_id)
    seeded = seed_product_state(client, principal_id=principal_id)
    draft_ref = f"approval:{seeded['approval_id']}"

    resolved = client.post(
        f"/app/api/queue/{draft_ref}/resolve",
        json={"action": "approve", "reason": "Approve from queue"},
    )
    assert resolved.status_code == 200
    assert resolved.json()["resolution_state"] == "approved"

    events = client.get("/app/api/events")
    assert events.status_code == 200
    approved_event = next(item for item in events.json()["items"] if item["event_type"] == "draft_approved")
    assert approved_event["payload"]["delivery"]["status"] == "skipped"
    assert approved_event["payload"]["followup_ref"].startswith("human_task:")
    assert any(item["event_type"] == "draft_send_followup_created" for item in events.json()["items"])

    handoffs = client.get("/app/api/handoffs")
    assert handoffs.status_code == 200
    followup = next(item for item in handoffs.json() if item["id"] == approved_event["payload"]["followup_ref"])
    assert followup["task_type"] == "delivery_followup"
    assert followup["draft_ref"] == draft_ref


def test_delivery_followup_completion_can_record_manual_send() -> None:
    principal_id = "exec-product-delivery-followup-sent"
    client = build_operator_product_client(principal_id=principal_id, operator_id="operator-office")
    seeded = seed_product_state(client, principal_id=principal_id)

    approved = client.post(
        f"/app/api/drafts/approval:{seeded['approval_id']}/approve",
        json={"reason": "Approve and route to manual send"},
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
    assert assigned.json()["owner"] == seeded["operator_id"]

    completed = client.post(
        f"/app/api/handoffs/{followup['id']}/complete",
        json={"operator_id": seeded["operator_id"], "resolution": "sent"},
    )
    assert completed.status_code == 200
    assert completed.json()["resolution"] == "sent"

    events = client.get("/app/api/events")
    assert events.status_code == 200
    resolved_event = next(item for item in events.json()["items"] if item["event_type"] == "draft_send_followup_resolved")
    assert resolved_event["payload"]["draft_ref"] == f"approval:{seeded['approval_id']}"
    sent_event = next(item for item in events.json()["items"] if item["event_type"] == "draft_sent")
    assert sent_event["payload"]["delivery_mode"] == "manual_followup"
    assert sent_event["payload"]["draft_ref"] == f"approval:{seeded['approval_id']}"
    outcomes = client.get("/app/api/outcomes")
    assert outcomes.status_code == 200
    outcomes_body = outcomes.json()
    assert outcomes_body["approval_coverage_rate"] == 1.0
    assert outcomes_body["approval_action_rate"] == 1.0
    assert outcomes_body["delivery_followup_closeout_count"] == 1
    assert outcomes_body["delivery_followup_blocked_count"] == 0
    assert outcomes_body["delivery_followup_resolution_rate"] == 1.0
    assert outcomes_body["delivery_followup_blocked_rate"] == 0.0


def test_delivery_followup_completion_can_record_reauth_needed() -> None:
    principal_id = "exec-product-delivery-followup-reauth"
    client = build_operator_product_client(principal_id=principal_id, operator_id="operator-office")
    seeded = seed_product_state(client, principal_id=principal_id)

    approved = client.post(
        f"/app/api/drafts/approval:{seeded['approval_id']}/approve",
        json={"reason": "Approve and route to manual send"},
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
        json={"operator_id": seeded["operator_id"], "resolution": "reauth_needed"},
    )
    assert completed.status_code == 200
    assert completed.json()["resolution"] == "reauth_needed"

    events = client.get("/app/api/events")
    assert events.status_code == 200
    assert any(item["event_type"] == "draft_send_reauth_needed" for item in events.json()["items"])
    outcomes = client.get("/app/api/outcomes")
    assert outcomes.status_code == 200
    outcomes_body = outcomes.json()
    assert outcomes_body["approval_coverage_rate"] == 1.0
    assert outcomes_body["approval_action_rate"] == 0.0
    assert outcomes_body["delivery_followup_closeout_count"] == 0
    assert outcomes_body["delivery_followup_blocked_count"] == 1
    assert outcomes_body["delivery_followup_resolution_rate"] == 0.0
    assert outcomes_body["delivery_followup_blocked_rate"] == 1.0


def test_delivery_followup_completion_can_record_waiting_on_principal() -> None:
    principal_id = "exec-product-delivery-followup-waiting"
    client = build_operator_product_client(principal_id=principal_id, operator_id="operator-office")
    seeded = seed_product_state(client, principal_id=principal_id)

    approved = client.post(
        f"/app/api/drafts/approval:{seeded['approval_id']}/approve",
        json={"reason": "Approve and route to manual send"},
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
    assert completed.json()["resolution"] == "waiting_on_principal"

    events = client.get("/app/api/events")
    assert events.status_code == 200
    assert any(item["event_type"] == "draft_send_waiting_on_principal" for item in events.json()["items"])
    outcomes = client.get("/app/api/outcomes")
    assert outcomes.status_code == 200
    outcomes_body = outcomes.json()
    assert outcomes_body["approval_coverage_rate"] == 1.0
    assert outcomes_body["approval_action_rate"] == 0.0
    assert outcomes_body["delivery_followup_closeout_count"] == 0
    assert outcomes_body["delivery_followup_blocked_count"] == 1
    assert outcomes_body["delivery_followup_resolution_rate"] == 0.0
    assert outcomes_body["delivery_followup_blocked_rate"] == 1.0

    handoff_page = client.get(f"/app/handoffs/{followup['id']}")
    assert handoff_page.status_code == 200
    assert "Waiting on principal" in handoff_page.text


def test_thread_delivery_followup_can_be_resumed_via_product_api() -> None:
    principal_id = "exec-product-thread-resume-followup"
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

    resumed = client.post(
        f"/app/api/threads/{thread_id}/resume-delivery",
        json={"operator_id": seeded["operator_id"]},
    )
    assert resumed.status_code == 200
    assert resumed.json()["task_type"] == "delivery_followup"
    assert resumed.json()["draft_ref"] == f"approval:{seeded['approval_id']}"
    assert resumed.json()["owner"] == seeded["operator_id"]

    pending_handoffs = client.get("/app/api/handoffs")
    assert pending_handoffs.status_code == 200
    reopened = next(item for item in pending_handoffs.json() if item["task_type"] == "delivery_followup")
    assert reopened["draft_ref"] == f"approval:{seeded['approval_id']}"

    thread_history = client.get(f"/app/api/threads/{thread_id}/history")
    assert thread_history.status_code == 200
    assert any(row["event_type"] == "draft_send_followup_reopened" for row in thread_history.json())


def test_delivery_followup_retry_send_reuses_saved_draft_payload(monkeypatch) -> None:
    principal_id = "exec-product-delivery-followup-retry"
    client = build_operator_product_client(principal_id=principal_id, operator_id="operator-office")
    seeded = seed_product_state(client, principal_id=principal_id)

    attempts: list[dict[str, object]] = []

    def _fake_send(**kwargs):
        attempts.append(dict(kwargs))
        if len(attempts) == 1:
            raise RuntimeError("google_oauth_binding_not_found")
        return google_oauth_service.GoogleGmailSendResult(
            binding=None,
            sender_email="ea@example.com",
            recipient_email=str(kwargs.get("recipient_email") or ""),
            subject=str(kwargs.get("subject") or ""),
            rfc822_message_id="<retry-send@example.com>",
            gmail_message_id="gmail-retry-1",
            sent_at="2026-03-29T10:00:00+00:00",
        )

    monkeypatch.setattr(google_oauth_service, "send_google_gmail_message", _fake_send)

    approved = client.post(
        f"/app/api/drafts/approval:{seeded['approval_id']}/approve",
        json={"reason": "Approve and retry through EA"},
    )
    assert approved.status_code == 200

    handoffs = client.get("/app/api/handoffs")
    assert handoffs.status_code == 200
    followup = next(item for item in handoffs.json() if item["task_type"] == "delivery_followup")

    retried = client.post(
        f"/app/api/handoffs/{followup['id']}/retry-send",
        json={"operator_id": seeded["operator_id"]},
    )
    assert retried.status_code == 200
    assert retried.json()["resolution"] == "sent"
    assert len(attempts) == 2
    assert attempts[1]["recipient_email"] == "sofia@example.com"
    assert attempts[1]["body_text"] == "Draft board reply"

    events = client.get("/app/api/events")
    assert events.status_code == 200
    retry_event = next(item for item in events.json()["items"] if item["event_type"] == "draft_send_retry_attempted")
    assert retry_event["payload"]["status"] == "sent"
    sent_event = next(item for item in events.json()["items"] if item["event_type"] == "draft_sent")
    assert sent_event["payload"]["delivery_mode"] == "retry_send"
    assert sent_event["payload"]["sender_email"] == "ea@example.com"

    outcomes = client.get("/app/api/outcomes")
    assert outcomes.status_code == 200
    outcomes_body = outcomes.json()
    assert outcomes_body["approval_action_rate"] == 1.0

    handoff_page = client.get(f"/app/handoffs/{followup['id']}")
    assert handoff_page.status_code == 200
    assert "Retry send completed." in handoff_page.text
    assert "Connect Google" not in handoff_page.text


def test_delivery_followup_surfaces_retry_connect_and_manual_send_actions_in_operator_views() -> None:
    principal_id = "exec-product-delivery-action-surfaces"
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

    loop = client.get("/app/api/channel-loop")
    assert loop.status_code == 200
    operator_digest = next(item for item in loop.json()["digests"] if item["key"] == "operator")
    handoff_item = next(item for item in operator_digest["items"] if item["href"] == f"/app/handoffs/{followup['id']}")
    assert handoff_item["action_label"] == "Retry send"
    assert "/app/channel-actions/" in handoff_item["action_href"]
    assert handoff_item["secondary_action_label"] in {"Connect Google", "Reconnect Google"}
    assert handoff_item["secondary_action_href"].endswith("return_to=/app/channel-loop/operator")
    assert handoff_item["tertiary_action_label"] == "Mark sent"
    assert "/app/channel-actions/" in handoff_item["tertiary_action_href"]
    assert handoff_item["quaternary_action_label"] == "Waiting on principal"
    assert "/app/channel-actions/" in handoff_item["quaternary_action_href"]

    center = client.get("/app/api/operator-center")
    assert center.status_code == 200
    next_action = next(item for item in center.json()["next_actions"] if item["label"] == followup["summary"])
    assert next_action["action_label"] == "Retry send"
    assert next_action["secondary_action_label"] in {"Connect Google", "Reconnect Google"}
    assert next_action["tertiary_action_label"] == "Mark sent"
    assert next_action["quaternary_action_label"] == "Waiting on principal"


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
                    text="Please send the board prep agenda to Sofia before the memo review.",
                    source_ref="calendar-event:prep-1",
                    external_id="calendar-event:prep-1",
                    counterparty="Sofia N.",
                    due_at="2026-03-28T09:00:00+00:00",
                    payload={"event_id": "prep-1", "description": "Please send the board prep agenda to Sofia before the memo review."},
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
    gmail_item = next(item for item in body["items"] if item["channel"] == "gmail")
    assert gmail_item["ooda_loop"]["reviewed"] is True
    assert gmail_item["ooda_loop"]["observe"]["signal_type"] == "email_thread"

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
    deduplicated_gmail = next(item for item in deduplicated_body["items"] if item["channel"] == "gmail")
    assert deduplicated_gmail["staged_count"] >= 1
    assert deduplicated_gmail["draft_count"] >= 1
    assert deduplicated_gmail["ooda_loop"]["reviewed"] is True
    diagnostics = client.get("/app/api/usage")
    assert diagnostics.status_code == 200
    sync_analytics = diagnostics.json()["analytics"]["sync"]
    assert sync_analytics["google_account_email"] == "exec@example.com"
    assert sync_analytics["google_sync_freshness_state"] == "clear"
    assert sync_analytics["google_sync_last_completed_at"]
    assert sync_analytics["pending_commitment_candidates"] <= 1
    assert sync_analytics["covered_signal_candidates"] >= 1
    sync_status = client.get("/app/api/signals/google/status")
    assert sync_status.status_code == 200
    sync_status_body = sync_status.json()
    assert sync_status_body["connected"] is True
    assert sync_status_body["account_email"] == "exec@example.com"
    assert sync_status_body["freshness_state"] == "clear"
    assert sync_status_body["last_completed_at"]
    assert sync_status_body["pending_commitment_candidates"] <= 1
    assert sync_status_body["covered_signal_candidates"] >= 1

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


def test_google_signal_sync_suppresses_low_signal_calendar_and_promotional_noise(monkeypatch) -> None:
    principal_id = "exec-product-google-noise"
    monkeypatch.setenv("EA_REGISTRATION_EMAIL_FROM", "kleinhirn@girschele.com")
    client = build_product_client(principal_id=principal_id)
    seed_product_state(client, principal_id=principal_id)

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
                    signal_type="calendar_note",
                    channel="calendar",
                    title="ADHS psychiater",
                    summary="Starts 2026-03-30T09:00:00+00:00",
                    text="ADHS psychiater",
                    source_ref="calendar-event:self-1",
                    external_id="calendar-event:self-1",
                    counterparty="",
                    due_at="2026-03-30T09:00:00+00:00",
                    payload={
                        "event_id": "self-1",
                        "attendees": ["exec@example.com"],
                        "organizer": "exec@example.com",
                        "account_email": "exec@example.com",
                        "description": "",
                    },
                ),
                google_oauth_service.GoogleWorkspaceSignal(
                    signal_type="email_thread",
                    channel="gmail",
                    title="Mit dem Omni-Plan deutlich mehr erhalten: Blitzangebot",
                    summary="MyHeritage promotional message",
                    text="Mit dem Omni-Plan deutlich mehr erhalten: Blitzangebot",
                    source_ref="gmail-thread:promo-1",
                    external_id="gmail-message:promo-1",
                    counterparty="MyHeritage.com",
                    due_at=None,
                    payload={
                        "thread_id": "promo-1",
                        "message_id": "promo-1",
                        "from_email": "offers@myheritage.com",
                        "labels": ["INBOX", "CATEGORY_PROMOTIONS"],
                    },
                ),
                google_oauth_service.GoogleWorkspaceSignal(
                    signal_type="calendar_note",
                    channel="calendar",
                    title="Boulderbar noah kurs",
                    summary="Starts 2026-04-01T13:00:00+00:00",
                    text="Boulderbar noah kurs Attendees: elisabeth.girschele@gmail.com",
                    source_ref="calendar-event:meeting-1",
                    external_id="calendar-event:meeting-1",
                    counterparty="elisabeth.girschele@gmail.com",
                    due_at="2026-04-01T13:00:00+00:00",
                    payload={
                        "event_id": "meeting-1",
                        "attendees": ["elisabeth.girschele@gmail.com"],
                        "organizer": "exec@example.com",
                        "account_email": "exec@example.com",
                        "description": "",
                    },
                ),
                google_oauth_service.GoogleWorkspaceSignal(
                    signal_type="email_thread",
                    channel="gmail",
                    title="Morning memo digest",
                    summary="Open this secure workspace view and review the current office loop.",
                    text="Morning memo digest Open this secure workspace view and review the current office loop.",
                    source_ref="gmail-thread:memo-1",
                    external_id="gmail-message:memo-1",
                    counterparty="Kleinhirn",
                    due_at=None,
                    payload={
                        "thread_id": "memo-1",
                        "message_id": "memo-1",
                        "from_email": "kleinhirn@girschele.com",
                        "from_name": "Kleinhirn",
                        "snippet": "Open this secure workspace view and review the current office loop.",
                        "labels": ["INBOX"],
                    },
                ),
                google_oauth_service.GoogleWorkspaceSignal(
                    signal_type="email_thread",
                    channel="gmail",
                    title="Investor follow-up",
                    summary="Please send the revised board packet tomorrow morning.",
                    text="Please send the revised board packet tomorrow morning.",
                    source_ref="gmail-thread:action-1",
                    external_id="gmail-message:action-1",
                    counterparty="Sofia N.",
                    due_at=None,
                    payload={
                        "thread_id": "action-1",
                        "message_id": "action-1",
                        "from_email": "sofia@example.com",
                        "labels": ["INBOX"],
                    },
                ),
            ),
        ),
    )

    synced = client.post("/app/api/signals/google/sync", params={"email_limit": 5, "calendar_limit": 5})
    assert synced.status_code == 200
    body = synced.json()
    assert body["total"] == 4
    assert body["suppressed_total"] == 1

    self_calendar = next(item for item in body["items"] if item["source_id"] == "calendar-event:self-1")
    meeting_calendar = next(item for item in body["items"] if item["source_id"] == "calendar-event:meeting-1")
    memo_email = next(item for item in body["items"] if item["source_id"] == "gmail-thread:memo-1")
    actionable_email = next(item for item in body["items"] if item["source_id"] == "gmail-thread:action-1")

    assert self_calendar["staged_count"] == 0
    assert meeting_calendar["staged_count"] == 0
    assert memo_email["staged_count"] == 0
    assert actionable_email["staged_count"] >= 1

    candidates = client.get("/app/api/commitments/candidates", params={"status": "pending"})
    assert candidates.status_code == 200
    titles = {item["title"] for item in candidates.json()}
    assert "ADHS psychiater" not in titles
    assert "Boulderbar noah kurs" not in titles
    assert "Mit dem Omni-Plan deutlich mehr erhalten: Blitzangebot" not in titles
    assert "Morning memo digest" not in titles
    assert any("board packet" in title.lower() for title in titles)
    assert not any(item["source_id"] == "gmail-thread:promo-1" for item in body["items"])

    sync_status = client.get("/app/api/signals/google/status")
    assert sync_status.status_code == 200
    sync_status_body = sync_status.json()
    assert sync_status_body["last_suppressed_total"] == 1


def test_google_signal_sync_retires_preexisting_assistant_generated_candidate(monkeypatch) -> None:
    principal_id = "exec-product-google-memo-self-heal"
    monkeypatch.setenv("EA_REGISTRATION_EMAIL_FROM", "kleinhirn@girschele.com")
    client = build_product_client(principal_id=principal_id)
    seed_product_state(client, principal_id=principal_id)

    title = "Morning memo digest"
    summary = "Open this secure workspace view and review the current office loop."
    text = "Morning memo digest Open this secure workspace view and review the current office loop."
    source_ref = "gmail-thread:memo-legacy"
    external_id = "gmail-message:memo-legacy"
    dedupe_key = "|".join(
        part
        for part in (
            "office-signal",
            principal_id,
            "email_thread",
            external_id,
            source_ref,
            text[:80],
        )
        if part
    )

    client.app.state.container.memory_runtime.stage_candidate(
        principal_id=principal_id,
        category="product_commitment_candidate",
        summary=title,
        fact_json={
            "title": title,
            "details": summary,
            "source_text": text,
            "counterparty": "Kleinhirn",
            "channel_hint": "gmail",
            "source_ref": source_ref,
            "signal_type": "email_thread",
            "kind": "commitment",
        },
    )
    client.app.state.container.channel_runtime.ingest_observation(
        principal_id=principal_id,
        channel="gmail",
        event_type="office_signal_email_thread",
        payload={
            "title": title,
            "summary": summary,
            "text": text,
            "from_email": "kleinhirn@girschele.com",
            "snippet": summary,
        },
        source_id=source_ref,
        external_id=external_id,
        dedupe_key=dedupe_key,
    )

    ingested = client.post(
        "/app/api/signals/ingest",
        json={
            "signal_type": "email_thread",
            "channel": "gmail",
            "title": title,
            "summary": summary,
            "text": text,
            "source_ref": source_ref,
            "external_id": external_id,
            "counterparty": "Kleinhirn",
            "payload": {
                "from_email": "kleinhirn@girschele.com",
                "snippet": summary,
                "labels": ["INBOX"],
            },
        },
    )
    assert ingested.status_code == 200
    assert ingested.json()["deduplicated"] is True
    assert ingested.json()["staged_count"] == 0

    candidates = client.get("/app/api/commitments/candidates", params={"status": "pending"})
    assert candidates.status_code == 200
    assert "Morning memo digest" not in {item["title"] for item in candidates.json()}

    diagnostics = client.get("/app/api/diagnostics")
    assert diagnostics.status_code == 200
    assert int(diagnostics.json()["analytics"]["counts"].get("commitment_candidate_rejected") or 0) >= 1


def test_google_signal_sync_collapses_duplicate_gmail_threads(monkeypatch) -> None:
    principal_id = "exec-product-google-thread-dupes"
    client = build_product_client(principal_id=principal_id)
    seed_product_state(client, principal_id=principal_id)

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
                    summary="Please send the revised board packet tomorrow morning.",
                    text="Please send the revised board packet tomorrow morning.",
                    source_ref="gmail-thread:duplicate-1",
                    external_id="gmail-message:first",
                    due_at=None,
                    counterparty="Sofia N.",
                    payload={
                        "thread_id": "duplicate-1",
                        "message_id": "first",
                        "from_email": "sofia@example.com",
                        "labels": ["INBOX"],
                    },
                ),
                google_oauth_service.GoogleWorkspaceSignal(
                    signal_type="email_thread",
                    channel="gmail",
                    title="Investor follow-up (duplicate)",
                    summary="Another noisy duplicate of same Gmail thread.",
                    text="Another noisy duplicate of same Gmail thread.",
                    source_ref="gmail-thread:duplicate-1",
                    external_id="gmail-message:second",
                    due_at=None,
                    counterparty="Sofia N.",
                    payload={
                        "thread_id": "duplicate-1",
                        "message_id": "second",
                        "from_email": "sofia@example.com",
                        "labels": ["INBOX"],
                    },
                ),
            ),
        ),
    )

    synced = client.post("/app/api/signals/google/sync", params={"email_limit": 2, "calendar_limit": 0})
    assert synced.status_code == 200
    body = synced.json()
    assert body["total"] == 1
    assert body["synced_total"] == 1
    assert body["deduplicated_total"] == 0
    assert body["suppressed_total"] == 1
    assert all(item["deduplicated"] is False for item in body["items"] if item["source_id"] == "gmail-thread:duplicate-1")
    assert len(body["items"]) == 1

    candidates = client.get("/app/api/commitments/candidates")
    assert candidates.status_code == 200
    candidate = next(item for item in candidates.json() if item["source_ref"] == "gmail-thread:duplicate-1")
    assert candidate["source_ref"] == "gmail-thread:duplicate-1"

    drafts = client.get("/app/api/drafts")
    assert drafts.status_code == 200
    assert len(drafts.json()) >= 2
    assert any("investor follow-up" in str(item.get("draft_text") or "").lower() for item in drafts.json())
    assert candidate["kind"] == "commitment"

    events = client.get("/app/api/events")
    assert events.status_code == 200
    office_signal_events = [item for item in events.json()["items"] if item["event_type"] == "office_signal_email_thread"]
    assert any(item["source_id"] == "gmail-thread:duplicate-1" for item in office_signal_events)

    sync_status = client.get("/app/api/signals/google/status")
    assert sync_status.status_code == 200
    sync_status_body = sync_status.json()
    assert sync_status_body["last_synced_total"] == 1
    assert sync_status_body["last_deduplicated_total"] == 0
    assert sync_status_body["last_suppressed_total"] == 1


def test_google_signal_sync_collapses_duplicate_gmail_threads_by_thread_id(monkeypatch) -> None:
    principal_id = "exec-product-google-thread-dupes-thread-id"
    client = build_product_client(principal_id=principal_id)
    seed_product_state(client, principal_id=principal_id)

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
                    summary="Please send the revised board packet tomorrow morning.",
                    text="Please send the revised board packet tomorrow morning.",
                    source_ref="gmail-message:thread-first",
                    external_id="gmail-message:first",
                    due_at=None,
                    counterparty="Sofia N.",
                    payload={
                        "thread_id": "shared-thread-id",
                        "message_id": "first",
                        "from_email": "sofia@example.com",
                        "labels": ["INBOX"],
                    },
                ),
                google_oauth_service.GoogleWorkspaceSignal(
                    signal_type="email_thread",
                    channel="gmail",
                    title="Investor follow-up (duplicate thread)",
                    summary="Follow-up duplicate in same Gmail thread.",
                    text="Follow-up duplicate in same Gmail thread.",
                    source_ref="gmail-message:thread-second",
                    external_id="gmail-message:second",
                    due_at=None,
                    counterparty="Sofia N.",
                    payload={
                        "thread_id": "shared-thread-id",
                        "message_id": "second",
                        "from_email": "sofia@example.com",
                        "labels": ["INBOX"],
                    },
                ),
            ),
        ),
    )

    synced = client.post("/app/api/signals/google/sync", params={"email_limit": 2, "calendar_limit": 0})
    assert synced.status_code == 200
    body = synced.json()
    assert body["total"] == 1
    assert body["synced_total"] == 1
    assert body["deduplicated_total"] == 0
    assert body["suppressed_total"] == 1
    assert len(body["items"]) == 1

    sync_status = client.get("/app/api/signals/google/status")
    assert sync_status.status_code == 200
    sync_status_body = sync_status.json()
    assert sync_status_body["last_suppressed_total"] == 1


def test_google_signal_sync_status_tracks_per_account_sync_totals(monkeypatch) -> None:
    principal_id = "exec-product-google-account-sync-status"
    client = build_product_client(principal_id=principal_id)
    seed_product_state(client, principal_id=principal_id)

    monkeypatch.setattr(
        google_oauth_service,
        "list_recent_workspace_signals",
        lambda **_: google_oauth_service.GoogleWorkspaceSignalSync(
            account_email="tibor@girschele.com",
            account_emails=("tibor@girschele.com", "office@girschele.com"),
            granted_scopes=(
                google_oauth_service.GOOGLE_SCOPE_METADATA,
                google_oauth_service.GOOGLE_SCOPE_CALENDAR_READONLY,
            ),
            signals=(
                google_oauth_service.GoogleWorkspaceSignal(
                    signal_type="email_thread",
                    channel="gmail",
                    title="Founder follow-up",
                    summary="Send the board packet.",
                    text="Send the board packet.",
                    source_ref="gmail-thread:tibor@girschele.com:thread-1",
                    external_id="gmail-message:tibor@girschele.com:msg-1",
                    counterparty="Sofia N.",
                    due_at=None,
                    payload={
                        "thread_id": "thread-1",
                        "message_id": "msg-1",
                        "account_email": "tibor@girschele.com",
                        "labels": ["INBOX"],
                    },
                ),
                google_oauth_service.GoogleWorkspaceSignal(
                    signal_type="calendar_note",
                    channel="calendar",
                    title="Board prep",
                    summary="Starts 2026-03-28T09:00:00+00:00",
                    text="Board prep agenda due.",
                    source_ref="calendar-event:tibor@girschele.com:evt-1",
                    external_id="calendar-event:tibor@girschele.com:evt-1",
                    counterparty="Sofia N.",
                    due_at="2026-03-28T09:00:00+00:00",
                    payload={
                        "event_id": "evt-1",
                        "account_email": "tibor@girschele.com",
                    },
                ),
                google_oauth_service.GoogleWorkspaceSignal(
                    signal_type="email_thread",
                    channel="gmail",
                    title="Office request",
                    summary="Please review the follow-up.",
                    text="Please review the follow-up.",
                    source_ref="gmail-thread:office@girschele.com:thread-2",
                    external_id="gmail-message:office@girschele.com:msg-2",
                    counterparty="Ops Lead",
                    due_at=None,
                    payload={
                        "thread_id": "thread-2",
                        "message_id": "msg-2",
                        "account_email": "office@girschele.com",
                        "labels": ["INBOX"],
                    },
                ),
            ),
        ),
    )

    synced = client.post("/app/api/signals/google/sync", params={"email_limit": 5, "calendar_limit": 5})
    assert synced.status_code == 200

    sync_status = client.get("/app/api/signals/google/status")
    assert sync_status.status_code == 200
    sync_status_body = sync_status.json()
    account_rows = {row["account_email"]: row for row in sync_status_body["account_sync_accounts"]}
    assert account_rows["tibor@girschele.com"]["gmail_total"] == 1
    assert account_rows["tibor@girschele.com"]["calendar_total"] == 1
    assert account_rows["tibor@girschele.com"]["processed_total"] == 2
    assert account_rows["tibor@girschele.com"]["synced_total"] == 2
    assert account_rows["tibor@girschele.com"]["deduplicated_total"] == 0
    assert account_rows["tibor@girschele.com"]["suppressed_total"] == 0
    assert account_rows["office@girschele.com"]["gmail_total"] == 1
    assert account_rows["office@girschele.com"]["calendar_total"] == 0
    assert account_rows["office@girschele.com"]["processed_total"] == 1
    assert account_rows["office@girschele.com"]["synced_total"] == 1
    assert account_rows["office@girschele.com"]["suppressed_total"] == 0
def test_channel_loop_approvals_digest_counts_reviewable_candidates_not_rejected_history() -> None:
    principal_id = "exec-product-channel-loop-reviewable-candidates"
    client = build_product_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Reviewable Candidates Office")

    runtime = client.app.state.container.memory_runtime

    for index in range(3):
        runtime.stage_candidate(
            principal_id=principal_id,
            category="product_commitment_candidate",
            summary=f"Pending candidate {index + 1}",
            fact_json={
                "title": f"Pending candidate {index + 1}",
                "details": "Needs review.",
                "source_text": f"Pending candidate {index + 1}",
                "counterparty": "Sofia N.",
                "channel_hint": "gmail",
                "source_ref": f"gmail-thread:pending-{index + 1}",
                "signal_type": "email_thread",
                "kind": "commitment",
            },
        )

    for index in range(8):
        rejected = runtime.stage_candidate(
            principal_id=principal_id,
            category="product_commitment_candidate",
            summary=f"Rejected candidate {index + 1}",
            fact_json={
                "title": f"Rejected candidate {index + 1}",
                "details": "Already reviewed.",
                "source_text": f"Rejected candidate {index + 1}",
                "counterparty": "Archive",
                "channel_hint": "gmail",
                "source_ref": f"gmail-thread:rejected-{index + 1}",
                "signal_type": "email_thread",
                "kind": "commitment",
            },
        )
        runtime.reject_candidate(rejected.candidate_id, principal_id=principal_id, reviewer="operator-office")

    loop = client.get("/app/api/channel-loop")
    assert loop.status_code == 200
    approvals_digest = next(item for item in loop.json()["digests"] if item["key"] == "approvals")
    assert approvals_digest["stats"]["pending_commitment_candidates"] == 3
    candidate_items = [item for item in approvals_digest["items"] if item["tag"] == "Candidate"]
    assert len(candidate_items) == 2
    assert all("Pending candidate" in item["title"] for item in candidate_items)

    diagnostics = client.get("/app/api/diagnostics")
    assert diagnostics.status_code == 200
    assert diagnostics.json()["analytics"]["sync"]["pending_commitment_candidates"] == 3


def test_channel_loop_approvals_digest_can_accept_and_reject_signal_candidates() -> None:
    principal_id = "exec-product-channel-loop-candidates"
    client = build_product_client(principal_id=principal_id)
    seed_product_state(client, principal_id=principal_id)

    first_signal = client.post(
        "/app/api/signals/ingest",
        json={
            "signal_type": "email_thread",
            "channel": "gmail",
            "title": "Board packet deadline",
            "summary": "Board packet due for Sofia by EOD.",
            "text": "Board packet due for Sofia by EOD.",
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
            "title": "Investor note deadline",
            "summary": "Investor note due for Sofia today.",
            "text": "Investor note due for Sofia today.",
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
    listed_with_closed = client.get("/app/api/commitments", params={"include_closed": True})
    assert listed_with_closed.status_code == 200
    assert any(row["id"] == commitment_ref and row["status"] == "completed" for row in listed_with_closed.json())
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

    deferred = client.post(
        f"/app/api/commitments/{commitment_ref}/resolve",
        json={"action": "defer", "reason": "Waiting on the next board window"},
    )
    assert deferred.status_code == 200
    assert deferred.json()["status"] == "open"
    assert deferred.json()["resolution_code"] == "deferred"
    assert deferred.json()["resolution_reason"] == "Waiting on the next board window"

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

    decision_resolved_again = client.post(
        f"/app/api/decisions/decision:{seeded['decision_window_id']}/resolve",
        json={"action": "resolve", "reason": "Principal finalized the owner"},
    )
    assert decision_resolved_again.status_code == 200
    open_decisions = client.get("/app/api/decisions")
    assert open_decisions.status_code == 200
    assert all(item["id"] != f"decision:{seeded['decision_window_id']}" for item in open_decisions.json()["items"])
    decisions_with_closed = client.get("/app/api/decisions", params={"include_closed": True})
    assert decisions_with_closed.status_code == 200
    assert any(item["id"] == f"decision:{seeded['decision_window_id']}" and item["status"] == "decided" for item in decisions_with_closed.json()["items"])
    decision_search = client.get("/app/api/search", params={"query": "memo owner", "limit": 10})
    assert decision_search.status_code == 200
    reopened_decision = next(item for item in decision_search.json()["items"] if item["kind"] == "decision")
    assert reopened_decision["action_label"] == "Reopen"
    assert reopened_decision["action_value"] == "reopen"

    deadline_ref = f"deadline:{seeded['deadline_window_id']}"
    deadline_closed = client.post(
        f"/app/api/deadlines/{deadline_ref}/resolve",
        json={"action": "close", "reason": "Window covered in the queue"},
    )
    assert deadline_closed.status_code == 200
    assert deadline_closed.json()["status"] == "elapsed"
    deadline_detail = client.get(f"/app/api/deadlines/{deadline_ref}")
    assert deadline_detail.status_code == 200
    assert deadline_detail.json()["status"] == "elapsed"
    open_deadlines = client.get("/app/api/deadlines")
    assert open_deadlines.status_code == 200
    assert all(item["id"] != deadline_ref for item in open_deadlines.json()["items"])
    deadlines_with_closed = client.get("/app/api/deadlines", params={"include_closed": True})
    assert deadlines_with_closed.status_code == 200
    assert any(item["id"] == deadline_ref and item["status"] == "elapsed" for item in deadlines_with_closed.json()["items"])
    deadline_history = client.get(f"/app/api/deadlines/{deadline_ref}/history")
    assert deadline_history.status_code == 200
    assert any(row["event_type"] == "queue_resolved" for row in deadline_history.json())
    deadline_reopened = client.post(
        f"/app/api/deadlines/{deadline_ref}/resolve",
        json={"action": "reopen", "reason": "Window reopened for the next board cycle", "due_at": "2026-03-26T15:00:00+00:00"},
    )
    assert deadline_reopened.status_code == 200
    assert deadline_reopened.json()["status"] == "open"
    assert deadline_reopened.json()["end_at"] == "2026-03-26T15:00:00+00:00"

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

    waiting = client.post(
        f"/app/api/commitments/follow_up:{seeded['follow_up_id']}/resolve",
        json={
            "action": "wait",
            "reason": "Investor needs to confirm availability",
            "reason_code": "waiting_on_external",
            "due_at": "2026-03-28T09:30:00+00:00",
        },
    )
    assert waiting.status_code == 200
    assert waiting.json()["status"] == "waiting_on_external"
    assert waiting.json()["resolution_code"] == "waiting_on_external"
    assert waiting.json()["due_at"] == "2026-03-28T09:30:00+00:00"

    scheduled = client.post(
        f"/app/api/commitments/commitment:{seeded['commitment_id']}/resolve",
        json={
            "action": "schedule",
            "reason": "Board review is booked for Friday morning",
            "reason_code": "board_review_booked",
            "due_at": "2026-03-29T08:00:00+00:00",
        },
    )
    assert scheduled.status_code == 200
    assert scheduled.json()["status"] == "scheduled"
    assert scheduled.json()["resolution_code"] == "board_review_booked"
    assert scheduled.json()["due_at"] == "2026-03-29T08:00:00+00:00"

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

    history = client.get(f"/app/api/handoffs/{handoff_ref}/history")
    assert history.status_code == 200
    history_rows = history.json()
    assert [row["event_name"] for row in history_rows] == [
        "human_task_created",
        "human_task_assigned",
        "human_task_returned",
    ]
    assert [row["assigned_operator_id"] for row in history_rows] == [
        "",
        seeded["operator_id"],
        seeded["operator_id"],
    ]
    assert history_rows[1]["assignment_source"] == "manual"
    assert history_rows[1]["assigned_by_actor_id"] == seeded["operator_id"]
    assert history_rows[2]["assigned_by_actor_id"] == seeded["operator_id"]
    assert history_rows[2]["resolution"] == "completed"

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

    office = client.get("/admin/office")
    assert office.status_code == 200
    assert "Other operator-only handoff" not in office.text


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
    assert outcomes_body["counts"]["draft_send_followup_created"] >= 1
    assert outcomes_body["approval_coverage_rate"] >= outcomes_body["approval_action_rate"]
    assert outcomes_body["approval_action_rate"] == 0.0
    assert outcomes_body["delivery_followup_closeout_count"] == 0
    assert outcomes_body["delivery_followup_blocked_count"] == 0
    assert outcomes_body["delivery_followup_resolution_rate"] == 0.0
    assert outcomes_body["delivery_followup_blocked_rate"] == 0.0
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
    assert body["product_control"]["summary"]
    assert "journey_gate_freshness" in body["product_control"]
    assert "support_fallout" in body["product_control"]
    assert "public_guide_freshness" in body["product_control"]


def test_support_fix_verification_tracks_request_receipt_and_confirmation() -> None:
    principal_id = "exec-support-fix-verification"
    client = build_product_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Support Verification Office")

    updated = client.post(
        "/app/api/settings/morning-memo",
        json={
            "workspace_name": "Support Verification Office",
            "enabled": True,
            "cadence": "daily_morning",
            "recipient_email": "tibor@example.com",
            "delivery_time_local": "08:00",
            "quiet_hours_start": "20:00",
            "quiet_hours_end": "07:00",
        },
    )
    assert updated.status_code == 200
    assert updated.json()["workspace"]["name"] == "Support Verification Office"

    requested = client.post("/app/api/support/fix-verification/request")
    assert requested.status_code == 200
    support_body = requested.json()
    verification = dict(support_body["support_verification"])
    assert verification["state"] == "waiting"
    assert verification["recipient_email"] == "tibor@example.com"
    assert verification["request_id"]
    assert verification["delivery_url"].startswith("/channel-loop/deliveries/")
    assert verification["access_url"].startswith("/workspace-access/")
    assert verification["channel_receipt_state"] == "waiting"
    assert verification["install_receipt_state"] == "waiting"
    assert verification["request_api_href"] == "/app/api/support/fix-verification/request"
    assert verification["request_api_method"] == "post"

    memo_plain = client.get("/app/api/channel-loop/memo/plain")
    assert memo_plain.status_code == 200
    assert "Confirm the fix reached you" in memo_plain.text
    assert "/app/channel-actions/" in memo_plain.text

    opened_delivery = client.get(verification["delivery_url"], follow_redirects=False)
    assert opened_delivery.status_code == 303

    after_delivery = dict(client.get("/app/api/support").json()["support_verification"])
    assert after_delivery["channel_receipt_state"] == "received"

    opened_access = client.get(verification["access_url"], follow_redirects=False)
    assert opened_access.status_code == 303

    after_access = dict(client.get("/app/api/support").json()["support_verification"])
    assert after_access["install_receipt_state"] == "opened"

    channel_loop = client.get("/app/api/channel-loop")
    assert channel_loop.status_code == 200
    memo_digest = next(item for item in channel_loop.json()["digests"] if item["key"] == "memo")
    support_item = next(item for item in memo_digest["items"] if item["title"] == "Confirm the fix reached you")

    confirmed = client.get(str(support_item["action_href"]), follow_redirects=False)
    assert confirmed.status_code == 303
    assert confirmed.headers["location"] == "/app/channel-loop/memo"

    final = dict(client.get("/app/api/support").json()["support_verification"])
    assert final["state"] == "confirmed"
    assert final["confirmation_state"] == "confirmed"


def test_workspace_outcomes_expose_last_memo_issue_and_fix_target() -> None:
    principal_id = "exec-product-memo-issue"
    client = build_product_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Memo Issue Office")
    updated = client.post(
        "/app/api/settings/morning-memo",
        json={
            "workspace_name": "Memo Issue Office",
            "enabled": True,
            "cadence": "daily_morning",
            "recipient_email": "tibor@myexternalbrain.com",
            "delivery_time_local": "08:00",
            "quiet_hours_start": "20:00",
            "quiet_hours_end": "07:00",
        },
    )
    assert updated.status_code == 200
    assert updated.json()["workspace"]["name"] == "Memo Issue Office"
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

    outcomes = client.get("/app/api/outcomes")
    assert outcomes.status_code == 200
    memo_loop = outcomes.json()["memo_loop"]
    assert memo_loop["last_issue_kind"] == "failed"
    assert memo_loop["last_issue_reason"] == "Domain not verified"
    assert memo_loop["last_issue_fix_href"] == "/app/settings/support"
    assert memo_loop["last_issue_fix_label"] == "Open support"


def test_workspace_outcomes_expose_manual_memo_delivery_issue_and_fix_target() -> None:
    principal_id = "exec-product-manual-memo-issue"
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

    outcomes = client.get("/app/api/outcomes")
    assert outcomes.status_code == 200
    memo_loop = outcomes.json()["memo_loop"]
    assert memo_loop["enabled"] is False
    assert memo_loop["last_issue_kind"] == "failed"
    assert memo_loop["last_issue_reason"] == "Domain not verified"
    assert memo_loop["last_issue_fix_href"] == "/app/settings/support"
    assert memo_loop["last_issue_fix_label"] == "Open support"
    assert memo_loop["last_issue_fix_detail"] == "Verify the sending domain in the email provider before the next memo cycle."
    proof = outcomes.json()["office_loop_proof"]
    blocker_check = next(item for item in proof["checks"] if item["key"] == "memo_delivery_blocker")
    assert blocker_check["state"] == "critical"
    assert blocker_check["actual"] == "Domain not verified"
    assert blocker_check["target"] == "no blocker"
    assert blocker_check["detail"] == "Verify the sending domain in the email provider before the next memo cycle."
    assert proof["state"] == "critical"
    assert proof["summary"] == "Office-loop proof is blocked by a current memo delivery issue."


def test_channel_loop_surfaces_memo_delivery_blocker_fix_action() -> None:
    principal_id = "exec-product-channel-loop-memo-blocker"
    client = build_product_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Channel Loop Memo Blocker Office")
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

    loop = client.get("/app/api/channel-loop")
    assert loop.status_code == 200
    body = loop.json()
    root_blocker = next(item for item in body["items"] if item["title"] == "Fix memo delivery blocker")
    assert "Domain not verified" in root_blocker["detail"]
    assert root_blocker["action_label"] == "Open support"
    assert root_blocker["action_href"] == "/app/settings/support"
    memo_digest = next(item for item in body["digests"] if item["key"] == "memo")
    memo_blocker = next(item for item in memo_digest["items"] if item["title"] == "Fix memo delivery blocker")
    assert "Domain not verified" in memo_blocker["detail"]
    assert memo_blocker["action_label"] == "Open support"
    assert memo_blocker["action_href"] == "/app/settings/support"
    assert int(memo_digest["stats"]["memo_blockers"]) == 1
    assert "memo blocker" in memo_digest["preview_text"].lower()
    operator_digest = next(item for item in body["digests"] if item["key"] == "operator")
    assert any(item["title"] == "Fix memo delivery blocker" for item in operator_digest["items"])
    memo_plain = client.get("/app/api/channel-loop/memo/plain")
    assert memo_plain.status_code == 200
    assert "Fix memo delivery blocker" in memo_plain.text
    assert "Domain not verified" in memo_plain.text
    assert "/app/settings/support" in memo_plain.text
    assert "Open support:" in memo_plain.text
    assert "Open: http://testserver/app/settings/support" not in memo_plain.text


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
    assert body["sync"]["pending_commitment_candidates"] == 0
    assert body["sync"]["covered_signal_candidates"] >= 1
    assert any(item["label"] for item in body["next_actions"])
    assert body["operator_memo_grounding"]["id"] == "operator_memo"
    assert body["operator_memo_grounding"]["actions"]
    assert any(item["label"] == "GOLDEN_JOURNEY_RELEASE_GATES.yaml" for item in body["operator_memo_grounding"]["sources"])
    assert any(item["label"] == "manifest.generated.json" for item in body["operator_memo_grounding"]["sources"])
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


def test_operator_center_surfaces_memo_delivery_blocker_fix_action() -> None:
    principal_id = "exec-operator-center-memo-blocker"
    client = build_operator_product_client(principal_id=principal_id, operator_id="operator-office")
    seed_product_state(client, principal_id=principal_id)
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

    center = client.get("/app/api/operator-center")
    assert center.status_code == 200
    blocker = next(item for item in center.json()["next_actions"] if item["label"] == "Fix memo delivery blocker")
    assert "Domain not verified" in blocker["detail"]
    assert "Verify the sending domain in the email provider before the next memo cycle." in blocker["detail"]
    assert blocker["href"] == "/app/settings/support"
    assert blocker["action_label"] == "Open support"
    assert blocker["action_href"] == "/app/settings/support"
    assert blocker["action_method"] == "get"


def test_operator_center_clears_historical_digest_failures_after_successful_memo_send() -> None:
    principal_id = "exec-operator-center-memo-recovered"
    client = build_operator_product_client(principal_id=principal_id, operator_id="operator-office")
    seed_product_state(client, principal_id=principal_id)
    runtime = client.app.state.container.channel_runtime
    runtime.ingest_observation(
        principal_id=principal_id,
        channel="product",
        event_type="channel_digest_delivery_email_failed",
        payload={
            "delivery_id": "memo-delivery-failed",
            "digest_key": "memo",
            "recipient_email": "tibor@myexternalbrain.com",
            "error": 'registration_email_send_failed:422:{"error":"Domain not verified"}',
        },
        source_id="memo-delivery-failed",
        dedupe_key=f"{principal_id}|manual-memo-failed",
    )
    runtime.ingest_observation(
        principal_id=principal_id,
        channel="product",
        event_type="channel_digest_delivery_email_sent",
        payload={
            "delivery_id": "memo-delivery-sent",
            "digest_key": "memo",
            "recipient_email": "tibor@myexternalbrain.com",
            "email_delivery_status": "sent",
        },
        source_id="memo-delivery-sent",
        dedupe_key=f"{principal_id}|manual-memo-sent",
    )

    outcomes = client.get("/app/api/outcomes")
    assert outcomes.status_code == 200
    assert outcomes.json()["memo_loop"]["last_issue_reason"] == ""

    center = client.get("/app/api/operator-center")
    assert center.status_code == 200
    body = center.json()
    delivery_lane = next(item for item in body["lanes"] if item["key"] == "delivery")
    exceptions_lane = next(item for item in body["lanes"] if item["key"] == "exceptions")
    assert delivery_lane["state"] == "clear"
    assert delivery_lane["count"] == 0
    assert "0 active memo blockers" in delivery_lane["detail"]
    assert "0 delivery issues" in exceptions_lane["detail"]
    assert not any(item["label"] == "Fix memo delivery blocker" for item in body["next_actions"])
    assert any(str(item.get("event_type") or "") == "channel_digest_delivery_email_sent" for item in body["recent_runtime"])

    diagnostics = client.get("/app/api/diagnostics")
    assert diagnostics.status_code == 200
    reliability = diagnostics.json()["analytics"]["reliability"]
    assert reliability["delivery_reliability_state"] == "clear"
    assert reliability["active_delivery_issue_total"] == 0


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
    assert "Review this workspace invite before you join." in preview.text
    assert "Accept invitation" in preview.text
    assert "Return through existing access" in preview.text

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
    sign_in_head = client.head("/sign-in", follow_redirects=False)
    assert sign_in_head.status_code == 200

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
    opened_access_external = client.get(
        access_body["access_url"],
        params={"return_to": "https://evil.example/phish"},
        follow_redirects=False,
    )
    assert opened_access_external.status_code == 303
    assert opened_access_external.headers["location"] == "/app/today"
    opened_access = client.get(access_body["access_url"], follow_redirects=False)
    assert opened_access.status_code == 303
    assert opened_access.headers["location"] == "/app/today"
    assert "ea_workspace_session=" in str(opened_access.headers.get("set-cookie") or "")
    opened_access_secure = client.get(
        access_body["access_url"],
        follow_redirects=False,
        headers={"x-forwarded-proto": "https"},
    )
    assert opened_access_secure.status_code == 303
    secure_access_cookie = str(opened_access_secure.headers.get("set-cookie") or "")
    assert "ea_workspace_session=" in secure_access_cookie
    assert "Secure" in secure_access_cookie
    assert "Max-Age=" in secure_access_cookie
    head_opened_access = client.head(access_body["access_url"], follow_redirects=False)
    assert head_opened_access.status_code == 303
    assert head_opened_access.headers["location"] == "/app/today"
    assert "ea_workspace_session=" in str(head_opened_access.headers.get("set-cookie") or "")
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
    assert "This sign-in link is no longer valid." in blocked_access.text
    assert "Request new sign-in link" in blocked_access.text
    blocked_access_head = client.head(access_body["access_url"], follow_redirects=False)
    assert blocked_access_head.status_code == 404

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
    opened_delivery_secure = client.get(
        delivery_body["delivery_url"],
        follow_redirects=False,
        headers={"x-forwarded-proto": "https"},
    )
    assert opened_delivery_secure.status_code == 303
    secure_delivery_cookie = str(opened_delivery_secure.headers.get("set-cookie") or "")
    assert "ea_workspace_session=" in secure_delivery_cookie
    assert "Secure" in secure_delivery_cookie
    assert "Max-Age=" in secure_delivery_cookie
    opened_delivery_head = client.head(delivery_body["delivery_url"], follow_redirects=False)
    assert opened_delivery_head.status_code == 303
    assert opened_delivery_head.headers["location"] == "/app/channel-loop/memo"
    assert "ea_workspace_session=" in str(opened_delivery_head.headers.get("set-cookie") or "")
    delivered_loop = client.get("/app/api/channel-loop")
    assert delivered_loop.status_code == 200
    delivered_body = delivered_loop.json()
    assert delivered_body["headline"] == "Inline loop"
    assert any(item["key"] == "operator" for item in delivered_body["digests"])

    diagnostics = client.get("/app/api/diagnostics")
    assert diagnostics.status_code == 200
    counts = diagnostics.json()["analytics"]["counts"]
    assert int(counts.get("channel_digest_delivery_opened") or 0) >= 1
    assert int(counts.get("memo_opened") or 0) >= 1

    missing_delivery = client.get("/channel-loop/deliveries/bad-token")
    assert missing_delivery.status_code == 404
    assert "This delivered workspace link is no longer valid." in missing_delivery.text
    assert "Request new sign-in link" in missing_delivery.text
    missing_delivery_head = client.head("/channel-loop/deliveries/bad-token", follow_redirects=False)
    assert missing_delivery_head.status_code == 404


def test_workspace_invite_and_access_invalid_pages_render_browser_recovery_copy() -> None:
    principal_id = "exec-workspace-link-recovery"
    client = build_product_client(principal_id=principal_id)
    start_workspace(client, mode="team", workspace_name="Recovery Office")

    missing_invite = client.get("/workspace-invites/bad-token")
    assert missing_invite.status_code == 404
    assert "This workspace invite is no longer valid." in missing_invite.text
    assert "Request a fresh invite" in missing_invite.text
    assert "Request new sign-in link" in missing_invite.text
    missing_invite_head = client.head("/workspace-invites/bad-token", follow_redirects=False)
    assert missing_invite_head.status_code == 404

    missing_access = client.get("/workspace-access/bad-token")
    assert missing_access.status_code == 404
    assert "This sign-in link is no longer valid." in missing_access.text
    assert "Request new sign-in link" in missing_access.text
    missing_access_head = client.head("/workspace-access/bad-token", follow_redirects=False)
    assert missing_access_head.status_code == 404

    missing_channel_action = client.get("/app/channel-actions/bad-token")
    assert missing_channel_action.status_code == 404
    assert "This action link is no longer valid." in missing_channel_action.text
    missing_channel_action_head = client.head("/app/channel-actions/bad-token", follow_redirects=False)
    assert missing_channel_action_head.status_code == 404
