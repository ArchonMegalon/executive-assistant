from __future__ import annotations

import hashlib
import hmac
import json
import os
import urllib.parse
import zipfile
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlparse
from uuid import uuid4

import pytest

import app.api.routes.channels as channel_routes
import app.api.routes.product_api_delivery as product_api_delivery_routes
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


def test_signal_ingest_immmo_property_alert_mail_uses_property_review_lane() -> None:
    principal_id = "exec-product-signal-ooda-immmo-agent"
    client = build_product_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Property Alert Office")

    signal = client.post(
        "/app/api/signals/ingest",
        json={
            "signal_type": "email_thread",
            "channel": "gmail",
            "title": "1 neue Anzeige für Wohnungen mieten in Wien 2/20",
            "summary": "1 neue Anzeige für Wohnungen mieten in Wien 2/20",
            "text": "1 neue Anzeige für Wohnungen mieten in Wien 2/20",
            "counterparty": "IMMMO",
            "source_ref": "gmail-thread:elisabeth.girschele@gmail.com:test-immmo-alert-1",
            "external_id": "gmail-message:elisabeth.girschele@gmail.com:test-immmo-alert-1",
            "payload": {
                "from_email": "mailrobot@immmo.at",
                "from_name": "IMMMO",
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


def test_signal_ingest_property_alert_sends_telegram_review_summary(monkeypatch) -> None:
    principal_id = "exec-product-signal-telegram-property-review"
    client = build_product_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Property Alert Telegram Office")
    client.app.state.container.tool_runtime.upsert_connector_binding(
        principal_id=principal_id,
        connector_name="telegram_identity",
        external_account_ref="1354554303",
        auth_metadata_json={"default_chat_ref": "1354554303", "bot_key": "default", "bot_handle": "tibor_concierge_bot"},
        scope_json={"assistant_surfaces": ["dm"]},
        status="enabled",
    )
    monkeypatch.setenv("EA_TELEGRAM_BOT_TOKEN", "telegram-token-test")

    observed_telegram: dict[str, object] = {}

    class _TelegramReceipt:
        chat_id = "1354554303"
        message_ids = ("777",)

    monkeypatch.setattr(
        product_service,
        "send_telegram_message_for_principal",
        lambda tool_runtime, *, principal_id, text, inline_buttons=None: observed_telegram.update(
            {"principal_id": principal_id, "text": text, "inline_buttons": inline_buttons}
        ) or _TelegramReceipt(),
    )

    signal = client.post(
        "/app/api/signals/ingest",
        json={
            "signal_type": "email_thread",
            "channel": "gmail",
            "title": "1 neue Anzeige für Wohnungen mieten in Wien 2/20",
            "summary": "1 neue Anzeige für Wohnungen mieten in Wien 2/20",
            "text": "https://www.immoscout24.at/expose/telegram-test-property-1",
            "counterparty": "IMMMO",
            "source_ref": "gmail-thread:elisabeth.girschele@gmail.com:test-telegram-property-alert-1",
            "external_id": "gmail-message:elisabeth.girschele@gmail.com:test-telegram-property-alert-1",
            "payload": {
                "from_email": "mailrobot@immmo.at",
                "from_name": "IMMMO",
                "account_email": "elisabeth.girschele@gmail.com",
                "labels": ["CATEGORY_UPDATES", "INBOX"],
            },
        },
    )
    assert signal.status_code == 200
    assert observed_telegram["principal_id"] == principal_id
    assert "Scout update." in str(observed_telegram["text"])
    assert "Listing: https://www.immoscout24.at/expose/telegram-test-property-1" in str(observed_telegram["text"])
    assert observed_telegram["inline_buttons"]


def test_signal_ingest_property_alert_sends_workspace_review_link_for_cf_email_principal(monkeypatch) -> None:
    principal_id = "cf-email:tibor.girschele@gmail.com"
    client = build_product_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Property Alert Telegram Office")
    client.app.state.container.tool_runtime.upsert_connector_binding(
        principal_id=principal_id,
        connector_name="telegram_identity",
        external_account_ref="1354554303",
        auth_metadata_json={"default_chat_ref": "1354554303", "bot_key": "default", "bot_handle": "tibor_concierge_bot"},
        scope_json={"assistant_surfaces": ["dm"]},
        status="enabled",
    )
    monkeypatch.setenv("EA_TELEGRAM_BOT_TOKEN", "telegram-token-test")
    monkeypatch.setenv("EA_PUBLIC_APP_BASE_URL", "https://myexternalbrain.com")

    observed_telegram: dict[str, object] = {}

    class _TelegramReceipt:
        chat_id = "1354554303"
        message_ids = ("778",)

    monkeypatch.setattr(
        product_service,
        "send_telegram_message_for_principal",
        lambda tool_runtime, *, principal_id, text, inline_buttons=None: observed_telegram.update(
            {"principal_id": principal_id, "text": text, "inline_buttons": inline_buttons}
        ) or _TelegramReceipt(),
    )

    signal = client.post(
        "/app/api/signals/ingest",
        json={
            "signal_type": "email_thread",
            "channel": "gmail",
            "title": "1 neue Anzeige für Wohnungen mieten in Wien 2/20",
            "summary": "1 neue Anzeige für Wohnungen mieten in Wien 2/20",
            "text": "https://www.immobilienscout24.at/expose/telegram-test-property-2",
            "counterparty": "IMMMO",
            "source_ref": "gmail-thread:elisabeth.girschele@gmail.com:test-telegram-property-alert-2",
            "external_id": "gmail-message:elisabeth.girschele@gmail.com:test-telegram-property-alert-2",
            "payload": {
                "from_email": "mailrobot@immmo.at",
                "from_name": "IMMMO",
                "account_email": "elisabeth.girschele@gmail.com",
                "labels": ["CATEGORY_UPDATES", "INBOX"],
            },
        },
    )
    assert signal.status_code == 200
    assert observed_telegram["principal_id"] == principal_id
    assert "Review: https://myexternalbrain.com/workspace-access/" in str(observed_telegram["text"])
    assert "Listing: https://www.immobilienscout24.at/expose/telegram-test-property-2" not in str(observed_telegram["text"])

    handoffs = client.get("/app/api/handoffs")
    assert handoffs.status_code == 200
    property_handoff = next(item for item in handoffs.json() if item["task_type"] == "property_alert_review")
    assert property_handoff["editor_url"].startswith("/app/handoffs/human_task:")


def test_signal_ingest_willhaben_property_alert_review_uses_personal_fit_priority(monkeypatch) -> None:
    principal_id = "exec-product-signal-property-fit-priority"
    client = build_product_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Property Fit Priority Office")

    monkeypatch.setattr(
        product_service,
        "_load_willhaben_property_packet",
        lambda url: {
            "property_url": url,
            "listing_id": "fit-priority-1",
            "title": "Strong Waehring listing",
            "property_facts_json": {
                "postal_name": "Waehring",
                "heating_type": "Fernwaerme",
                "has_floorplan": True,
                "has_360": True,
                "lift": True,
                "bike_infrastructure_score": 9,
                "green_space_score": 8,
                "playground_score": 7,
            },
            "media_urls_json": [],
            "floorplan_urls_json": ["https://cdn.example.com/floorplan.png"],
        },
    )

    monkeypatch.setattr(
        client.app.state.container.preference_profiles,
        "assess_candidate",
        lambda **kwargs: {
            "assessment_id": "assessment-property-fit-priority",
            "domain": "willhaben",
            "object_id": "fit-priority-1",
            "fit_score": 92.0,
            "confidence": 0.91,
            "predicted_reaction": "shortlist",
            "recommendation": "shortlist",
            "match_reasons_json": ["The listing is in Waehring, which matches established district preferences."],
            "mismatch_reasons_json": [],
            "unknowns_json": [],
            "blocking_constraints_json": [],
        },
    )

    signal = client.post(
        "/app/api/signals/ingest",
        json={
            "signal_type": "email_thread",
            "channel": "gmail",
            "title": "\"Mietwohnungen 2,20, 09\" hat 1 neue Anzeige für dich gefunden",
            "summary": "\"Mietwohnungen 2,20, 09\" hat 1 neue Anzeige für dich gefunden",
            "text": (
                "Neue Anzeige gefunden. "
                "https://www.willhaben.at/iad/immobilien/d/mietwohnungen/wien/test-fit-priority-1"
            ),
            "counterparty": "willhaben-Suchagent",
            "source_ref": "gmail-thread:elisabeth.girschele@gmail.com:test-fit-priority-1",
            "external_id": "gmail-message:elisabeth.girschele@gmail.com:test-fit-priority-1",
            "payload": {
                "from_email": "no-reply@agent.willhaben.at",
                "from_name": "willhaben-Suchagent",
                "account_email": "elisabeth.girschele@gmail.com",
                "labels": ["CATEGORY_UPDATES", "INBOX"],
            },
        },
    )
    assert signal.status_code == 200

    queue = client.get("/app/api/queue")
    assert queue.status_code == 200
    item = next(row for row in queue.json()["items"] if row["id"].startswith("human_task:"))
    assert item["priority"] == "high"
    assert item["rank_score"] == 92.0
    assert "Personal fit 92/100" in item["summary"]
    assert "shortlist" in item["summary"].lower()


def test_signal_ingest_property_alert_queue_orders_higher_fit_first(monkeypatch) -> None:
    principal_id = "exec-product-signal-property-fit-order"
    client = build_product_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Property Fit Ordering Office")

    def _fake_packet(url: str) -> dict[str, object]:
        listing_id = "high-fit-1" if "high-fit-1" in url else "mid-fit-1"
        district = "Waehring" if listing_id == "high-fit-1" else "Floridsdorf"
        return {
            "property_url": url,
            "listing_id": listing_id,
            "title": f"Listing {listing_id}",
            "property_facts_json": {
                "postal_name": district,
                "heating_type": "Fernwaerme",
                "has_floorplan": True,
                "has_360": True,
                "lift": True,
            },
            "media_urls_json": [],
            "floorplan_urls_json": ["https://cdn.example.com/floorplan.png"],
        }

    monkeypatch.setattr(product_service, "_load_willhaben_property_packet", _fake_packet)
    monkeypatch.setattr(ProductService, "_resolve_browseract_property_tour_binding_id", lambda self, **kwargs: "browseract-binding-1")

    def _fake_assess_candidate(**kwargs):
        object_id = str(kwargs.get("object_id") or "")
        if "high-fit-1" in object_id:
            return {
                "assessment_id": "assessment-high-fit-1",
                "domain": "willhaben",
                "object_id": object_id,
                "fit_score": 96.0,
                "confidence": 0.95,
                "predicted_reaction": "shortlist",
                "recommendation": "shortlist",
                "match_reasons_json": ["The listing is in Waehring, which matches established district preferences."],
                "mismatch_reasons_json": [],
                "unknowns_json": [],
                "blocking_constraints_json": [],
            }
        return {
            "assessment_id": "assessment-mid-fit-1",
            "domain": "willhaben",
            "object_id": object_id,
            "fit_score": 61.0,
            "confidence": 0.76,
            "predicted_reaction": "consider",
            "recommendation": "ask_for_clarification",
            "match_reasons_json": ["The listing could work, but the district fit is less certain."],
            "mismatch_reasons_json": [],
            "unknowns_json": [],
            "blocking_constraints_json": [],
        }

    monkeypatch.setattr(client.app.state.container.preference_profiles, "assess_candidate", _fake_assess_candidate)

    for suffix in ("mid-fit-1", "high-fit-1"):
        signal = client.post(
            "/app/api/signals/ingest",
            json={
                "signal_type": "email_thread",
                "channel": "gmail",
                "title": f"\"Mietwohnungen 2,20, 09\" hat 1 neue Anzeige für dich gefunden ({suffix})",
                "summary": f"\"Mietwohnungen 2,20, 09\" hat 1 neue Anzeige für dich gefunden ({suffix})",
                "text": f"https://www.willhaben.at/iad/immobilien/d/mietwohnungen/wien/{suffix}",
                "counterparty": "willhaben-Suchagent",
                "source_ref": f"gmail-thread:elisabeth.girschele@gmail.com:{suffix}",
                "external_id": f"gmail-message:elisabeth.girschele@gmail.com:{suffix}",
                "payload": {
                    "from_email": "no-reply@agent.willhaben.at",
                    "from_name": "willhaben-Suchagent",
                    "account_email": "elisabeth.girschele@gmail.com",
                    "labels": ["CATEGORY_UPDATES", "INBOX"],
                },
            },
        )
        assert signal.status_code == 200

    queue = client.get("/app/api/queue")
    assert queue.status_code == 200
    items = [row for row in queue.json()["items"] if row["id"].startswith("human_task:")]
    assert len(items) >= 2
    assert items[0]["rank_score"] == 96.0
    assert "Personal fit 96/100" in items[0]["summary"]
    assert items[1]["rank_score"] == 61.0


def test_property_scout_config_and_listing_extraction(monkeypatch) -> None:
    monkeypatch.setenv(
        "EA_PROPERTY_SCOUT_URLS_JSON",
        json.dumps(
            [
                "https://www.immmo.at/search/rent",
                {
                    "url": "https://www.immoscout24.at/suche#ignored",
                    "label": "Scout",
                    "principal_id": "principal-scout",
                    "preference_person_id": "elisabeth",
                    "account_email": "Scout@Example.COM",
                    "notify_telegram": False,
                    "max_results": 99,
                },
            ]
        ),
    )

    specs = product_service._property_scout_source_specs()

    assert specs[0]["url"] == "https://www.immmo.at/search/rent"
    assert specs[0]["notify_telegram"] is True
    assert specs[0]["max_results"] == 3
    assert specs[1]["url"] == "https://www.immoscout24.at/suche"
    assert specs[1]["label"] == "Scout"
    assert specs[1]["principal_id"] == "principal-scout"
    assert specs[1]["preference_person_id"] == "elisabeth"
    assert specs[1]["account_email"] == "scout@example.com"
    assert specs[1]["notify_telegram"] is False
    assert specs[1]["max_results"] == 10

    html = """
    <a href="/expose/12345">supported relative</a>
    <a href="https://www.immoscout24.at/expose/12345#gallery">duplicate fragment</a>
    <a href="https://example.com/expose/999">unsupported host</a>
    <script>{"url":"https:\\/\\/www.willhaben.at\\/iad\\/immobilien\\/d\\/mietwohnungen\\/wien\\/garden-789"}</script>
    <a href="https://www.willhaben.at/iad/immobilien/mietwohnungen/wien">search page</a>
    <a href="https://www.willhaben.at/bbx-search/_next/static/assets/facebook_placeholder.jpg">placeholder</a>
    """

    urls = product_service._property_scout_extract_listing_urls(
        source_url="https://www.immoscout24.at/suche",
        html=html,
    )

    assert urls == (
        "https://www.immoscout24.at/expose/12345",
        "https://www.willhaben.at/iad/immobilien/d/mietwohnungen/wien/garden-789",
    )


def test_property_alert_email_url_extraction_skips_willhaben_campaign_links() -> None:
    body = (
        "https://www.willhaben.at/dl/v1/home/?at_campaign=email "
        "https://www.willhaben.at/dl/v1/alertsearch/myprofile/alert?searchId=131 "
        "https://www.willhaben.at/iad/object?adId=2021345821&searchAgentQueryString=1 "
        "https://www.willhaben.at/iad/object?adId=1491222816&searchAgentQueryString=1"
    )

    urls = product_service._willhaben_property_urls_from_signal(
        title='"Mietwohnungen" hat 2 neue Anzeigen fuer dich gefunden',
        summary="Recent mail from willhaben-Suchagent.",
        text=body,
        source_ref="gmail-thread:elisabeth:test",
        external_id="gmail-message:elisabeth:test",
        payload={"body_text_excerpt": body, "from_email": "no-reply@agent.willhaben.at"},
    )
    first = product_service._property_listing_url_from_signal(
        title='"Mietwohnungen" hat 2 neue Anzeigen fuer dich gefunden',
        summary="Recent mail from willhaben-Suchagent.",
        text=body,
        source_ref="gmail-thread:elisabeth:test",
        external_id="gmail-message:elisabeth:test",
        payload={"body_text_excerpt": body, "from_email": "no-reply@agent.willhaben.at"},
    )

    assert urls == (
        "https://www.willhaben.at/iad/object?adId=2021345821&searchAgentQueryString=1",
        "https://www.willhaben.at/iad/object?adId=1491222816&searchAgentQueryString=1",
    )
    assert first == "https://www.willhaben.at/iad/object?adId=2021345821&searchAgentQueryString=1"


def test_property_scout_extract_listing_urls_reads_script_paths_for_js_heavy_search_pages() -> None:
    html = """
    <script type="application/json">
      {"items":[{"url":"/for-sale/details/12345678/"},{"url":"/for-sale/details/87654321/"}]}
    </script>
    """

    urls = product_service._property_scout_extract_listing_urls(
        source_url="https://www.zoopla.co.uk/for-sale/property/london/",
        html=html,
    )

    assert urls == (
        "https://www.zoopla.co.uk/for-sale/details/12345678/",
        "https://www.zoopla.co.uk/for-sale/details/87654321/",
    )


def test_property_scout_extract_listing_urls_filters_immmo_upstream_to_immoscout() -> None:
    html = """
    <a href="https://www.immobilienscout24.at/expose/6a211cd1e3becfd2d596846f?utm_source=immmo.at">supported scout expose</a>
    <a href="https://immo.sn.at/immobilien/beispiel-GVXMH2?utm_source=immmo.at">other upstream listing</a>
    """

    urls = product_service._property_scout_extract_listing_urls(
        source_url="https://www.immmo.at/suche/kauf?q=Wien&pq_upstream=immoscout_at",
        html=html,
    )

    assert urls == (
        "https://www.immobilienscout24.at/expose/6a211cd1e3becfd2d596846f?utm_source=immmo.at",
    )


def test_property_scout_extract_listing_urls_supports_justiz_alldoc_results() -> None:
    html = """
    <a href="alldoc/62af2c93a0d4c4e1c1258d1c00225860!OpenDocument">Eintrag 1</a>
    <a href="alldoc/a468679bdbbc73d1c1258d1c00225a5c!OpenDocument">Eintrag 2</a>
    """

    urls = product_service._property_scout_extract_listing_urls(
        source_url="https://edikte2.justiz.gv.at/edikte/ex/exedi3.nsf/suchedi?SearchView&subf=eex&query=test",
        html=html,
    )

    assert urls == (
        "https://edikte2.justiz.gv.at/edikte/ex/exedi3.nsf/alldoc/62af2c93a0d4c4e1c1258d1c00225860!OpenDocument",
        "https://edikte2.justiz.gv.at/edikte/ex/exedi3.nsf/alldoc/a468679bdbbc73d1c1258d1c00225a5c!OpenDocument",
    )


def test_property_scout_extract_listing_urls_builds_sozialbau_virtual_listings() -> None:
    html = """
    <table><tbody>
      <tr data-ri="0" class="ui-widget-content ui-datatable-even">
        <td role="gridcell"><span class="badge">Miete</span></td>
        <td role="gridcell"><a href="#">1210 Wien<br />1210 Wien, Antonie-Lehr-Straße 18 / Leopoldauer Haide Gasse 12</a></td>
        <td role="gridcell">144</td>
        <td role="gridcell">August 2026</td>
        <td role="gridcell">37486</td>
        <td role="gridcell"><a href="https://www.google.com/maps/place/48.248654,16.425635/@48.248654,16.425635,19z">map</a></td>
        <td role="gridcell"><button>Vormerken</button></td>
      </tr>
    </tbody></table>
    """

    urls = product_service._property_scout_extract_listing_urls(
        source_url="https://angebote.sozialbau.at/sobitvX/htmlprospect/home.xhtml?pq_scope=in_bau",
        html=html,
    )

    assert len(urls) == 1
    assert "pq_listing=1" in urls[0]
    assert "offer_type=Miete" in urls[0]
    assert "registration_count=37486" in urls[0]


def test_property_scout_page_preview_reads_sozialbau_virtual_listing_url() -> None:
    listing_url = (
        "https://angebote.sozialbau.at/sobitvX/htmlprospect/home.xhtml"
        "?pq_listing=1&offer_type=Miete&postal_name=1210+Wien&street_address=Antonie-Lehr-Stra%C3%9Fe+18"
        "&unit_count=144&move_in=August+2026&registration_count=37486&map_lat=48.248654&map_lng=16.425635"
    )

    preview = product_service._property_scout_page_preview(listing_url, prefer_fast=True)

    facts = dict(preview["property_facts_json"])
    assert facts["provider_channel"] == "sozialbau"
    assert facts["provider_group"] == "genossenschaften_at"
    assert facts["street_address"] == "Antonie-Lehr-Straße 18"
    assert facts["postal_name"] == "1210 Wien"
    assert facts["unit_count"] == 144
    assert facts["registration_count"] == 37486
    assert facts["availability_label"] == "August 2026"
    assert preview["title"] == "1210 Wien | Antonie-Lehr-Straße 18"


def test_property_scout_extract_listing_urls_supports_query_based_auction_links() -> None:
    html = """
    <div data-href="/index.php?button=showzvg&zvg_id=123&land_abk=be"></div>
    <script>
      window.location='/index.php?button=showzvg&zvg_id=987&land_abk=be';
    </script>
    """

    urls = product_service._property_scout_extract_listing_urls(
        source_url="https://www.zvg-portal.de/",
        html=html,
    )

    assert urls == (
        "https://www.zvg-portal.de/index.php?button=showzvg&zvg_id=123&land_abk=be",
        "https://www.zvg-portal.de/index.php?button=showzvg&zvg_id=987&land_abk=be",
    )


def test_property_scout_extract_listing_urls_supports_boe_subasta_query_ids() -> None:
    html = """
    <a data-url="/subastas/detalleSubasta.php?idSub=SUB-JA-2026-99999">detalle</a>
    <script type="application/json">
      {"detailUrl":"https:\\/\\/subastas.boe.es\\/subastas\\/detalleSubasta.php?idSub=SUB-JA-2026-11111"}
    </script>
    """

    urls = product_service._property_scout_extract_listing_urls(
        source_url="https://subastas.boe.es/subastas_ava.php?campo%5B0%5D=SUBASTA.INMUEBLES",
        html=html,
    )

    assert set(urls) == {
        "https://subastas.boe.es/subastas/detalleSubasta.php?idSub=SUB-JA-2026-99999",
        "https://subastas.boe.es/subastas/detalleSubasta.php?idSub=SUB-JA-2026-11111",
    }


def test_property_scout_extract_listing_urls_supports_grouped_austria_cooperative_sources() -> None:
    gesiba_html = """
    <a href="/immobilien/wohnungen/objekt?objektnummer=01000103511">GESIBA detail</a>
    <a href="/immobilien/wohnungen">Search root</a>
    """
    siedlungsunion_html = """
    <a href="/wohnen/sofort/1100-wien-leibnizgasse-68-2-eg-3">Siedlungsunion detail</a>
    """
    wbv_html = """
    <a href="https://www.wbv-gpa.at/wohnung/2700-wr-neustadt-groehrmuehlgasse-4-6-top-19/">WBV detail</a>
    """
    frieden_html = """
    <a href="/immobiliensuche/59442?returnUrl=%2Fimmobiliensuche">Frieden detail</a>
    <a href="/immobiliensuche?pg=2">Pagination</a>
    """

    gesiba_urls = product_service._property_scout_extract_listing_urls(
        source_url="https://www.gesiba.at/immobilien/wohnungen",
        html=gesiba_html,
    )
    siedlungsunion_urls = product_service._property_scout_extract_listing_urls(
        source_url="https://www.siedlungsunion.at/wohnen/sofort",
        html=siedlungsunion_html,
    )
    wbv_urls = product_service._property_scout_extract_listing_urls(
        source_url="https://www.wbv-gpa.at/wohnungen/",
        html=wbv_html,
    )
    frieden_urls = product_service._property_scout_extract_listing_urls(
        source_url="https://www.frieden.at/immobiliensuche",
        html=frieden_html,
    )

    assert gesiba_urls == ("https://www.gesiba.at/immobilien/wohnungen/objekt?objektnummer=01000103511",)
    assert siedlungsunion_urls == ("https://www.siedlungsunion.at/wohnen/sofort/1100-wien-leibnizgasse-68-2-eg-3",)
    assert wbv_urls == ("https://www.wbv-gpa.at/wohnung/2700-wr-neustadt-groehrmuehlgasse-4-6-top-19/",)
    assert frieden_urls == ("https://www.frieden.at/immobiliensuche/59442?returnUrl=%2Fimmobiliensuche",)


def test_property_cooperative_preview_fact_parsers_extract_structured_fields() -> None:
    gesiba_html = """
    <img src="/imager/objekte/1100_WIEN_KURBADSTRASSE_-_01000103511/21921/rendering-2.jpg">
    <p>Geplant ist eine Fassadenbegrünung. Tiefgarage vorhanden.</p>
    """
    siedlungsunion_html = """
    <div class="uk-text-bold">2 Zimmer</div>
    <p>2 Zimmerwohnung mit Terrasse (6,99 m²) und Loggia (8,01 m²)</p>
    """
    wbv_html = """
    <strong>3 Zimmer</strong>
    <div>Wohnfläche</div><div>78,40 m²</div>
    <p>Miete brutto incl. BK, Heizung und einem Garagenplatz: dzt. € 1.026,–</p>
    <p>Lift ist vorhanden.</p>
    """
    frieden_html = """
    <div>ZIMMER</div><div><div>2</div></div>
    <div>61,89 m² | 2 Zimmer</div>
    <script type="application/json">
    {"address":"2624 Neusiedl am Steinfeld, Am Waldstrand 1-3","latitude":48.56481,"longitude":16.07877,
     "equipments":[{"label":"Heizung","annotation":"Fußbodenheizung mittels Fernwärme (EVN)"},{"label":"Aufzug"}],
     "price":"€ 812,34"}
    </script>
    """

    gesiba = product_service._property_cooperative_housing_facts(
        "https://www.gesiba.at/immobilien/wohnungen/objekt?objektnummer=01000103511",
        gesiba_html,
        product_service._property_html_fragment_text(gesiba_html),
    )
    siedlungsunion = product_service._property_cooperative_housing_facts(
        "https://www.siedlungsunion.at/wohnen/sofort/1100-wien-leibnizgasse-68-2-eg-3",
        siedlungsunion_html,
        product_service._property_html_fragment_text(siedlungsunion_html),
    )
    wbv = product_service._property_cooperative_housing_facts(
        "https://www.wbv-gpa.at/wohnung/2700-wr-neustadt-groehrmuehlgasse-4-6-top-19/",
        wbv_html,
        product_service._property_html_fragment_text(wbv_html),
    )
    frieden = product_service._property_cooperative_housing_facts(
        "https://www.frieden.at/immobiliensuche/59442?returnUrl=%2Fimmobiliensuche",
        frieden_html,
        product_service._property_html_fragment_text(frieden_html),
    )

    assert gesiba["provider_channel"] == "gesiba"
    assert gesiba["postal_name"] == "1100 Wien"
    assert gesiba["garage"] is True

    assert siedlungsunion["provider_channel"] == "siedlungsunion"
    assert siedlungsunion["rooms"] == 2.0
    assert siedlungsunion["terrace_area_sqm"] == 6.99
    assert siedlungsunion["loggia_area_sqm"] == 8.01

    assert wbv["provider_channel"] == "wbv_gpa"
    assert wbv["rooms"] == 3.0
    assert wbv["area_sqm"] == 78.4
    assert wbv["has_lift"] is True
    assert wbv["total_rent_eur"] == 1026.0

    assert frieden["provider_channel"] == "frieden"
    assert frieden["rooms"] == 2.0
    assert frieden["area_sqm"] == 61.89
    assert frieden["heating_type"].startswith("Fu")
    assert frieden["has_lift"] is True


def test_property_scout_source_specs_infers_platform_from_url_host() -> None:
    monkeypatch_json = json.dumps(
        [
            {
                "url": "https://www.zoopla.co.uk/for-sale/property/london/",
            }
        ]
    )
    previous = os.environ.get("EA_PROPERTY_SCOUT_URLS_JSON")
    os.environ["EA_PROPERTY_SCOUT_URLS_JSON"] = monkeypatch_json
    try:
        specs = product_service._property_scout_source_specs()
    finally:
        if previous is None:
            os.environ.pop("EA_PROPERTY_SCOUT_URLS_JSON", None)
        else:
            os.environ["EA_PROPERTY_SCOUT_URLS_JSON"] = previous

    assert specs[0]["platform"] == "zoopla"


def test_property_scout_route_uses_explicit_preference_person_and_creates_reviews(monkeypatch) -> None:
    principal_id = "cf-email:tibor.girschele@gmail.com"
    client = build_product_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Property Scout Office")
    monkeypatch.setenv(
        "EA_PROPERTY_SCOUT_URLS_JSON",
        json.dumps(
            [
                {
                    "url": "https://www.immmo.at/immo/Wohnung-mieten/Wien",
                    "label": "IMMMO Wien rentals",
                    "principal_id": principal_id,
                    "preference_person_id": "elisabeth",
                    "notify_telegram": False,
                    "max_results": 2,
                }
            ]
        ),
    )
    monkeypatch.setattr(
        product_service,
        "_property_scout_fetch_html",
        lambda url: '<a href="https://www.immobilienscout24.at/expose/abc-1">One</a><a href="https://www.immobilienscout24.at/expose/abc-2">Two</a>',
    )
    monkeypatch.setattr(
        product_service,
        "_property_scout_page_preview",
        lambda url: {
            "listing_id": url.rsplit("/", 1)[-1],
            "title": "Scout flat " + url.rsplit("/", 1)[-1],
            "summary": "Waehring, lift, floorplan, 360 panorama",
            "property_facts_json": {},
        },
    )
    captured: list[dict[str, object]] = []

    def _fake_assess_candidate(**kwargs):
        captured.append(dict(kwargs))
        score = 96.0 if str(kwargs["object_id"]).endswith("abc-1") else 72.0
        return {
            "fit_score": score,
            "confidence": 0.9,
            "predicted_reaction": "positive",
            "recommendation": "shortlist" if score >= 90 else "view_if_compelling",
            "match_reasons_json": ["Matches Elisabeth"],
            "mismatch_reasons_json": [],
            "unknowns_json": [],
            "blocking_constraints_json": [],
        }

    monkeypatch.setattr(client.app.state.container.preference_profiles, "assess_candidate", _fake_assess_candidate)

    response = client.post("/app/api/signals/property/scout")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "processed"
    assert body["sources_total"] == 1
    assert body["listing_total"] == 2
    assert body["review_created_total"] == 2
    assert body["high_fit_total"] == 1
    assert body["sources"][0]["preference_person_id"] == "elisabeth"
    assert body["sources"][0]["top_fit_score"] == 96.0
    assert captured[0]["person_id"] == "elisabeth"
    assert captured[0]["object_payload"]["district"] == "waehring"
    assert captured[0]["object_payload"]["has_360"] is True
    assert captured[0]["object_payload"]["has_floorplan"] is True
    events = client.get("/app/api/events", params={"channel": "product", "event_type": "property_alert_review_created"})
    assert events.status_code == 200
    created = [item for item in events.json()["items"] if item["payload"].get("preference_person_id") == "elisabeth"]
    assert created
    assert all(float(item["payload"].get("willhaben_fit_score") or 0.0) > 0.0 for item in created)


def test_property_scout_route_notifies_high_fit_and_creates_tour_for_existing_review(monkeypatch) -> None:
    principal_id = "cf-email:tibor.girschele@gmail.com"
    client = build_product_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Property Scout Notify Office")
    product = ProductService(client.app.state.container)
    product.update_property_alert_policy(
        principal_id=principal_id,
        auto_score=True,
        auto_compare=True,
        auto_generate_tour_for_good_fit=True,
        notify_only_if_good=True,
        good_fit_min_score=80.0,
        actor="test",
    )
    product.upsert_preference_profile(
        principal_id=principal_id,
        person_id="elisabeth",
        display_name="Elisabeth",
        learning_enabled=True,
    )
    client.app.state.container.tool_runtime.upsert_connector_binding(
        principal_id=principal_id,
        connector_name="telegram_identity",
        external_account_ref="1354554303",
        auth_metadata_json={"default_chat_ref": "1354554303", "bot_key": "default", "bot_handle": "tibor_concierge_bot"},
        scope_json={"assistant_surfaces": ["dm"]},
        status="enabled",
    )
    monkeypatch.setenv("EA_TELEGRAM_BOT_TOKEN", "telegram-token-test")
    listing_url = "https://www.willhaben.at/iad/immobilien/d/mietwohnungen/wien/wien-1180-waehring/testwohnung-123456789/"
    monkeypatch.setenv(
        "EA_PROPERTY_SCOUT_URLS_JSON",
        json.dumps(
            [
                {
                    "url": "https://www.willhaben.at/iad/immobilien/mietwohnungen/wien/?areaId=900&sort=3",
                    "label": "Willhaben Wien rentals",
                    "principal_id": principal_id,
                    "preference_person_id": "elisabeth",
                    "notify_telegram": True,
                    "max_results": 1,
                }
            ]
        ),
    )
    monkeypatch.setattr(
        product_service,
        "_property_scout_fetch_html",
        lambda url: f'<a href="{listing_url}">One</a>',
    )
    monkeypatch.setattr(
        product_service,
        "_load_willhaben_property_packet",
        lambda url: {
            "property_url": url,
            "listing_id": "123456789",
            "listing_uuid": "uuid-123456789",
            "title": "Waehring shortlist flat",
            "property_facts_json": {
                "postal_name": "Waehring",
                "area_label": "74 m²",
                "rooms_label": "3 rooms",
                "total_rent_eur": 1890.0,
                "heating": "Fernwaerme",
                "floorplan_count": 1,
            },
            "media_urls_json": ["https://cdn.example.com/photo-1.jpg"],
            "floorplan_urls_json": ["https://cdn.example.com/floorplan.png"],
            "tour_variants_json": [{"variant_key": "layout_first", "scene_strategy": "layout_first"}],
        },
    )
    monkeypatch.setattr(
        client.app.state.container.preference_profiles,
        "assess_candidate",
        lambda **kwargs: {
            "assessment_id": "assessment-high-fit-scout-existing-1",
            "domain": "willhaben",
            "object_id": str(kwargs.get("object_id") or ""),
            "fit_score": 96.0,
            "confidence": 0.96,
            "predicted_reaction": "shortlist",
            "recommendation": "shortlist",
            "match_reasons_json": ["Matches Elisabeth strongly."],
            "mismatch_reasons_json": [],
            "unknowns_json": [],
            "blocking_constraints_json": [],
        },
    )
    product._open_property_alert_review(
        principal_id=principal_id,
        title="Existing Waehring shortlist flat",
        summary="existing scout review",
        source_ref="property-scout:123456789",
        external_id=listing_url,
        counterparty="Willhaben Wien rentals",
        account_email="",
        property_url=listing_url,
        actor="test",
        notify_telegram=False,
        personal_fit_assessment={"fit_score": 96.0, "recommendation": "shortlist"},
        preference_person_id="elisabeth",
    )
    observed_telegram: dict[str, object] = {}

    class _TelegramReceipt:
        chat_id = "1354554303"
        message_ids = ("991",)

    monkeypatch.setattr(
        product_service,
        "send_telegram_message_for_principal",
        lambda tool_runtime, *, principal_id, text, inline_buttons=None: observed_telegram.update({"principal_id": principal_id, "text": text, "inline_buttons": inline_buttons}) or _TelegramReceipt(),
    )
    monkeypatch.setattr(
        ProductService,
        "create_willhaben_property_tour",
        lambda self, **kwargs: {
            "status": "created",
            "tour_url": "https://myexternalbrain.com/tours/test-scout-flat",
            "vendor_tour_url": "https://vendor.example.com/tours/test-scout-flat",
            "blocked_reason": "",
        },
    )
    response = client.post("/app/api/signals/property/scout")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "processed"
    assert body["review_existing_total"] == 1
    assert body["notified_total"] == 1
    assert body["tour_created_total"] == 1
    assert body["high_fit_total"] == 1
    assert "Personal fit 96/100" in str(observed_telegram["text"])
    assert "https://myexternalbrain.com/tours/test-scout-flat" in str(observed_telegram["text"])
    assert observed_telegram["inline_buttons"]
    feedback_events = client.get("/app/api/events", params={"channel": "product", "event_type": "notification_feedback_prompted"})
    assert feedback_events.status_code == 200
    feedback_prompt = next(item for item in feedback_events.json()["items"] if item["payload"]["source_ref"] == "property-scout:123456789")
    feedback_result = product.record_notification_feedback(
        principal_id=principal_id,
        notification_key=str(feedback_prompt["payload"]["notification_key"]),
        feedback_key="more_like_this",
        actor="test",
        chat_id="1354554303",
    )
    assert feedback_result["status"] == "recorded"
    bundle = client.app.state.container.preference_profiles.get_profile_bundle(principal_id=principal_id, person_id="elisabeth")
    evidence_rows = [
        row
        for row in list(bundle.get("recent_evidence_events") or [])
        if str(row.get("domain") or "") == "willhaben" and str(row.get("event_type") or "") == "listing_saved"
    ]
    assert evidence_rows


def test_property_scout_route_sends_client_email_alerts_via_emailit(monkeypatch) -> None:
    from app.services.registration_email import RegistrationEmailReceipt

    monkeypatch.setenv("EMAILIT_API_KEY", "emailit-test-key")
    principal_id = "cf-email:tibor.girschele@gmail.com"
    client = build_product_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Property Scout Email Office")
    product = ProductService(client.app.state.container)
    product.update_property_alert_policy(
        principal_id=principal_id,
        auto_score=True,
        auto_compare=True,
        auto_generate_tour_for_good_fit=False,
        notify_only_if_good=True,
        good_fit_min_score=80.0,
        actor="test",
    )
    listing_url = "https://www.willhaben.at/iad/immobilien/d/mietwohnungen/wien/wien-1180-waehring/email-fit-123456789/"
    monkeypatch.setenv(
        "EA_PROPERTY_SCOUT_URLS_JSON",
        json.dumps(
            [
                {
                    "url": "https://www.willhaben.at/iad/immobilien/mietwohnungen/wien/?areaId=900&sort=3",
                    "label": "Willhaben Wien rentals",
                    "principal_id": principal_id,
                    "preference_person_id": "elisabeth",
                    "notify_telegram": False,
                    "max_results": 1,
                }
            ]
        ),
    )
    monkeypatch.setattr(product_service, "_property_scout_fetch_html", lambda url: f'<a href="{listing_url}">One</a>')
    monkeypatch.setattr(
        product_service,
        "_load_willhaben_property_packet",
        lambda url: {
            "property_url": url,
            "listing_id": "email-fit-123456789",
            "title": "Email fit flat",
            "property_facts_json": {
                "postal_name": "Waehring",
                "area_label": "74 m²",
                "rooms_label": "3 rooms",
                "total_rent_eur": 1890.0,
                "heating": "Fernwaerme",
                "floorplan_count": 1,
            },
            "media_urls_json": ["https://cdn.example.com/photo-1.jpg"],
            "floorplan_urls_json": ["https://cdn.example.com/floorplan.png"],
            "tour_variants_json": [],
        },
    )
    monkeypatch.setattr(
        client.app.state.container.preference_profiles,
        "assess_candidate",
        lambda **kwargs: {
            "assessment_id": "assessment-email-fit-1",
            "domain": "willhaben",
            "object_id": str(kwargs.get("object_id") or ""),
            "fit_score": 94.0,
            "confidence": 0.94,
            "predicted_reaction": "shortlist",
            "recommendation": "shortlist",
            "match_reasons_json": ["Strong transit fit.", "Floor plan is available."],
            "mismatch_reasons_json": [],
            "unknowns_json": ["Lift still needs checking."],
            "blocking_constraints_json": [],
        },
    )
    observed_email: dict[str, object] = {}
    monkeypatch.setattr(
        product_service,
        "send_property_match_email",
        lambda **kwargs: observed_email.update(kwargs) or RegistrationEmailReceipt(provider="emailit", message_id="property-match-email-1", accepted_at="2026-06-03T00:00:00+00:00"),
    )

    response = client.post("/app/api/signals/property/scout")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "processed"
    assert body["notified_total"] == 1
    assert body["email_notified_total"] == 1
    assert body["sources"][0]["email_notified_total"] == 1
    assert body["sources"][0]["top_candidates"][0]["title"] == "Email fit flat"
    assert body["sources"][0]["top_candidates"][0]["recommendation"] == "shortlist"
    assert body["sources"][0]["top_candidates"][0]["review_url"]
    assert observed_email["recipient_email"] == "tibor.girschele@gmail.com"
    assert observed_email["property_title"] == "Email fit flat"
    assert "Willhaben Wien rentals" in str(observed_email["provider_label"])


def test_property_scout_route_notifies_top_watch_hit_when_no_good_fit(monkeypatch) -> None:
    principal_id = "cf-email:tibor.girschele@gmail.com"
    client = build_product_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Property Scout Watch Notify Office")
    client.post(
        "/app/api/people/elisabeth/preference-profile",
        json={
            "display_name": "Elisabeth",
            "consent_mode": "behavioral_learning",
            "learning_enabled": True,
        },
    )
    client.app.state.container.tool_runtime.upsert_connector_binding(
        principal_id=principal_id,
        connector_name="telegram_identity",
        external_account_ref="1354554303",
        auth_metadata_json={
            "default_chat_ref": "1354554303",
            "bot_key": "default",
            "bot_handle": "tibor_concierge_bot",
        },
        scope_json={"assistant_surfaces": ["dm"]},
        status="enabled",
    )
    product = ProductService(client.app.state.container)
    product.update_property_alert_policy(
        principal_id=principal_id,
        auto_score=True,
        auto_compare=True,
        auto_generate_tour_for_good_fit=True,
        notify_only_if_good=True,
        good_fit_min_score=80.0,
        notify_top_watch_hit_when_no_good_fit=True,
        watch_fit_min_score=35.0,
        actor="test",
    )
    monkeypatch.setenv(
        "EA_PROPERTY_SCOUT_URLS_JSON",
        json.dumps(
            [
                {
                    "url": "https://www.immmo.at/immo/Wohnung-mieten/Wien",
                    "label": "IMMMO Wien rentals",
                    "principal_id": principal_id,
                    "preference_person_id": "elisabeth",
                    "notify_telegram": True,
                    "max_results": 1,
                }
            ]
        ),
    )
    monkeypatch.setenv("EA_TELEGRAM_BOT_TOKEN", "telegram-token-test")
    listing_url = "https://www.immobilienscout24.at/expose/watch-fit-1"
    monkeypatch.setattr(
        product_service,
        "_property_scout_fetch_html",
        lambda url: f'<a href="{listing_url}">One</a>',
    )
    monkeypatch.setattr(
        product_service,
        "_property_scout_page_preview",
        lambda url: {
            "listing_id": "watch-fit-1",
            "title": "Watch fit apartment",
            "summary": "Vienna apartment",
            "property_facts_json": {},
        },
    )
    monkeypatch.setattr(
        client.app.state.container.preference_profiles,
        "assess_candidate",
        lambda **kwargs: {
            "assessment_id": "assessment-watch-fit-1",
            "domain": "willhaben",
            "object_id": str(kwargs.get("object_id") or ""),
            "fit_score": 37.0,
            "confidence": 0.78,
            "predicted_reaction": "consider",
            "recommendation": "ask_for_clarification",
            "match_reasons_json": ["Potential fit worth watching."],
            "mismatch_reasons_json": [],
            "unknowns_json": [],
            "blocking_constraints_json": [],
        },
    )
    observed_telegram: dict[str, object] = {}

    class _TelegramReceipt:
        chat_id = "1354554303"
        message_ids = ("992",)

    monkeypatch.setattr(
        product_service,
        "send_telegram_message_for_principal",
        lambda tool_runtime, *, principal_id, text, inline_buttons=None: observed_telegram.update({"principal_id": principal_id, "text": text, "inline_buttons": inline_buttons}) or _TelegramReceipt(),
    )
    response = client.post("/app/api/signals/property/scout")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "processed"
    assert body["high_fit_total"] == 0
    assert body["notified_total"] == 1
    assert body["sources"][0]["watch_notified_total"] == 1
    assert "Personal fit 37/100" in str(observed_telegram["text"])
    assert "Review: https://myexternalbrain.com/workspace-access/" in str(observed_telegram["text"])
    assert f"Listing: {listing_url}" not in str(observed_telegram["text"])


def test_property_alert_review_handoff_page_renders_research_packet() -> None:
    principal_id = "cf-email:tibor.girschele@gmail.com"
    client = build_product_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Property Review Packet Office")
    product = ProductService(client.app.state.container)
    result = product._open_property_alert_review(
        principal_id=principal_id,
        title="Watch fit apartment",
        summary="Lift unclear, but floor plan and good transit look promising.",
        source_ref="property-scout:watch-fit-1",
        external_id="https://www.immobilienscout24.at/expose/watch-fit-1",
        counterparty="IMMMO Wien rentals",
        account_email="elisabeth.girschele@gmail.com",
        property_url="https://www.immobilienscout24.at/expose/watch-fit-1",
        actor="test",
        notify_telegram=False,
        candidate_properties=(
            {
                "property_url": "https://www.immobilienscout24.at/expose/watch-fit-1",
                "listing_title": "Watch fit apartment",
                "fit_summary": "Personal fit 91/100 · shortlist",
                "assessment": {
                    "fit_score": 91.0,
                    "recommendation": "shortlist",
                },
            },
        ),
        personal_fit_assessment={
            "fit_score": 91.0,
            "recommendation": "shortlist",
            "match_reasons_json": ["Good U-Bahn access.", "Floor plan is available."],
            "mismatch_reasons_json": ["Lift not confirmed."],
            "unknowns_json": ["Heating type needs research."],
            "blocking_constraints_json": [],
        },
        preference_person_id="elisabeth",
        tour_url="https://myexternalbrain.com/tours/watch-fit-1",
    )

    page = client.get(f"/app/handoffs/{result['human_task_id']}")
    assert page.status_code == 200
    assert "Property research, fit reasoning, and review actions for this alert." in page.text
    assert "Watch fit apartment" in page.text
    assert "Good U-Bahn access." in page.text
    assert "Lift not confirmed." in page.text
    assert "Heating type needs research." in page.text
    assert "https://myexternalbrain.com/tours/watch-fit-1" in page.text
    assert "https://www.immobilienscout24.at/expose/watch-fit-1" in page.text


def test_property_scout_feedback_buttons_include_reason_suggestions(monkeypatch) -> None:
    principal_id = "cf-email:tibor.girschele@gmail.com"
    client = build_product_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Property Scout Reason Buttons Office")
    product = ProductService(client.app.state.container)
    product.update_property_alert_policy(
        principal_id=principal_id,
        auto_score=True,
        auto_compare=True,
        auto_generate_tour_for_good_fit=False,
        notify_only_if_good=True,
        good_fit_min_score=80.0,
        actor="test",
    )
    product.upsert_preference_profile(
        principal_id=principal_id,
        person_id="elisabeth",
        display_name="Elisabeth",
        learning_enabled=True,
    )
    client.app.state.container.tool_runtime.upsert_connector_binding(
        principal_id=principal_id,
        connector_name="telegram_identity",
        external_account_ref="1354554303",
        auth_metadata_json={"default_chat_ref": "1354554303", "bot_key": "default", "bot_handle": "tibor_concierge_bot"},
        scope_json={"assistant_surfaces": ["dm"]},
        status="enabled",
    )
    monkeypatch.setenv("EA_TELEGRAM_BOT_TOKEN", "telegram-token-test")
    listing_url = "https://www.willhaben.at/iad/immobilien/d/mietwohnungen/wien/wien-1180-waehring/testwohnung-987654321/"
    monkeypatch.setenv(
        "EA_PROPERTY_SCOUT_URLS_JSON",
        json.dumps(
            [
                {
                    "url": "https://www.willhaben.at/iad/immobilien/mietwohnungen/wien/?areaId=900&sort=3",
                    "label": "Willhaben Wien rentals",
                    "principal_id": principal_id,
                    "preference_person_id": "elisabeth",
                    "notify_telegram": True,
                    "max_results": 1,
                }
            ]
        ),
    )
    monkeypatch.setattr(product_service, "_property_scout_fetch_html", lambda url: f'<a href="{listing_url}">One</a>')
    monkeypatch.setattr(
        product_service,
        "_load_willhaben_property_packet",
        lambda url: {
            "property_url": url,
            "listing_id": "987654321",
            "listing_uuid": "uuid-987654321",
            "title": "Heating mismatch flat",
            "property_facts_json": {
                "postal_name": "Waehring",
                "heating": "Gasetagenheizung",
                "floorplan_count": 0,
            },
            "media_urls_json": ["https://cdn.example.com/photo-1.jpg"],
            "floorplan_urls_json": [],
            "tour_variants_json": [],
        },
    )
    monkeypatch.setattr(
        client.app.state.container.preference_profiles,
        "assess_candidate",
        lambda **kwargs: {
            "assessment_id": "assessment-reason-buttons-1",
            "domain": "willhaben",
            "object_id": str(kwargs.get("object_id") or ""),
            "fit_score": 92.0,
            "confidence": 0.92,
            "predicted_reaction": "consider",
            "recommendation": "shortlist",
            "match_reasons_json": ["Mostly strong, but heating and missing floor plan are concerns."],
            "mismatch_reasons_json": ["Gas heating."],
            "unknowns_json": [],
            "blocking_constraints_json": [],
        },
    )
    observed_telegram: dict[str, object] = {}

    class _TelegramReceipt:
        chat_id = "1354554303"
        message_ids = ("993",)

    monkeypatch.setattr(
        product_service,
        "send_telegram_message_for_principal",
        lambda tool_runtime, *, principal_id, text, inline_buttons=None: observed_telegram.update({"principal_id": principal_id, "text": text, "inline_buttons": inline_buttons}) or _TelegramReceipt(),
    )
    response = client.post("/app/api/signals/property/scout")
    assert response.status_code == 200
    button_labels = [button[0] for row in list(observed_telegram.get("inline_buttons") or []) for button in row]
    assert "Ignore: no central heating" in button_labels
    assert "Need floor plan" in button_labels
    feedback_events = client.get("/app/api/events", params={"channel": "product", "event_type": "notification_feedback_prompted"})
    assert feedback_events.status_code == 200
    feedback_prompt = next(item for item in feedback_events.json()["items"] if item["payload"]["source_ref"] == "property-scout:987654321")
    feedback_result = product.record_notification_feedback(
        principal_id=principal_id,
        notification_key=str(feedback_prompt["payload"]["notification_key"]),
        feedback_key="avoid_heat",
        actor="test",
        chat_id="1354554303",
    )
    assert feedback_result["status"] == "recorded"
    bundle = client.app.state.container.preference_profiles.get_profile_bundle(principal_id=principal_id, person_id="elisabeth")
    evidence_rows = [
        row
        for row in list(bundle.get("recent_evidence_events") or [])
        if str(row.get("domain") or "") == "willhaben" and str(row.get("event_type") or "") == "listing_dismissed"
    ]
    assert any("avoid_heating_types" in json.dumps(dict(row.get("interpreted_signal_json") or {}), ensure_ascii=False) for row in evidence_rows)


def test_telegram_feedback_callback_records_generic_notification_preference(monkeypatch) -> None:
    principal_id = "cf-email:tibor.girschele@gmail.com"
    client = build_product_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Telegram Feedback Office")
    monkeypatch.setenv("EA_TELEGRAM_BOT_TOKEN", "telegram-token-test")
    monkeypatch.setenv("EA_TELEGRAM_BOT_HANDLE", "tibor_concierge_bot")
    monkeypatch.setenv("EA_TELEGRAM_INGEST_SECRET", "telegram-secret-test")
    client.app.state.container.tool_runtime.upsert_connector_binding(
        principal_id=principal_id,
        connector_name="telegram_identity",
        external_account_ref="1354554303",
        auth_metadata_json={
            "default_chat_ref": "1354554303",
            "bot_key": "default",
            "bot_handle": "tibor_concierge_bot",
        },
        scope_json={"assistant_surfaces": ["dm"]},
        status="enabled",
    )
    product = ProductService(client.app.state.container)
    prompt = product._prepare_notification_feedback_prompt(
        principal_id=principal_id,
        notification_kind="assistant_nudge",
        person_id="self",
        domain="assistant_nudge",
        object_type="channel_digest",
        object_id="assistant_nudge",
        source_ref="channel_digest:assistant_nudge",
        raw_signal_json={"headline": "Action needed", "preview_text": "Approve the draft."},
        interpreted_signal_json={},
    )
    product._record_notification_feedback_prompt(
        principal_id=principal_id,
        prompt=prompt,
        delivery_channel="telegram",
        telegram_chat_ref="1354554303",
        telegram_message_ids=["991"],
    )
    callback_data = str(prompt["button_rows"][0][0][1])
    answered: list[dict[str, object]] = []
    replies: list[dict[str, object]] = []
    monkeypatch.setattr(
        channel_routes,
        "_telegram_answer_callback_query",
        lambda *, bot_token, callback_query_id, text="": answered.append(
            {"bot_token": bot_token, "callback_query_id": callback_query_id, "text": text}
        ),
    )
    monkeypatch.setattr(
        channel_routes,
        "_telegram_send_and_record_reply",
        lambda **kwargs: replies.append({"reply_text": kwargs.get("reply_text"), "dedupe_key": kwargs.get("dedupe_key")}) or True,
    )
    response = client.post(
        "/v1/channels/telegram/ingest",
        headers={"x-telegram-bot-api-secret-token": "telegram-secret-test"},
        json={
            "update": {
                "callback_query": {
                    "id": "cb-1",
                    "data": callback_data,
                    "message": {
                        "message_id": 991,
                        "text": "Action needed",
                        "chat": {"id": "1354554303"},
                    },
                }
            }
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["reply_sent"] is True
    assert body["reply_text"] == "Noted. I’ll keep this style of notification."
    assert answered and answered[0]["callback_query_id"] == "cb-1"
    assert replies and replies[0]["reply_text"] == "Noted. I’ll keep this style of notification."
    feedback_events = client.get("/app/api/events", params={"channel": "product", "event_type": "notification_feedback_received"})
    assert feedback_events.status_code == 200
    feedback_payloads = [item["payload"] for item in feedback_events.json()["items"]]
    matched_feedback = next(item for item in feedback_payloads if item["notification_key"] == prompt["notification_key"])
    assert matched_feedback["feedback_key"] == "useful"
    bundle = client.app.state.container.preference_profiles.get_profile_bundle(principal_id=principal_id, person_id="self")
    evidence_rows = [
        row
        for row in list(bundle.get("recent_evidence_events") or [])
        if str(row.get("domain") or "") == "assistant_nudge" and str(row.get("event_type") or "") == "notification_useful"
    ]
    assert evidence_rows


def test_property_alert_preference_scoring_flows_through_queue_and_telegram(monkeypatch) -> None:
    principal_id = "exec-product-property-fit-end-to-end"
    client = build_product_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Property Fit End To End Office")
    product = ProductService(client.app.state.container)
    product.update_property_alert_policy(
        principal_id=principal_id,
        auto_score=True,
        auto_compare=True,
        auto_generate_tour_for_good_fit=False,
        notify_only_if_good=True,
        actor="test",
    )
    client.post(
        "/app/api/people/self/preference-profile",
        json={
            "display_name": "Tibor",
            "consent_mode": "behavioral_learning",
            "learning_enabled": True,
        },
    )

    def _fake_packet(url: str) -> dict[str, object]:
        listing_id = "high-fit-telegram-1" if "high-fit-telegram-1" in url else "low-fit-telegram-1"
        district = "Waehring" if listing_id == "high-fit-telegram-1" else "Floridsdorf"
        return {
            "property_url": url,
            "listing_id": listing_id,
            "listing_uuid": f"uuid-{listing_id}",
            "title": f"Listing {listing_id}",
            "property_facts_json": {
                "postal_name": district,
                "area_label": "74 m²",
                "rooms_label": "3 rooms",
                "total_rent_eur": 1890.0 if listing_id == "high-fit-telegram-1" else 1790.0,
                "heating": "Fernwaerme",
                "floorplan_count": 1,
                "decision_summary": {"recommendation": "shortlist" if listing_id == "high-fit-telegram-1" else "mention"},
            },
            "media_urls_json": ["https://cdn.example.com/photo-1.jpg"],
            "floorplan_urls_json": ["https://cdn.example.com/floorplan.png"],
            "tour_variants_json": [{"variant_key": "layout_first", "scene_strategy": "layout_first"}],
        }

    monkeypatch.setattr(product_service, "_load_willhaben_property_packet", _fake_packet)
    monkeypatch.setattr(ProductService, "_resolve_browseract_property_tour_binding_id", lambda self, **kwargs: "browseract-binding-1")

    def _fake_assess_candidate(**kwargs):
        object_id = str(kwargs.get("object_id") or "")
        if "high-fit-telegram-1" in object_id:
            return {
                "assessment_id": "assessment-high-fit-telegram-1",
                "domain": "willhaben",
                "object_id": object_id,
                "fit_score": 96.0,
                "confidence": 0.95,
                "predicted_reaction": "shortlist",
                "recommendation": "shortlist",
                "match_reasons_json": ["The listing is in Waehring, which matches established district preferences."],
                "mismatch_reasons_json": [],
                "unknowns_json": [],
                "blocking_constraints_json": [],
            }
        return {
            "assessment_id": "assessment-low-fit-telegram-1",
            "domain": "willhaben",
            "object_id": object_id,
            "fit_score": 42.0,
            "confidence": 0.7,
            "predicted_reaction": "consider",
            "recommendation": "ask_for_clarification",
            "match_reasons_json": ["The listing may work, but district fit is weak."],
            "mismatch_reasons_json": [],
            "unknowns_json": [],
            "blocking_constraints_json": [],
        }

    monkeypatch.setattr(client.app.state.container.preference_profiles, "assess_candidate", _fake_assess_candidate)

    observed_telegram: dict[str, object] = {}

    class _TelegramReceipt:
        chat_id = "1354554303"
        message_ids = ("778",)

    monkeypatch.setattr(
        product_service,
        "send_telegram_message_for_principal",
        lambda tool_runtime, *, principal_id, text, inline_buttons=None: observed_telegram.update({"principal_id": principal_id, "text": text, "inline_buttons": inline_buttons}) or _TelegramReceipt(),
    )

    signal = client.post(
        "/app/api/signals/ingest",
        json={
            "signal_type": "email_thread",
            "channel": "gmail",
            "title": "\"Mietwohnungen 2,20, 09\" hat 2 neue Anzeigen für dich gefunden",
            "summary": "\"Mietwohnungen 2,20, 09\" hat 2 neue Anzeigen für dich gefunden",
            "text": (
                "Neue Anzeigen gefunden. "
                "https://www.willhaben.at/iad/immobilien/d/mietwohnungen/wien/high-fit-telegram-1 "
                "https://www.willhaben.at/iad/immobilien/d/mietwohnungen/wien/low-fit-telegram-1"
            ),
            "counterparty": "willhaben-Suchagent",
            "source_ref": "gmail-thread:elisabeth.girschele@gmail.com:high-low-fit-batch",
            "external_id": "gmail-message:elisabeth.girschele@gmail.com:high-low-fit-batch",
            "payload": {
                "from_email": "no-reply@agent.willhaben.at",
                "from_name": "willhaben-Suchagent",
                "account_email": "elisabeth.girschele@gmail.com",
                "labels": ["CATEGORY_UPDATES", "INBOX"],
            },
        },
    )
    assert signal.status_code == 200
    assert "Top candidate: Personal fit 96/100" in str(observed_telegram["text"])
    assert "high-fit-telegram-1" in str(observed_telegram["text"])

    queue = client.get("/app/api/queue")
    assert queue.status_code == 200
    items = [row for row in queue.json()["items"] if row["id"].startswith("human_task:")]
    assert len(items) >= 2
    assert items[0]["rank_score"] == 96.0
    assert items[1]["rank_score"] == 42.0
    assert "Personal fit 96/100" in items[0]["summary"]


def test_queue_uses_profile_admin_boost_for_matching_tasks() -> None:
    principal_id = "exec-product-profile-queue-boost"
    client = build_product_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Profile Queue Boost Office")
    seeded = seed_product_state(client, principal_id=principal_id)
    product = ProductService(client.app.state.container)

    product.upsert_preference_profile(
        principal_id=principal_id,
        person_id="self",
        display_name="Tibor Girschele",
        learning_enabled=True,
    )
    product.upsert_preference_node(
        principal_id=principal_id,
        person_id="self",
        domain="life_admin",
        category="insurance_admin",
        key="rehab_authorization_management",
        value_json={
            "enabled": True,
            "entities": ["KfA", "NRZ"],
            "focus_areas": ["rehab_authorizations", "physio_ergo_approvals"],
        },
        strength="high",
        confidence=0.9,
        source_mode="inferred",
        status="active",
        decay_policy="reinforce_only",
    )

    container = client.app.state.container
    matching = container.orchestrator.create_human_task(
        session_id=seeded["session_id"],
        principal_id=principal_id,
        task_type="handoff",
        role_required="operator",
        brief="KfA rehab authorization follow-up",
        why_human="Need to review the KfA rehab approval and physio authorization paperwork.",
        priority="normal",
        sla_due_at="2026-05-29T09:00:00+00:00",
    )
    generic = container.orchestrator.create_human_task(
        session_id=seeded["session_id"],
        principal_id=principal_id,
        task_type="handoff",
        role_required="operator",
        brief="General inbox cleanup",
        why_human="Clear a general inbox backlog item.",
        priority="normal",
        sla_due_at="2026-05-29T09:00:00+00:00",
    )

    queue = client.get("/app/api/queue")
    assert queue.status_code == 200
    items = [
        row
        for row in queue.json()["items"]
        if row["id"] in {f"human_task:{matching.human_task_id}", f"human_task:{generic.human_task_id}"}
    ]
    assert len(items) == 2
    assert items[0]["id"] == f"human_task:{matching.human_task_id}"
    assert items[0]["rank_score"] > items[1]["rank_score"]


def test_brief_items_use_profile_admin_boost_for_matching_tasks() -> None:
    principal_id = "exec-product-profile-brief-boost"
    client = build_product_client(principal_id=principal_id)
    seeded = seed_product_state(client, principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Profile Brief Boost Office")
    product = ProductService(client.app.state.container)

    product.upsert_preference_profile(
        principal_id=principal_id,
        person_id="self",
        display_name="Tibor Girschele",
        learning_enabled=True,
    )
    product.upsert_preference_node(
        principal_id=principal_id,
        person_id="self",
        domain="life_admin",
        category="insurance_admin",
        key="rehab_authorization_management",
        value_json={
            "enabled": True,
            "entities": ["KfA", "NRZ"],
            "focus_areas": ["rehab_authorizations", "physio_ergo_approvals"],
        },
        strength="high",
        confidence=0.9,
        source_mode="inferred",
        status="active",
        decay_policy="reinforce_only",
    )

    container = client.app.state.container
    matching = container.orchestrator.create_human_task(
        session_id=seeded["session_id"],
        principal_id=principal_id,
        task_type="handoff",
        role_required="operator",
        brief="KfA rehab authorization follow-up",
        why_human="Need to review the KfA rehab approval and physio authorization paperwork.",
        priority="normal",
        sla_due_at="2026-05-29T09:00:00+00:00",
    )
    generic = container.orchestrator.create_human_task(
        session_id=seeded["session_id"],
        principal_id=principal_id,
        task_type="handoff",
        role_required="operator",
        brief="General inbox cleanup",
        why_human="Clear a general inbox backlog item.",
        priority="normal",
        sla_due_at="2026-05-29T09:00:00+00:00",
    )

    brief = client.get("/app/api/brief")
    assert brief.status_code == 200
    items = [
        row
        for row in brief.json()["items"]
        if row["object_ref"] in {f"human_task:{matching.human_task_id}", f"human_task:{generic.human_task_id}"}
    ]
    assert len(items) == 2
    assert items[0]["object_ref"] == f"human_task:{matching.human_task_id}"
    assert items[0]["score"] > items[1]["score"]


def test_brief_items_include_proactive_profile_followup() -> None:
    principal_id = "exec-product-profile-proactive-brief"
    client = build_product_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Profile Proactive Brief Office")
    product = ProductService(client.app.state.container)

    product.upsert_preference_profile(
        principal_id=principal_id,
        person_id="self",
        display_name="Tibor Girschele",
        learning_enabled=True,
    )
    product.upsert_preference_node(
        principal_id=principal_id,
        person_id="self",
        domain="life_admin",
        category="insurance_admin",
        key="rehab_authorization_management",
        value_json={
            "enabled": True,
            "entities": ["KfA", "NRZ"],
            "focus_areas": ["rehab_authorizations", "physio_ergo_approvals"],
        },
        strength="high",
        confidence=0.9,
        source_mode="inferred",
        status="active",
        decay_policy="reinforce_only",
    )
    product.record_preference_evidence(
        principal_id=principal_id,
        person_id="self",
        domain="document_ingest",
        event_type="document_pattern_detected",
        object_type="scanned_document_batch",
        object_id="onedrive:tibor-insurance-rehab-authorizations",
        source_ref="/mnt/onedrive/Documents/Scanned Documents",
        raw_signal_json={"sample_documents": ["20250615 Kfa Bewilligung Physio.pdf"]},
        interpreted_signal_json={"summary": "Recurring KfA and rehab authorization paperwork."},
        signal_strength=0.9,
        reversible=True,
    )

    brief = client.get("/app/api/brief")
    assert brief.status_code == 200
    row = next(item for item in brief.json()["items"] if item["object_ref"] == "profile_followup:insurance_admin:rehab_authorization_management")
    assert row["title"] == "Review rehab approvals and KfA authorization status"
    assert row["recommended_action"] == "check rehab approvals"
    assert row["score"] > 60


def test_channel_loop_memo_surfaces_proactive_profile_followup() -> None:
    principal_id = "exec-product-profile-memo-followup"
    client = build_product_client(principal_id=principal_id)
    seeded = seed_product_state(client, principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Profile Memo Followup Office")
    product = ProductService(client.app.state.container)

    product.upsert_preference_profile(
        principal_id=principal_id,
        person_id="self",
        display_name="Tibor Girschele",
        learning_enabled=True,
    )
    product.upsert_preference_node(
        principal_id=principal_id,
        person_id="self",
        domain="life_admin",
        category="insurance_admin",
        key="rehab_authorization_management",
        value_json={
            "enabled": True,
            "entities": ["KfA", "NRZ"],
            "focus_areas": ["rehab_authorizations", "physio_ergo_approvals"],
        },
        strength="high",
        confidence=0.9,
        source_mode="inferred",
        status="active",
        decay_policy="reinforce_only",
    )
    product.record_preference_evidence(
        principal_id=principal_id,
        person_id="self",
        domain="document_ingest",
        event_type="document_pattern_detected",
        object_type="scanned_document_batch",
        object_id="onedrive:tibor-insurance-rehab-authorizations",
        source_ref="/mnt/onedrive/Documents/Scanned Documents",
        raw_signal_json={"sample_documents": ["20250615 Kfa Bewilligung Physio.pdf"]},
        interpreted_signal_json={"summary": "Recurring KfA and rehab authorization paperwork."},
        signal_strength=0.9,
        reversible=True,
    )

    container = client.app.state.container
    container.orchestrator.create_human_task(
        session_id=seeded["session_id"],
        principal_id=principal_id,
        task_type="handoff",
        role_required="operator",
        brief="Property review 1",
        why_human="Review apartment alert in Waehring.",
        priority="high",
        sla_due_at="2026-05-29T09:00:00+00:00",
    )
    container.orchestrator.create_human_task(
        session_id=seeded["session_id"],
        principal_id=principal_id,
        task_type="handoff",
        role_required="operator",
        brief="Property review 2",
        why_human="Review apartment alert in Doebling.",
        priority="high",
        sla_due_at="2026-05-29T09:00:00+00:00",
    )

    loop = client.get("/app/api/channel-loop")
    assert loop.status_code == 200
    memo_digest = next(item for item in loop.json()["digests"] if item["key"] == "memo")
    proactive = next(item for item in memo_digest["items"] if item["title"] == "Review rehab approvals and KfA authorization status")
    assert proactive["tag"] == "Profile follow-up"


def test_channel_loop_memo_suppresses_recent_profile_followup_nudge() -> None:
    principal_id = "exec-product-profile-memo-followup-cooldown"
    client = build_product_client(principal_id=principal_id)
    seed_product_state(client, principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Profile Memo Followup Cooldown Office")
    product = ProductService(client.app.state.container)

    product.upsert_preference_profile(
        principal_id=principal_id,
        person_id="self",
        display_name="Tibor Girschele",
        learning_enabled=True,
    )
    product.upsert_preference_node(
        principal_id=principal_id,
        person_id="self",
        domain="life_admin",
        category="insurance_admin",
        key="rehab_authorization_management",
        value_json={"enabled": True},
        strength="high",
        confidence=0.9,
        source_mode="inferred",
        status="active",
        decay_policy="reinforce_only",
    )
    product.record_preference_evidence(
        principal_id=principal_id,
        person_id="self",
        domain="document_ingest",
        event_type="document_pattern_detected",
        object_type="scanned_document_batch",
        object_id="onedrive:tibor-insurance-rehab-authorizations",
        source_ref="/mnt/onedrive/Documents/Scanned Documents",
        raw_signal_json={"sample_documents": ["20250615 Kfa Bewilligung Physio.pdf"]},
        interpreted_signal_json={"summary": "Recurring KfA and rehab authorization paperwork."},
        signal_strength=0.9,
        reversible=True,
    )
    product._record_product_event(
        principal_id=principal_id,
        event_type="profile_followup_nudged",
        payload={
            "object_ref": "profile_followup:insurance_admin:rehab_authorization_management",
            "title": "Review rehab approvals and KfA authorization status",
        },
        source_id="memo-cooldown-test",
        dedupe_key=f"{principal_id}|memo-cooldown-test|profile_followup:insurance_admin:rehab_authorization_management|profile-followup-nudged",
    )

    loop = client.get("/app/api/channel-loop")
    assert loop.status_code == 200
    memo_digest = next(item for item in loop.json()["digests"] if item["key"] == "memo")
    assert all(item["title"] != "Review rehab approvals and KfA authorization status" for item in memo_digest["items"])


def test_issue_channel_digest_delivery_records_profile_followup_nudge() -> None:
    principal_id = "exec-product-profile-memo-followup-receipt"
    client = build_product_client(principal_id=principal_id)
    seed_product_state(client, principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Profile Memo Followup Receipt Office")
    product = ProductService(client.app.state.container)

    product.upsert_preference_profile(
        principal_id=principal_id,
        person_id="self",
        display_name="Tibor Girschele",
        learning_enabled=True,
    )
    product.upsert_preference_node(
        principal_id=principal_id,
        person_id="self",
        domain="life_admin",
        category="insurance_admin",
        key="rehab_authorization_management",
        value_json={"enabled": True},
        strength="high",
        confidence=0.9,
        source_mode="inferred",
        status="active",
        decay_policy="reinforce_only",
    )
    product.record_preference_evidence(
        principal_id=principal_id,
        person_id="self",
        domain="document_ingest",
        event_type="document_pattern_detected",
        object_type="scanned_document_batch",
        object_id="onedrive:tibor-insurance-rehab-authorizations",
        source_ref="/mnt/onedrive/Documents/Scanned Documents",
        raw_signal_json={"sample_documents": ["20250615 Kfa Bewilligung Physio.pdf"]},
        interpreted_signal_json={"summary": "Recurring KfA and rehab authorization paperwork."},
        signal_strength=0.9,
        reversible=True,
    )

    delivery = product.issue_channel_digest_delivery(
        principal_id=principal_id,
        digest_key="memo",
        recipient_email="tibor@example.com",
        role="principal",
        delivery_channel="email",
    )
    assert delivery is not None

    rows = list(client.app.state.container.channel_runtime.list_recent_observations(limit=50, principal_id=principal_id))
    nudge = next(
        row
        for row in rows
        if str(row.channel or "") == "product" and str(row.event_type or "").strip().lower() == "profile_followup_nudged"
    )
    assert str((nudge.payload or {}).get("object_ref") or "") == "profile_followup:insurance_admin:rehab_authorization_management"
    assert str((nudge.payload or {}).get("recommended_action") or "") == "check rehab approvals"


def test_channel_loop_exposes_actionable_assistant_nudge_without_grounding_noise() -> None:
    principal_id = "exec-product-assistant-nudge-digest"
    client = build_product_client(principal_id=principal_id)
    seed_product_state(client, principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Assistant Nudge Office")
    product = ProductService(client.app.state.container)

    product.upsert_preference_profile(
        principal_id=principal_id,
        person_id="self",
        display_name="Tibor Girschele",
        learning_enabled=True,
    )
    product.upsert_preference_node(
        principal_id=principal_id,
        person_id="self",
        domain="life_admin",
        category="insurance_admin",
        key="rehab_authorization_management",
        value_json={"enabled": True},
        strength="high",
        confidence=0.9,
        source_mode="inferred",
        status="active",
        decay_policy="reinforce_only",
    )
    product.record_preference_evidence(
        principal_id=principal_id,
        person_id="self",
        domain="document_ingest",
        event_type="document_pattern_detected",
        object_type="scanned_document_batch",
        object_id="onedrive:tibor-insurance-rehab-authorizations",
        source_ref="/mnt/onedrive/Documents/Scanned Documents",
        raw_signal_json={"sample_documents": ["20250615 Kfa Bewilligung Physio.pdf"]},
        interpreted_signal_json={"summary": "Recurring KfA and rehab authorization paperwork."},
        signal_strength=0.9,
        reversible=True,
    )

    loop = client.get("/app/api/channel-loop")
    assert loop.status_code == 200
    assistant_nudge = next(item for item in loop.json()["digests"] if item["key"] == "assistant_nudge")
    assert assistant_nudge["summary"] == "Only the items where you need to do something now."
    assert any(item["tag"] == "Profile follow-up" for item in assistant_nudge["items"])
    assert all(item["tag"] != "Grounding" for item in assistant_nudge["items"])


def test_channel_loop_memo_reopens_profile_followup_after_fresh_evidence(monkeypatch) -> None:
    principal_id = "exec-product-profile-memo-followup-fresh-evidence"
    client = build_product_client(principal_id=principal_id)
    seed_product_state(client, principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Profile Memo Followup Fresh Evidence Office")
    product = ProductService(client.app.state.container)

    product.upsert_preference_profile(
        principal_id=principal_id,
        person_id="self",
        display_name="Tibor Girschele",
        learning_enabled=True,
    )
    product.upsert_preference_node(
        principal_id=principal_id,
        person_id="self",
        domain="life_admin",
        category="insurance_admin",
        key="rehab_authorization_management",
        value_json={"enabled": True},
        strength="high",
        confidence=0.9,
        source_mode="inferred",
        status="active",
        decay_policy="reinforce_only",
    )
    product.record_preference_evidence(
        principal_id=principal_id,
        person_id="self",
        domain="document_ingest",
        event_type="document_pattern_detected",
        object_type="scanned_document_batch",
        object_id="onedrive:tibor-insurance-rehab-authorizations-old",
        source_ref="/mnt/onedrive/Documents/Scanned Documents",
        raw_signal_json={"sample_documents": ["20250615 Kfa Bewilligung Physio.pdf"]},
        interpreted_signal_json={"summary": "Recurring KfA and rehab authorization paperwork."},
        signal_strength=0.9,
        reversible=True,
    )
    product._record_product_event(
        principal_id=principal_id,
        event_type="profile_followup_nudged",
        payload={
            "object_ref": "profile_followup:insurance_admin:rehab_authorization_management",
            "title": "Review rehab approvals and KfA authorization status",
        },
        source_id="memo-fresh-evidence-test",
        dedupe_key=f"{principal_id}|memo-fresh-evidence-test|profile_followup:insurance_admin:rehab_authorization_management|profile-followup-nudged",
    )
    product.record_preference_evidence(
        principal_id=principal_id,
        person_id="self",
        domain="document_ingest",
        event_type="document_pattern_detected",
        object_type="scanned_document_batch",
        object_id="onedrive:tibor-insurance-rehab-authorizations-new",
        source_ref="/mnt/onedrive/Documents/Scanned Documents",
        raw_signal_json={"sample_documents": ["20250705_Rehaantrag KfA Ablehnung.pdf"]},
        interpreted_signal_json={"summary": "Fresh KfA rehab authorization paperwork arrived after the last nudge."},
        signal_strength=0.95,
        reversible=True,
    )
    monkeypatch.setattr(
        ProductService,
        "_profile_followup_latest_evidence_at",
        lambda self, **kwargs: product_service._utcnow() + timedelta(minutes=5),
    )

    loop = client.get("/app/api/channel-loop")
    assert loop.status_code == 200
    memo_digest = next(item for item in loop.json()["digests"] if item["key"] == "memo")
    proactive = next(item for item in memo_digest["items"] if item["title"] == "Review rehab approvals and KfA authorization status")
    assert proactive["tag"] == "Profile follow-up"


def test_profile_followup_uses_category_specific_cooldown(monkeypatch) -> None:
    principal_id = "exec-product-profile-followup-category-cooldown"
    client = build_product_client(principal_id=principal_id)
    seed_product_state(client, principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Profile Followup Category Cooldown Office")
    product = ProductService(client.app.state.container)

    product.upsert_preference_profile(
        principal_id=principal_id,
        person_id="self",
        display_name="Elisabeth Girschele",
        learning_enabled=True,
    )
    product.upsert_preference_node(
        principal_id=principal_id,
        person_id="self",
        domain="life_admin",
        category="utilities_admin",
        key="utility_and_provider_account_management",
        value_json={"enabled": True},
        strength="high",
        confidence=0.9,
        source_mode="inferred",
        status="active",
        decay_policy="reinforce_only",
    )
    product._record_product_event(
        principal_id=principal_id,
        event_type="profile_followup_nudged",
        payload={
            "object_ref": "profile_followup:utilities_admin:utility_and_provider_account_management",
            "title": "Review utility and provider account admin",
        },
        source_id="memo-category-cooldown-test",
        dedupe_key=f"{principal_id}|memo-category-cooldown-test|profile_followup:utilities_admin:utility_and_provider_account_management|profile-followup-nudged",
    )

    monkeypatch.setattr(product_service, "_utcnow", lambda: product_service._parse_iso("2026-05-28T18:00:00+00:00"))
    monkeypatch.setattr(
        product,
        "_profile_followup_latest_evidence_at",
        lambda **kwargs: product_service._parse_iso("2026-05-27T00:00:00+00:00"),
    )
    assert product._profile_followup_nudge_allowed(
        principal_id=principal_id,
        object_ref="profile_followup:utilities_admin:utility_and_provider_account_management",
    ) is False


def test_queue_item_exposes_explicit_profile_followup_refs() -> None:
    principal_id = "exec-product-profile-followup-queue-refs"
    client = build_product_client(principal_id=principal_id)
    seed_product_state(client, principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Profile Followup Queue Refs Office")
    product = ProductService(client.app.state.container)

    product.upsert_preference_profile(
        principal_id=principal_id,
        person_id="self",
        display_name="Tibor Girschele",
        learning_enabled=True,
    )
    product.upsert_preference_node(
        principal_id=principal_id,
        person_id="self",
        domain="life_admin",
        category="insurance_admin",
        key="rehab_authorization_management",
        value_json={"enabled": True},
        strength="high",
        confidence=0.9,
        source_mode="inferred",
        status="active",
        decay_policy="reinforce_only",
    )
    decision = client.app.state.container.memory_runtime.upsert_decision_window(
        principal_id=principal_id,
        title="Check KfA rehab authorization",
        context="Follow up on rehab Bewilligung and KfA paperwork.",
        opens_at="2026-05-28T09:00:00+00:00",
        closes_at="2026-05-29T09:00:00+00:00",
        urgency="high",
        authority_required="principal",
        status="open",
        notes="Waiting on rehab paperwork update.",
        source_json={"source": "test"},
    )

    queue_item = product._queue_item_from_decision(decision)
    assert queue_item.profile_followup_refs == ("profile_followup:insurance_admin:rehab_authorization_management",)


def test_brief_item_exposes_explicit_profile_followup_refs() -> None:
    principal_id = "exec-product-profile-followup-brief-refs"
    client = build_product_client(principal_id=principal_id)
    seed_product_state(client, principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Profile Followup Brief Refs Office")
    product = ProductService(client.app.state.container)

    product.upsert_preference_profile(
        principal_id=principal_id,
        person_id="self",
        display_name="Tibor Girschele",
        learning_enabled=True,
    )
    product.upsert_preference_node(
        principal_id=principal_id,
        person_id="self",
        domain="life_admin",
        category="insurance_admin",
        key="rehab_authorization_management",
        value_json={"enabled": True},
        strength="high",
        confidence=0.9,
        source_mode="inferred",
        status="active",
        decay_policy="reinforce_only",
    )
    decision = client.app.state.container.memory_runtime.upsert_decision_window(
        principal_id=principal_id,
        title="Check KfA rehab authorization",
        context="Follow up on rehab Bewilligung and KfA paperwork.",
        opens_at="2026-05-28T09:00:00+00:00",
        closes_at="2026-05-29T09:00:00+00:00",
        urgency="high",
        authority_required="principal",
        status="open",
        notes="Waiting on rehab paperwork update.",
        source_json={"source": "test"},
    )

    brief_item = product._brief_item_from_decision(product._decision_item_from_window(decision), workspace_id=principal_id)
    assert brief_item.profile_followup_refs == ("profile_followup:insurance_admin:rehab_authorization_management",)


def test_channel_loop_memo_item_carries_profile_followup_refs() -> None:
    principal_id = "exec-product-profile-followup-memo-refs"
    client = build_product_client(principal_id=principal_id)
    seed_product_state(client, principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Profile Followup Memo Refs Office")
    product = ProductService(client.app.state.container)

    product.upsert_preference_profile(
        principal_id=principal_id,
        person_id="self",
        display_name="Tibor Girschele",
        learning_enabled=True,
    )
    product.upsert_preference_node(
        principal_id=principal_id,
        person_id="self",
        domain="life_admin",
        category="insurance_admin",
        key="rehab_authorization_management",
        value_json={"enabled": True},
        strength="high",
        confidence=0.9,
        source_mode="inferred",
        status="active",
        decay_policy="reinforce_only",
    )
    product.record_preference_evidence(
        principal_id=principal_id,
        person_id="self",
        domain="document_ingest",
        event_type="document_pattern_detected",
        object_type="scanned_document_batch",
        object_id="onedrive:tibor-insurance-rehab-authorizations",
        source_ref="/mnt/onedrive/Documents/Scanned Documents",
        raw_signal_json={"sample_documents": ["20250615 Kfa Bewilligung Physio.pdf"]},
        interpreted_signal_json={"summary": "Recurring KfA and rehab authorization paperwork."},
        signal_strength=0.9,
        reversible=True,
    )

    loop = client.get("/app/api/channel-loop")
    assert loop.status_code == 200
    memo_digest = next(item for item in loop.json()["digests"] if item["key"] == "memo")
    proactive = next(item for item in memo_digest["items"] if item["title"] == "Review rehab approvals and KfA authorization status")
    assert proactive["profile_followup_refs"] == ["profile_followup:insurance_admin:rehab_authorization_management"]


def test_queue_resolution_suppresses_matching_profile_followup() -> None:
    principal_id = "exec-product-profile-followup-resolution-suppression"
    client = build_product_client(principal_id=principal_id)
    seed_product_state(client, principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Profile Followup Resolution Suppression Office")
    product = ProductService(client.app.state.container)

    product.upsert_preference_profile(
        principal_id=principal_id,
        person_id="self",
        display_name="Tibor Girschele",
        learning_enabled=True,
    )
    product.upsert_preference_node(
        principal_id=principal_id,
        person_id="self",
        domain="life_admin",
        category="insurance_admin",
        key="rehab_authorization_management",
        value_json={"enabled": True},
        strength="high",
        confidence=0.9,
        source_mode="inferred",
        status="active",
        decay_policy="reinforce_only",
    )
    product.record_preference_evidence(
        principal_id=principal_id,
        person_id="self",
        domain="document_ingest",
        event_type="document_pattern_detected",
        object_type="scanned_document_batch",
        object_id="onedrive:tibor-insurance-rehab-authorizations",
        source_ref="/mnt/onedrive/Documents/Scanned Documents",
        raw_signal_json={"sample_documents": ["20250615 Kfa Bewilligung Physio.pdf"]},
        interpreted_signal_json={"summary": "Recurring KfA and rehab authorization paperwork."},
        signal_strength=0.9,
        reversible=True,
    )
    decision = client.app.state.container.memory_runtime.upsert_decision_window(
        principal_id=principal_id,
        title="Check KfA rehab authorization",
        context="Follow up on rehab Bewilligung and KfA paperwork.",
        opens_at="2026-05-28T09:00:00+00:00",
        closes_at="2026-05-29T09:00:00+00:00",
        urgency="high",
        authority_required="principal",
        status="open",
        notes="Waiting on rehab paperwork update.",
        source_json={"source": "test"},
    )

    product.resolve_queue_item(
        principal_id=principal_id,
        item_ref=f"decision:{decision.decision_window_id}",
        action="defer",
        actor="tibor",
        reason="Waiting on rehab paperwork update.",
    )

    rows = list(client.app.state.container.channel_runtime.list_recent_observations(limit=50, principal_id=principal_id))
    resolution = next(
        row
        for row in rows
        if str(row.channel or "") == "product" and str(row.event_type or "").strip().lower() == "profile_followup_resolution_recorded"
    )
    assert str((resolution.payload or {}).get("object_ref") or "") == "profile_followup:insurance_admin:rehab_authorization_management"
    assert str((resolution.payload or {}).get("action") or "") == "defer"

    loop = client.get("/app/api/channel-loop")
    assert loop.status_code == 200
    memo_digest = next(item for item in loop.json()["digests"] if item["key"] == "memo")
    assert all(item["title"] != "Review rehab approvals and KfA authorization status" for item in memo_digest["items"])


def test_profile_followup_resolution_suppression_expires(monkeypatch) -> None:
    principal_id = "exec-product-profile-followup-resolution-expiry"
    client = build_product_client(principal_id=principal_id)
    seed_product_state(client, principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Profile Followup Resolution Expiry Office")
    product = ProductService(client.app.state.container)

    product.upsert_preference_profile(
        principal_id=principal_id,
        person_id="self",
        display_name="Elisabeth Girschele",
        learning_enabled=True,
    )
    product.upsert_preference_node(
        principal_id=principal_id,
        person_id="self",
        domain="life_admin",
        category="utilities_admin",
        key="utility_and_provider_account_management",
        value_json={"enabled": True},
        strength="high",
        confidence=0.9,
        source_mode="inferred",
        status="active",
        decay_policy="reinforce_only",
    )
    monkeypatch.setattr(product_service, "_utcnow", lambda: product_service._parse_iso("2026-05-30T00:00:00+00:00"))
    product._record_product_event(
        principal_id=principal_id,
        event_type="profile_followup_resolution_recorded",
        payload={
            "object_ref": "profile_followup:utilities_admin:utility_and_provider_account_management",
            "action": "defer",
            "cooldown_hours": 36,
        },
        source_id="old-resolution-test",
        dedupe_key=f"{principal_id}|old-resolution-test|profile_followup:utilities_admin:utility_and_provider_account_management|profile-followup-resolution|defer",
    )
    monkeypatch.setattr(product_service, "_utcnow", lambda: product_service._parse_iso("2099-06-01T12:00:00+00:00"))
    monkeypatch.setattr(
        product,
        "_profile_followup_latest_evidence_at",
        lambda **kwargs: product_service._parse_iso("2026-05-27T00:00:00+00:00"),
    )
    assert product._profile_followup_nudge_allowed(
        principal_id=principal_id,
        object_ref="profile_followup:utilities_admin:utility_and_provider_account_management",
    ) is True


def test_signal_ingest_willhaben_search_agent_mail_can_auto_create_and_send_to_tibor(monkeypatch) -> None:
    from app.domain.models import Artifact
    from app.services.registration_email import RegistrationEmailReceipt

    monkeypatch.setenv("EA_WILLHABEN_SEARCH_AGENT_AUTO_CREATE_PROPERTY_TOUR", "1")
    monkeypatch.setenv("EA_WILLHABEN_PROPERTY_TOUR_REQUIRE_360", "0")
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


def test_willhaben_property_tour_route_generates_tour_and_sends_email(monkeypatch, tmp_path: Path) -> None:
    from app.domain.models import Artifact
    from app.services.registration_email import RegistrationEmailReceipt

    monkeypatch.setenv("EMAILIT_API_KEY", "test-emailit-key")
    monkeypatch.setenv("EA_WILLHABEN_PROPERTY_TOUR_REQUIRE_360", "0")
    monkeypatch.setenv("EA_PUBLIC_TOUR_DIR", str(tmp_path))
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
            "decision_summary": {
                "good_fit_reasons": ["A floor plan is available."],
                "bad_fit_reasons": ["Gas heating may raise running-cost risk."],
                "unknowns": ["Check noise and privacy in person."],
                "recommendation": "shortlist",
            },
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
    monkeypatch.setattr(
        product_service,
        "resolve_primary_telegram_binding",
        lambda tool_runtime, *, principal_id: SimpleNamespace(
            external_account_ref="1354554303",
            auth_metadata_json={"default_chat_ref": "1354554303"},
        ),
    )
    monkeypatch.setattr(
        product_service,
        "send_telegram_message_for_principal",
        lambda tool_runtime, *, principal_id, text: SimpleNamespace(
            chat_id="1354554303",
            bot_key="default",
            bot_handle="tibor_concierge_bot",
            message_ids=("tg-1",),
        ),
    )
    monkeypatch.setattr(
        product_service,
        "send_telegram_video_for_principal",
        lambda tool_runtime, *, principal_id, video_ref, audio_probe_ref="", caption="": SimpleNamespace(
            chat_id="1354554303",
            bot_key="default",
            bot_handle="tibor_concierge_bot",
            message_ids=("tg-video-1",),
        ),
    )

    def _fake_execute_task_artifact(request):  # type: ignore[no-untyped-def]
        assert request.task_key in {
            "create_property_tour",
            "ltd_runtime__crezlo_tours__create_property_tour",
        }
        assert request.input_json["binding_id"] == "browseract-binding-1"
        assert request.input_json["force_ui_worker"] is False
        assert request.input_json["proxy_result"] is True
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
    bundle_dir = tmp_path / "brigittenau-apartment-a"
    bundle_dir.mkdir(parents=True)
    (bundle_dir / "tour.mp4").write_bytes(b"fake-video")
    (bundle_dir / "tour.json").write_text(
        '{"slug":"brigittenau-apartment-a","video_relpath":"tour.mp4","scenes":[{"asset_relpath":"scene-01.jpg"}]}',
        encoding="utf-8",
    )
    (bundle_dir / "scene-01.jpg").write_bytes(b"scene")

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
    assert body["telegram_delivery_status"] == "sent"
    assert body["telegram_chat_ref"] == "1354554303"
    assert body["telegram_message_ids"] == ["tg-1"]
    assert body["telegram_video_delivery_status"] == "sent"
    assert body["telegram_video_message_ids"] == ["tg-video-1"]
    assert body["telegram_video_url"] == "https://myexternalbrain.com/tours/files/brigittenau-apartment-a/tour.mp4"
    assert observed_email["recipient_email"] == "tibor.girschele@gmail.com"
    assert observed_email["tour_url"] == "https://myexternalbrain.com/tours/brigittenau-apartment-a"
    assert observed_email["decision_summary_json"]["recommendation"] == "shortlist"

    events = client.get(
        "/app/api/events",
        params={"channel": "product", "event_type": "willhaben_property_tour_email_sent"},
    )
    assert events.status_code == 200
    assert any(item["payload"]["delivery_email"] == "tibor.girschele@gmail.com" for item in events.json()["items"])
    tg_events = client.get(
        "/app/api/events",
        params={"channel": "product", "event_type": "willhaben_property_tour_telegram_sent"},
    )
    assert tg_events.status_code == 200
    assert any(item["payload"]["telegram_chat_ref"] == "1354554303" for item in tg_events.json()["items"])
    tg_video_events = client.get(
        "/app/api/events",
        params={"channel": "product", "event_type": "willhaben_property_tour_telegram_video_sent"},
    )
    assert tg_video_events.status_code == 200
    assert any(item["payload"]["telegram_video_url"].endswith("/tour.mp4") for item in tg_video_events.json()["items"])


def test_property_tour_delivery_message_includes_decision_reasoning() -> None:
    subject, body = product_service._property_tour_delivery_message(
        property_title="Bright Brigittenau apartment",
        property_url="https://www.willhaben.at/test-listing",
        tour_url="https://myexternalbrain.com/tours/test-listing",
        variant_key="layout_first",
        listing_id="listing-123",
        area_label="74 m²",
        rooms_label="3 rooms",
        price_label="EUR 1890",
        decision_summary_json={
            "good_fit_reasons": ["A floor plan is available."],
            "bad_fit_reasons": ["Gas heating may raise running-cost risk."],
            "unknowns": ["Check noise and privacy in person."],
            "recommendation": "shortlist",
            "location_fit_score": 5,
            "livability_snapshot": {
                "nearest_transit_m": 280,
                "nearest_supermarket_m": 190,
                "nearest_pharmacy_m": 320,
                "nearest_bicycle_parking_m": 110,
                "nearest_cycleway_m": 260,
                "nearest_running_m": 780,
            },
        },
    )

    assert "Apartment tour ready: Bright Brigittenau apartment" in subject
    assert "Recommendation: shortlist" in body
    assert "Neighborhood fit score: 5" in body
    assert "Neighborhood snapshot:" in body
    assert "Transit: about 280 m" in body
    assert "Bicycle parking: about 110 m" in body
    assert "Why it could fit:" in body
    assert "Why it may not fit:" in body
    assert "What still needs checking:" in body


def test_property_tour_delivery_message_accepts_personal_fit_assessment_shape() -> None:
    subject, body = product_service._property_tour_delivery_message(
        property_title="Strong Waehring apartment",
        property_url="https://www.willhaben.at/test-fit-listing",
        tour_url="https://myexternalbrain.com/tours/test-fit-listing",
        decision_summary_json={
            "fit_score": 96.0,
            "recommendation": "shortlist",
            "match_reasons_json": ["The listing is in Waehring, which matches established district preferences."],
            "mismatch_reasons_json": ["Gas heating may raise running-cost risk."],
            "unknowns_json": ["Check noise in person."],
        },
    )

    assert "Apartment tour ready: Strong Waehring apartment" in subject
    assert "Personal fit score: 96/100" in body
    assert "Recommendation: shortlist" in body
    assert "Why it could fit:" in body
    assert "Why it may not fit:" in body
    assert "What still needs checking:" in body


def test_property_alert_review_telegram_text_includes_top_candidate_summary() -> None:
    text = product_service._property_alert_review_telegram_text(
        title='"Eigentumswohnungen" hat 5 neue Anzeigen für dich gefunden',
        summary="Recent mail from willhaben-Suchagent.",
        counterparty="willhaben-Suchagent",
        account_email="elisabeth.girschele@gmail.com",
        property_url="",
        personal_fit_assessment=None,
        candidate_properties=(
            {
                "property_url": "https://www.willhaben.at/iad/immobilien/d/mietwohnungen/wien/top-fit-1",
                "listing_title": "Bright Waehring apartment with balcony",
                "fit_score": 91.0,
                "recommendation": "shortlist",
                "fit_summary": "Personal fit 91/100 · shortlist · The listing is in Waehring, which matches established district preferences.",
                "assessment": {"fit_score": 91.0, "recommendation": "shortlist"},
            },
            {
                "property_url": "https://www.willhaben.at/iad/immobilien/d/mietwohnungen/wien/top-fit-2",
                "fit_score": 74.0,
                "recommendation": "mention",
                "fit_summary": "Personal fit 74/100 · mention",
            },
        ),
    )

    assert "Title: Bright Waehring apartment with balcony" in text
    assert "EA found 2 concrete listings in this alert." in text
    assert "Top candidate: Personal fit 91/100" in text
    assert "Top listing: https://www.willhaben.at/iad/immobilien/d/mietwohnungen/wien/top-fit-1" in text
    assert "Next: open the listing and generate a tour." in text


def test_property_alert_review_telegram_text_prefers_internal_tour_link() -> None:
    text = product_service._property_alert_review_telegram_text(
        title="Watch fit apartment",
        summary="Recent scout hit.",
        counterparty="IMMMO",
        account_email="elisabeth.girschele@gmail.com",
        property_url="https://www.immobilienscout24.at/expose/watch-fit-1",
        personal_fit_assessment={"fit_score": 91.0, "recommendation": "shortlist"},
        candidate_properties=(
            {
                "property_url": "https://www.immobilienscout24.at/expose/watch-fit-1",
                "listing_title": "Watch fit apartment",
                "fit_score": 91.0,
                "recommendation": "shortlist",
                "fit_summary": "Personal fit 91/100 · shortlist",
                "assessment": {"fit_score": 91.0, "recommendation": "shortlist"},
            },
        ),
        tour_url="https://myexternalbrain.com/tours/watch-fit-1",
    )

    assert "3D tour: https://myexternalbrain.com/tours/watch-fit-1" in text
    assert "Listing: https://www.immobilienscout24.at/expose/watch-fit-1" not in text
    assert "Top listing: https://www.immobilienscout24.at/expose/watch-fit-1" not in text


def test_property_alert_review_telegram_text_prefers_review_link_over_listing() -> None:
    text = product_service._property_alert_review_telegram_text(
        title="Watch fit apartment",
        summary="Recent scout hit.",
        counterparty="IMMMO",
        account_email="elisabeth.girschele@gmail.com",
        property_url="https://www.immobilienscout24.at/expose/watch-fit-1",
        personal_fit_assessment={"fit_score": 91.0, "recommendation": "shortlist"},
        candidate_properties=(
            {
                "property_url": "https://www.immobilienscout24.at/expose/watch-fit-1",
                "listing_title": "Watch fit apartment",
                "fit_score": 91.0,
                "recommendation": "shortlist",
                "fit_summary": "Personal fit 91/100 · shortlist",
                "assessment": {"fit_score": 91.0, "recommendation": "shortlist"},
            },
        ),
        review_url="https://myexternalbrain.com/workspace-access/test-token?return_to=%2Fapp%2Fhandoffs%2Fhuman_task%3Atest-1",
    )

    assert "Review: https://myexternalbrain.com/workspace-access/test-token" in text
    assert "Listing: https://www.immobilienscout24.at/expose/watch-fit-1" not in text
    assert "Top listing: https://www.immobilienscout24.at/expose/watch-fit-1" not in text


def test_generic_property_tour_creates_myexternalbrain_tour_for_immoscout(monkeypatch) -> None:
    from app.domain.models import Artifact

    principal_id = "cf-email:tibor.girschele@gmail.com"
    client = build_product_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Generic Property Tour Office")
    service = ProductService(client.app.state.container)
    property_url = "https://www.immobilienscout24.at/expose/generic-fit-1"

    monkeypatch.setattr(ProductService, "_resolve_browseract_property_tour_binding_id", lambda self, **kwargs: "browseract-binding-1")
    monkeypatch.setattr(
        product_service,
        "_property_scout_page_preview",
        lambda url: {
            "listing_id": "generic-fit-1",
            "title": "Generic Waehring apartment",
            "summary": "Waehring, lift, balcony, 360 tour, floorplan",
            "property_facts_json": {
                "district": "Waehring",
                "has_360": True,
                "has_floorplan": True,
                "source_virtual_tour_url": "https://360.example.test/generic-fit-1",
                "panorama_source": "provider_live_360",
            },
            "media_urls_json": ["https://cdn.example.com/generic/photo.jpg"],
            "floorplan_urls_json": ["https://cdn.example.com/generic/floorplan.jpg"],
        },
    )
    monkeypatch.setattr(
        product_service,
        "_merge_property_facts_with_source_research",
        lambda *, property_url, property_facts, image_urls=(): {
            **dict(property_facts),
            "street_address": "Hameaustraße 34",
            "nearest_supermarket_m": 951,
            "nearest_pharmacy_m": 882,
            "nearest_playground_m": 532,
            "nearest_subway_m": 4752,
            "listing_research_snapshot": {
                "street_address": "Hameaustraße 34",
                "nearest_supermarket_m": 951,
                "nearest_pharmacy_m": 882,
            },
            "listing_research_meta": {"strategy": "provider_html_plus_geo"},
        },
    )
    captured: dict[str, object] = {}

    def _fake_execute_task_artifact(request):  # type: ignore[no-untyped-def]
        captured["request"] = request
        return Artifact(
            artifact_id="artifact-generic-property-tour",
            kind="property_tour_packet",
            content="Property tour created.",
            execution_session_id="session-generic-property-tour",
            principal_id=principal_id,
            structured_output_json={
                "public_url": "https://myexternalbrain.com/tours/generic-fit-1",
                "crezlo_public_url": "https://vendor.example.com/tours/generic-fit-1",
            },
        )

    client.app.state.container.orchestrator.execute_task_artifact = _fake_execute_task_artifact

    result = service.create_generic_property_tour(
        principal_id=principal_id,
        property_url=property_url,
        source_ref="gmail-thread:elisabeth:g-1",
        auto_deliver=False,
        actor="test",
    )

    assert result["status"] == "created"
    assert result["tour_url"] == "https://myexternalbrain.com/tours/generic-fit-1"
    request = captured["request"]
    assert request.input_json["property_url"] == property_url
    assert request.input_json["media_urls_json"] == ["https://cdn.example.com/generic/photo.jpg"]
    assert request.input_json["floorplan_urls_json"] == ["https://cdn.example.com/generic/floorplan.jpg"]
    assert request.input_json["source_virtual_tour_url"] == "https://360.example.test/generic-fit-1"
    assert request.input_json["runtime_inputs_json"]["source"] == "www.immobilienscout24.at"
    assert request.input_json["property_facts_json"]["street_address"] == "Hameaustraße 34"
    assert request.input_json["property_facts_json"]["nearest_supermarket_m"] == 951
    assert request.input_json["property_facts_json"]["nearest_pharmacy_m"] == 882
    assert request.input_json["property_facts_json"]["listing_research_snapshot"]["street_address"] == "Hameaustraße 34"
    assert request.input_json["property_facts_json"]["listing_research_meta"]["strategy"] == "provider_html_plus_geo"


def test_generic_property_tour_blocks_without_real_360_source(monkeypatch, tmp_path: Path) -> None:
    principal_id = "cf-email:tibor.girschele@gmail.com"
    monkeypatch.setenv("EA_PUBLIC_TOUR_DIR", str(tmp_path))
    monkeypatch.setenv("EA_PUBLIC_TOUR_BASE_URL", "https://myexternalbrain.com/tours")
    client = build_product_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Fallback Property Tour Office")
    service = ProductService(client.app.state.container)
    property_url = "https://www.immmo.at/detail/1547878487?c=3&utm_source=suchagent&utm_medium=email"

    monkeypatch.setattr(ProductService, "_resolve_browseract_property_tour_binding_id", lambda self, **kwargs: "")
    monkeypatch.setattr(
        product_service,
        "_property_scout_page_preview",
        lambda url: {
            "listing_id": "1547878487",
            "title": "Moderne 2 Zimmer Wohnung nahe Millennium City",
            "summary": "Loggia, Wien, Nachmietersuche",
            "property_facts_json": {"district": "Brigittenau", "has_360": False, "has_floorplan": False},
            "media_urls_json": [],
            "floorplan_urls_json": [],
        },
    )

    def _unexpected_execute_task_artifact(request):  # type: ignore[no-untyped-def]
        raise AssertionError("fallback should not require BrowserAct or Crezlo media")

    client.app.state.container.orchestrator.execute_task_artifact = _unexpected_execute_task_artifact

    result = service.create_generic_property_tour(
        principal_id=principal_id,
        property_url=property_url,
        source_ref="gmail-thread:elisabeth:g-no-media",
        auto_deliver=False,
        actor="test",
    )

    assert result["status"] == "blocked"
    assert result["blocked_reason"] == "listing_360_media_missing"
    assert result["tour_media_mode"] == "flat_images"
    assert result["tour_url"] == ""
    assert not any(tmp_path.iterdir())


def test_property_scout_page_preview_extracts_live_360_and_listing_images(monkeypatch) -> None:
    listing_url = "https://www.kalandra.at/objekt/14997053"
    monkeypatch.setattr(
        product_service,
        "_property_scout_fetch_html",
        lambda url, *, timeout_seconds=60.0: """
            <html>
              <head><title>360° TOUR // Test Apartment</title></head>
              <body>
                <img src="https://storage.justimmo.at/thumb/photo-1.jpg">
                <a href="https://360.kalandra.at/view/portal/id/VZ8P1">360 Tour</a>
                <iframe src="https://360.kalandra.at/view/portal/id/VZ8P1"></iframe>
              </body>
            </html>
        """,
    )

    preview = product_service._property_scout_page_preview(listing_url)

    assert preview["title"] == "360° TOUR // Test Apartment"
    assert preview["source_virtual_tour_url"] == "https://360.kalandra.at/view/portal/id/VZ8P1"
    assert preview["property_facts_json"]["has_360"] is True
    assert preview["property_facts_json"]["panorama_source"] == "360.kalandra.at"
    assert preview["media_urls_json"] == ("https://storage.justimmo.at/thumb/photo-1.jpg",)


def test_property_scout_page_preview_falls_back_to_fast_html_for_willhaben_when_packet_loader_times_out(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    listing_url = "https://www.willhaben.at/iad/immobilien/d/mietwohnungen/wien/test-1234567890/"
    monkeypatch.setattr(
        product_service,
        "_load_willhaben_property_packet",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("willhaben_property_packet_timeout")),
    )
    monkeypatch.setattr(
        product_service,
        "_property_scout_fetch_html",
        lambda url, *, timeout_seconds=60.0: """
            <html>
              <head>
                <title>Fallback Listing</title>
                <meta property=\"og:title\" content=\"Fallback Listing Title\">
                <meta property=\"og:description\" content=\"Fallback Listing Summary\">
              </head>
              <body><img src=\"https://images.example/listing.jpg\"></body>
            </html>
        """,
    )

    preview = product_service._property_scout_page_preview(listing_url)

    assert preview["listing_id"] == listing_url
    assert preview["title"] == "Fallback Listing Title"
    assert preview["summary"] == "Fallback Listing Summary"
    assert preview["media_urls_json"] == ("https://images.example/listing.jpg",)


def test_property_scout_page_preview_extracts_zvg_auction_facts(monkeypatch: pytest.MonkeyPatch) -> None:
    listing_url = "https://www.zvg-portal.de/index.php?button=showzvg&zvg_id=123&land_abk=be"
    monkeypatch.setattr(
        product_service,
        "_property_scout_fetch_html",
        lambda url, *, timeout_seconds=60.0: """
            <html>
              <head><title>Zwangsversteigerung Eigentumswohnung</title></head>
              <body>
                <table>
                  <tr><th>Amtsgericht</th><td>Amtsgericht Berlin-Mitte</td></tr>
                  <tr><th>Aktenzeichen</th><td>36 K 123/25</td></tr>
                  <tr><th>Verkehrswert</th><td>325.000,00 EUR</td></tr>
                  <tr><th>Geringstes Gebot</th><td>220.000,00 EUR</td></tr>
                  <tr><th>Termin</th><td>14.10.2026 09:00 Uhr</td></tr>
                  <tr><th>Lage</th><td>Musterstraße 14, 10115 Berlin</td></tr>
                  <tr><th>Nutzung</th><td>vermietet</td></tr>
                  <tr><th>Wohnfläche</th><td>82,5 m²</td></tr>
                </table>
              </body>
            </html>
        """,
    )

    preview = product_service._property_scout_page_preview(listing_url)

    facts = dict(preview["property_facts_json"])
    assert facts["distressed_sale"] is True
    assert facts["provider_channel"] == "zvg_de"
    assert facts["auction_reference"] == "123"
    assert facts["court"] == "Amtsgericht Berlin-Mitte"
    assert facts["court_file_reference"] == "36 K 123/25"
    assert facts["valuation_eur"] == 325000.0
    assert facts["reserve_price_eur"] == 220000.0
    assert facts["auction_date"] == "14.10.2026 09:00"
    assert facts["street_address"] == "Musterstraße 14"
    assert facts["postal_name"] == "10115 Berlin"
    assert facts["occupancy_status"] == "vermietet"
    assert facts["area_sqm"] == 82.5
    assert "Amtsgericht Berlin-Mitte" in preview["summary"]


def test_property_scout_page_preview_extracts_justiz_edikte_facts(monkeypatch: pytest.MonkeyPatch) -> None:
    listing_url = "https://edikte.justiz.gv.at/edikte/ex/exedi3.nsf/0/ABCDEF123456?OpenDocument&id=987"
    monkeypatch.setattr(
        product_service,
        "_property_scout_fetch_html",
        lambda url, *, timeout_seconds=60.0: """
            <html>
              <head><title>Edikt: Eigentumswohnung Wien</title></head>
              <body>
                <dl>
                  <dt>Bezirksgericht</dt><dd>Bezirksgericht Döbling</dd>
                  <dt>Geschäftszahl</dt><dd>15 E 44/26p</dd>
                  <dt>Schätzwert</dt><dd>EUR 410.000,00</dd>
                  <dt>Geringstes Gebot</dt><dd>EUR 205.000,00</dd>
                  <dt>Versteigerungstermin</dt><dd>21.11.2026 10:30</dd>
                  <dt>Liegenschaft</dt><dd>Hameaustraße 34, 1190 Wien</dd>
                  <dt>Nutzung</dt><dd>bewohnt</dd>
                  <dt>Wohnfläche</dt><dd>97,4 m²</dd>
                </dl>
              </body>
            </html>
        """,
    )

    preview = product_service._property_scout_page_preview(listing_url)

    facts = dict(preview["property_facts_json"])
    assert facts["distressed_sale"] is True
    assert facts["provider_channel"] == "justiz_edikte_at"
    assert facts["auction_reference"] == "987"
    assert facts["court"] == "Bezirksgericht Döbling"
    assert facts["court_file_reference"] == "15 E 44/26p"
    assert facts["valuation_eur"] == 410000.0
    assert facts["reserve_price_eur"] == 205000.0
    assert facts["auction_date"] == "21.11.2026 10:30"
    assert facts["street_address"] == "Hameaustraße 34"
    assert facts["postal_name"] == "1190 Wien"
    assert facts["occupancy_status"] == "bewohnt"
    assert facts["area_sqm"] == 97.4
    assert "Bezirksgericht Döbling" in preview["summary"]


def test_property_scout_page_preview_extracts_boe_subastas_facts(monkeypatch: pytest.MonkeyPatch) -> None:
    listing_url = "https://subastas.boe.es/subastas/detalleSubasta.php?idSub=SUB-JA-2026-11111"
    monkeypatch.setattr(
        product_service,
        "_property_scout_fetch_html",
        lambda url, *, timeout_seconds=60.0: """
            <html>
              <head><title>Subasta inmueble Madrid</title></head>
              <body>
                <table>
                  <tr><th>Autoridad gestora</th><td>Juzgado de Primera Instancia n.º 18 de Madrid</td></tr>
                  <tr><th>Valor de subasta</th><td>450.000,00 €</td></tr>
                  <tr><th>Importe del depósito</th><td>22.500,00 €</td></tr>
                  <tr><th>Cantidad reclamada</th><td>180.000,00 €</td></tr>
                  <tr><th>Fecha de conclusión</th><td>2026-12-01 18:00</td></tr>
                  <tr><th>Dirección</th><td>Calle de Alcalá 88, 28009 Madrid</td></tr>
                  <tr><th>Situación posesoria</th><td>ocupado por tercero</td></tr>
                  <tr><th>Superficie construida</th><td>112,0 m²</td></tr>
                </table>
              </body>
            </html>
        """,
    )

    preview = product_service._property_scout_page_preview(listing_url)

    facts = dict(preview["property_facts_json"])
    assert facts["distressed_sale"] is True
    assert facts["provider_channel"] == "boe_subastas_es"
    assert facts["auction_reference"] == "SUB-JA-2026-11111"
    assert facts["court"] == "Juzgado de Primera Instancia n.º 18 de Madrid"
    assert facts["valuation_eur"] == 450000.0
    assert facts["deposit_amount_eur"] == 22500.0
    assert facts["claimed_amount_eur"] == 180000.0
    assert facts["auction_date"] == "2026-12-01 18:00"
    assert facts["street_address"] == "Calle de Alcalá 88"
    assert facts["postal_name"] == "28009 Madrid"
    assert facts["occupancy_status"] == "ocupado por tercero"
    assert facts["area_sqm"] == 112.0
    assert "Juzgado de Primera Instancia" in preview["summary"]


def test_property_scout_page_preview_extracts_avoventes_facts(monkeypatch: pytest.MonkeyPatch) -> None:
    listing_url = "https://www.avoventes.fr/vente-immobiliere/appartement-paris-75015"
    monkeypatch.setattr(
        product_service,
        "_property_scout_fetch_html",
        lambda url, *, timeout_seconds=60.0: """
            <html>
              <head><title>Vente judiciaire appartement Paris</title></head>
              <body>
                <table>
                  <tr><th>Tribunal judiciaire</th><td>Tribunal judiciaire de Paris</td></tr>
                  <tr><th>Référence</th><td>RG 24/12345</td></tr>
                  <tr><th>Mise à prix</th><td>310 000 €</td></tr>
                  <tr><th>Consignation</th><td>31 000 €</td></tr>
                  <tr><th>Date d'audience</th><td>2026-09-18 14:00</td></tr>
                  <tr><th>Adresse</th><td>12 Rue Lecourbe, 75015 Paris</td></tr>
                  <tr><th>Occupation</th><td>occupé</td></tr>
                  <tr><th>Surface</th><td>58,5 m²</td></tr>
                </table>
              </body>
            </html>
        """,
    )

    preview = product_service._property_scout_page_preview(listing_url)

    facts = dict(preview["property_facts_json"])
    assert facts["provider_channel"] == "avoventes_fr"
    assert facts["court"] == "Tribunal judiciaire de Paris"
    assert facts["court_file_reference"] == "RG 24/12345"
    assert facts["valuation_eur"] == 310000.0
    assert facts["deposit_amount_eur"] == 31000.0
    assert facts["auction_date"] == "2026-09-18 14:00"
    assert facts["street_address"] == "12 Rue Lecourbe"
    assert facts["postal_name"] == "75015 Paris"
    assert facts["occupancy_status"] == "occupé"
    assert facts["area_sqm"] == 58.5


def test_property_scout_page_preview_extracts_aste_giudiziarie_facts(monkeypatch: pytest.MonkeyPatch) -> None:
    listing_url = "https://www.astegiudiziarie.it/beni/immobili/asta-roma-123456"
    monkeypatch.setattr(
        product_service,
        "_property_scout_fetch_html",
        lambda url, *, timeout_seconds=60.0: """
            <html>
              <head><title>Asta giudiziaria Roma</title></head>
              <body>
                <dl>
                  <dt>Tribunale</dt><dd>Tribunale di Roma</dd>
                  <dt>Numero procedura</dt><dd>RGE 456/2025</dd>
                  <dt>Prezzo base</dt><dd>€ 275.000,00</dd>
                  <dt>Offerta minima</dt><dd>€ 206.250,00</dd>
                  <dt>Data asta</dt><dd>21.10.2026 11:00</dd>
                  <dt>Indirizzo</dt><dd>Via Nomentana 145, 00161 Roma</dd>
                  <dt>Occupazione</dt><dd>occupato</dd>
                  <dt>Superficie</dt><dd>89,0 m²</dd>
                </dl>
              </body>
            </html>
        """,
    )

    preview = product_service._property_scout_page_preview(listing_url)

    facts = dict(preview["property_facts_json"])
    assert facts["provider_channel"] == "aste_giudiziarie_it"
    assert facts["court"] == "Tribunale di Roma"
    assert facts["court_file_reference"] == "RGE 456/2025"
    assert facts["valuation_eur"] == 275000.0
    assert facts["reserve_price_eur"] == 206250.0
    assert facts["auction_date"] == "21.10.2026 11:00"
    assert facts["street_address"] == "Via Nomentana 145"
    assert facts["postal_name"] == "00161 Roma"
    assert facts["occupancy_status"] == "occupato"
    assert facts["area_sqm"] == 89.0


def test_property_scout_page_preview_extracts_citius_exec_facts(monkeypatch: pytest.MonkeyPatch) -> None:
    listing_url = "https://www.citius.mj.pt/portal/consultas/consultasvenda.aspx?processo=111222333"
    monkeypatch.setattr(
        product_service,
        "_property_scout_fetch_html",
        lambda url, *, timeout_seconds=60.0: """
            <html>
              <head><title>Venda executiva Lisboa</title></head>
              <body>
                <table>
                  <tr><th>Tribunal</th><td>Tribunal Judicial da Comarca de Lisboa</td></tr>
                  <tr><th>Processo</th><td>111222333</td></tr>
                  <tr><th>Valor base</th><td>198 000,00 EUR</td></tr>
                  <tr><th>Valor mínimo</th><td>168 300,00 EUR</td></tr>
                  <tr><th>Data de venda</th><td>2026-11-03 15:30</td></tr>
                  <tr><th>Morada</th><td>Rua do Ouro 22, 1100-061 Lisboa</td></tr>
                  <tr><th>Ocupação</th><td>ocupado</td></tr>
                  <tr><th>Área</th><td>74,2 m²</td></tr>
                </table>
              </body>
            </html>
        """,
    )

    preview = product_service._property_scout_page_preview(listing_url)

    facts = dict(preview["property_facts_json"])
    assert facts["provider_channel"] == "citius_exec_pt"
    assert facts["auction_reference"] == "111222333"
    assert facts["court"] == "Tribunal Judicial da Comarca de Lisboa"
    assert facts["court_file_reference"] == "111222333"
    assert facts["valuation_eur"] == 198000.0
    assert facts["reserve_price_eur"] == 168300.0
    assert facts["auction_date"] == "2026-11-03 15:30"
    assert facts["street_address"] == "Rua do Ouro 22"
    assert facts["postal_name"] == "1100-061 Lisboa"
    assert facts["occupancy_status"] == "ocupado"
    assert facts["area_sqm"] == 74.2


def test_property_scout_page_preview_extracts_biddit_facts(monkeypatch: pytest.MonkeyPatch) -> None:
    listing_url = "https://www.biddit.be/nl/catalog/detail/987654"
    monkeypatch.setattr(
        product_service,
        "_property_scout_fetch_html",
        lambda url, *, timeout_seconds=60.0: """
            <html>
              <head><title>Biddit appartement Brussel</title></head>
              <body>
                <table>
                  <tr><th>Notaris</th><td>Notaris Peeters &amp; Co</td></tr>
                  <tr><th>Dossier</th><td>BID-2026-7788</td></tr>
                  <tr><th>Instelprijs</th><td>245 000 EUR</td></tr>
                  <tr><th>Waarborg</th><td>24 500 EUR</td></tr>
                  <tr><th>Sluiting biedingen</th><td>2026-10-15 14:00</td></tr>
                  <tr><th>Adres</th><td>Wetstraat 120, 1000 Brussel</td></tr>
                  <tr><th>Bewoning</th><td>verhuurd</td></tr>
                  <tr><th>Bewoonbare oppervlakte</th><td>76,0 m²</td></tr>
                </table>
              </body>
            </html>
        """,
    )

    preview = product_service._property_scout_page_preview(listing_url)
    facts = dict(preview["property_facts_json"])
    assert facts["provider_channel"] == "biddit_be"
    assert facts["court"] == "Notaris Peeters & Co"
    assert facts["court_file_reference"] == "BID-2026-7788"
    assert facts["valuation_eur"] == 245000.0
    assert facts["deposit_amount_eur"] == 24500.0
    assert facts["auction_date"] == "2026-10-15 14:00"
    assert facts["street_address"] == "Wetstraat 120"
    assert facts["postal_name"] == "1000 Brussel"
    assert facts["occupancy_status"] == "verhuurd"
    assert facts["area_sqm"] == 76.0


def test_property_scout_page_preview_extracts_veilingdeurwaarder_facts(monkeypatch: pytest.MonkeyPatch) -> None:
    listing_url = "https://www.veilingdeurwaarder.nl/object/amsterdam-334455"
    monkeypatch.setattr(
        product_service,
        "_property_scout_fetch_html",
        lambda url, *, timeout_seconds=60.0: """
            <html>
              <head><title>Executieveiling Amsterdam</title></head>
              <body>
                <dl>
                  <dt>Notaris</dt><dd>Van Dijk Notarissen</dd>
                  <dt>Dossiernummer</dt><dd>VD-2026-14</dd>
                  <dt>Inzetprijs</dt><dd>€ 395.000,00</dd>
                  <dt>Waarborgsom</dt><dd>€ 39.500,00</dd>
                  <dt>Veilingdatum</dt><dd>2026-11-21 10:00</dd>
                  <dt>Adres</dt><dd>Keizersgracht 18, 1012 LG Amsterdam</dd>
                  <dt>Bewoning</dt><dd>bewoond</dd>
                  <dt>Woonoppervlakte</dt><dd>94,0 m²</dd>
                </dl>
              </body>
            </html>
        """,
    )

    preview = product_service._property_scout_page_preview(listing_url)
    facts = dict(preview["property_facts_json"])
    assert facts["provider_channel"] == "veilingdeurwaarder_nl"
    assert facts["court"] == "Van Dijk Notarissen"
    assert facts["court_file_reference"] == "VD-2026-14"
    assert facts["valuation_eur"] == 395000.0
    assert facts["deposit_amount_eur"] == 39500.0
    assert facts["auction_date"] == "2026-11-21 10:00"
    assert facts["street_address"] == "Keizersgracht 18"
    assert facts["postal_name"] == "1012 LG Amsterdam"
    assert facts["occupancy_status"] == "bewoond"
    assert facts["area_sqm"] == 94.0


def test_property_scout_page_preview_extracts_komornik_facts(monkeypatch: pytest.MonkeyPatch) -> None:
    listing_url = "https://elicytacje.komornik.pl/items/auction?id=24680"
    monkeypatch.setattr(
        product_service,
        "_property_scout_fetch_html",
        lambda url, *, timeout_seconds=60.0: """
            <html>
              <head><title>E-licytacja mieszkania Warszawa</title></head>
              <body>
                <table>
                  <tr><th>Komornik</th><td>Komornik Sądowy Anna Kowalska</td></tr>
                  <tr><th>Sygnatura</th><td>KM 1234/25</td></tr>
                  <tr><th>Cena wywoławcza</th><td>520 000,00 EUR</td></tr>
                  <tr><th>Rękojmia</th><td>52 000,00 EUR</td></tr>
                  <tr><th>Termin licytacji</th><td>2026-12-09 09:30</td></tr>
                  <tr><th>Adres</th><td>Ulica Puławska 88, 00-950 Warszawa</td></tr>
                  <tr><th>Stan zamieszkania</th><td>zamieszkany</td></tr>
                  <tr><th>Powierzchnia</th><td>67,8 m²</td></tr>
                </table>
              </body>
            </html>
        """,
    )

    preview = product_service._property_scout_page_preview(listing_url)
    facts = dict(preview["property_facts_json"])
    assert facts["provider_channel"] == "komornik_elicytacje_pl"
    assert facts["auction_reference"] == "24680"
    assert facts["court"] == "Komornik Sądowy Anna Kowalska"
    assert facts["court_file_reference"] == "KM 1234/25"
    assert facts["valuation_eur"] == 520000.0
    assert facts["deposit_amount_eur"] == 52000.0
    assert facts["auction_date"] == "2026-12-09 09:30"
    assert facts["street_address"] == "Ulica Puławska 88"
    assert facts["postal_name"] == "00-950 Warszawa"
    assert facts["occupancy_status"] == "zamieszkany"
    assert facts["area_sqm"] == 67.8


def test_property_scout_page_preview_extracts_kronofogden_facts(monkeypatch: pytest.MonkeyPatch) -> None:
    listing_url = "https://auktionstorget.kronofogden.se/auktionstorget/object/stockholm-7788"
    monkeypatch.setattr(
        product_service,
        "_property_scout_fetch_html",
        lambda url, *, timeout_seconds=60.0: """
            <html>
              <head><title>Auktion bostadsrätt Stockholm</title></head>
              <body>
                <dl>
                  <dt>Kronofogden</dt><dd>Kronofogden Stockholm</dd>
                  <dt>Målnummer</dt><dd>KFM 2026-7788</dd>
                  <dt>Utropspris</dt><dd>3 250 000 EUR</dd>
                  <dt>Handpenning</dt><dd>325 000 EUR</dd>
                  <dt>Auktionstid</dt><dd>2026-10-28 13:00</dd>
                  <dt>Adress</dt><dd>Storgatan 11, 114 34 Stockholm</dd>
                  <dt>Uthyrd</dt><dd>uthyrd</dd>
                  <dt>Boarea</dt><dd>81,0 m²</dd>
                </dl>
              </body>
            </html>
        """,
    )

    preview = product_service._property_scout_page_preview(listing_url)
    facts = dict(preview["property_facts_json"])
    assert facts["provider_channel"] == "kronofogden_auktionstorget_se"
    assert facts["court"] == "Kronofogden Stockholm"
    assert facts["court_file_reference"] == "KFM 2026-7788"
    assert facts["valuation_eur"] == 3250000.0
    assert facts["deposit_amount_eur"] == 325000.0
    assert facts["auction_date"] == "2026-10-28 13:00"
    assert facts["street_address"] == "Storgatan 11"
    assert facts["postal_name"] == "114 34 Stockholm"
    assert facts["occupancy_status"] == "uthyrd"
    assert facts["area_sqm"] == 81.0


def test_generic_property_tour_publishes_pure_360_bundle_when_crezlo_is_unavailable(monkeypatch, tmp_path: Path) -> None:
    principal_id = "cf-email:tibor.girschele@gmail.com"
    monkeypatch.setenv("EA_PUBLIC_TOUR_DIR", str(tmp_path))
    monkeypatch.setenv("EA_PUBLIC_TOUR_BASE_URL", "https://myexternalbrain.com/tours")
    client = build_product_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Live 360 Property Tour Office")
    service = ProductService(client.app.state.container)
    property_url = "https://www.kalandra.at/objekt/14997053"

    monkeypatch.setattr(ProductService, "_resolve_browseract_property_tour_binding_id", lambda self, **kwargs: "browseract-binding-1")
    monkeypatch.setattr(
        product_service,
        "_property_scout_page_preview",
        lambda url: {
            "listing_id": "14997053",
            "title": "360 Tour Test Apartment",
            "summary": "Live 360 tour",
            "property_facts_json": {
                "has_360": True,
                "source_virtual_tour_url": "https://360.kalandra.at/view/portal/id/VZ8P1",
                "panorama_source": "360.kalandra.at",
            },
            "media_urls_json": ["https://storage.justimmo.at/thumb/photo-1.jpg"],
            "floorplan_urls_json": [],
            "source_virtual_tour_url": "https://360.kalandra.at/view/portal/id/VZ8P1",
            "panorama_source": "360.kalandra.at",
        },
    )
    monkeypatch.setattr(
        product_service,
        "_merge_property_facts_with_source_research",
        lambda *, property_url, property_facts, image_urls=(): {
            **dict(property_facts),
            "street_address": "Hameaustraße 34",
            "address_lines": ["Hameaustraße 34", "1190 Wien"],
            "exact_address": "34, Hameaustraße, Katastralgemeinde Salmannsdorf, Döbling, Wien, 1190, Österreich",
            "nearest_supermarket_m": 951,
            "nearest_pharmacy_m": 882,
            "nearest_playground_m": 532,
            "nearest_subway_m": 4752,
            "listing_research_snapshot": {
                "street_address": "Hameaustraße 34",
                "address_lines": ["Hameaustraße 34", "1190 Wien"],
                "nearest_supermarket_m": 951,
                "nearest_pharmacy_m": 882,
                "nearest_playground_m": 532,
                "nearest_subway_m": 4752,
            },
            "listing_research_meta": {"strategy": "provider_html_plus_geo"},
        },
    )

    def _crezlo_unavailable(request):  # type: ignore[no-untyped-def]
        raise RuntimeError("crezlo_login_required")

    client.app.state.container.orchestrator.execute_task_artifact = _crezlo_unavailable
    monkeypatch.setattr(
        product_service,
        "_feelestate_json_rpc",
        lambda method, params: {
            ("getLocationWithAuthentication", None): {
                "tour": {"floors": [{"id": 85470}], "name": "Tour"},
            },
            ("getAllFloorLocations", 85470): {
                "locations": [{"id": 847551, "name": "Living room"}],
            },
            ("getLocationWithAuthentication", 847551): {
                "location": {"id": 847551, "name": "Living room", "gotoYaw": 0, "gotoPitch": 0},
            },
        }[(method, params[2] if method == "getLocationWithAuthentication" else params[0])],
    )
    monkeypatch.setattr(
        product_service,
        "_download_public_tour_asset",
        lambda url, target: (target.parent.mkdir(parents=True, exist_ok=True), target.write_bytes(b"jpg")),
    )

    result = service.create_generic_property_tour(
        principal_id=principal_id,
        property_url=property_url,
        source_ref="gmail-thread:elisabeth:kalandra-live-360",
        auto_deliver=False,
        actor="test",
    )

    assert result["status"] == "created"
    assert result["creation_mode"] == "pure_hosted_360"
    assert result["source_virtual_tour_url"] == ""
    assert str(result["tour_url"]).startswith("https://myexternalbrain.com/tours/")
    assert not str(result["tour_url"]).endswith("#live-360")
    slug = str(result["tour_url"]).split("/tours/", 1)[1]
    payload = json.loads((tmp_path / slug / "tour.json").read_text(encoding="utf-8"))
    assert payload["scene_strategy"] == "pure_360_cube"
    assert payload["source_virtual_tour_url"] == ""
    assert payload["source_virtual_tour_origin"] == "https://360.kalandra.at/view/portal/id/VZ8P1"
    assert payload["principal_id"] == principal_id
    assert payload["source_ref"] == "gmail-thread:elisabeth:kalandra-live-360"
    assert payload["facts"]["street_address"] == "Hameaustraße 34"
    assert payload["facts"]["address_lines"] == ["Hameaustraße 34", "1190 Wien"]
    assert payload["facts"]["nearest_supermarket_m"] == 951
    assert payload["facts"]["nearest_pharmacy_m"] == 882
    assert payload["facts"]["nearest_playground_m"] == 532
    assert payload["facts"]["nearest_subway_m"] == 4752
    assert payload["facts"]["listing_research_snapshot"]["street_address"] == "Hameaustraße 34"
    assert payload["facts"]["listing_research_meta"]["strategy"] == "provider_html_plus_geo"
    assert payload["scenes"][0]["role"] == "pure_360"
    assert payload["scenes"][0]["cube_faces"]["f"] == "panorama/847551/tablet_f.jpg"


def test_property_source_research_snapshot_uses_image_ocr_when_listing_has_no_map(monkeypatch) -> None:
    listing_url = "https://www.immobilienscout24.at/expose/ocr-address"
    product_service._property_source_research_snapshot.cache_clear()
    product_service._property_research_forward_geocode.cache_clear()
    product_service._property_research_reverse_geocode.cache_clear()
    product_service._property_research_nearby_pois.cache_clear()
    monkeypatch.setattr(product_service, "_property_scout_fetch_html", lambda url: "<html><body>No map here</body></html>")
    monkeypatch.setattr(
        product_service,
        "_property_image_ocr_address_hint",
        lambda image_urls, *, source_text="", property_url="": {
            "street_address": "Beispielgasse 12",
            "address_lines": ["Beispielgasse 12", "1180 Wien"],
            "exact_address": "Beispielgasse 12, 1180 Wien, Österreich",
            "map_lat": 48.2345,
            "map_lng": 16.3456,
            "nearest_supermarket_m": 240,
            "nearest_pharmacy_m": 190,
        },
    )

    findings = product_service._property_source_research_snapshot(
        listing_url,
        ("https://cdn.example.com/listing/1.jpg", "https://cdn.example.com/listing/2.jpg"),
    )

    assert findings["street_address"] == "Beispielgasse 12"
    assert findings["address_lines"] == ["Beispielgasse 12", "1180 Wien"]
    assert findings["nearest_supermarket_m"] == 240
    assert findings["nearest_pharmacy_m"] == 190


def test_property_image_ocr_address_hint_rejects_geocode_when_postcode_conflicts(monkeypatch) -> None:
    class _FakeResponse:
        def __init__(self) -> None:
            self.headers = {"Content-Type": "image/jpeg", "Content-Length": "3"}

        def read(self) -> bytes:
            return b"img"

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb) -> None:
            return None

    monkeypatch.setattr(product_service.shutil, "which", lambda _name: "/usr/bin/tesseract")
    monkeypatch.setattr(product_service.urllib.request, "urlopen", lambda request, timeout=0: _FakeResponse())
    monkeypatch.setattr(product_service, "Image", type("FakeImageModule", (), {"open": staticmethod(lambda _stream: type("FakeImage", (), {"convert": lambda self, _mode: self})())}))
    monkeypatch.setattr(product_service, "pytesseract", type("FakeTesseract", (), {"image_to_string": staticmethod(lambda *_args, **_kwargs: "Beispielgasse 12")}))
    monkeypatch.setattr(
        product_service,
        "_property_research_forward_geocode",
        lambda query: {"lat": "48.2", "lon": "16.3", "display_name": "Beispielgasse 12, 1180 Wien, Österreich"},
    )
    monkeypatch.setattr(
        product_service,
        "_property_research_reverse_geocode",
        lambda lat, lon: {"address": {"road": "Beispielgasse", "house_number": "12", "postcode": "1180", "city": "Wien"}},
    )
    monkeypatch.setattr(product_service, "_property_research_nearby_pois", lambda lat, lon: {"nearest_supermarket_m": 240})

    findings = product_service._property_image_ocr_address_hint(
        ("https://cdn.example.com/listing/1.jpg",),
        source_text="Wohnung in 1190 Wien",
        property_url="https://www.immobilienscout24.at/expose/ocr-address",
    )

    assert findings == {}


def test_merge_property_facts_with_source_research_replaces_weak_values(monkeypatch) -> None:
    monkeypatch.setattr(
        product_service,
        "_property_source_research_snapshot",
        lambda property_url, image_urls=(): {
            "street_address": "Hameaustraße 34",
            "address_lines": ["Hameaustraße 34", "1190 Wien"],
            "nearest_supermarket_m": 951,
        },
    )

    merged = product_service._merge_property_facts_with_source_research(
        property_url="https://www.kalandra.at/objekt/14997053",
        property_facts={
            "street_address": "",
            "address_lines": ["", ""],
            "nearest_supermarket_m": 0,
        },
        image_urls=(),
    )

    assert merged["street_address"] == "Hameaustraße 34"
    assert merged["address_lines"] == ["Hameaustraße 34", "1190 Wien"]
    assert merged["nearest_supermarket_m"] == 951
    assert merged["listing_research_snapshot"]["street_address"] == "Hameaustraße 34"
    assert merged["listing_research_meta"]["strategy"] == "provider_html_plus_geo"


def test_preference_profile_endpoints_and_willhaben_assessment_flow() -> None:
    principal_id = "pref-product-api"
    client = build_product_client(principal_id=principal_id)

    created = client.post(
        "/app/api/people/self/preference-profile",
        json={
            "display_name": "Tibor",
            "consent_mode": "behavioral_learning",
            "learning_enabled": True,
            "high_stakes_domains_enabled": True,
        },
    )
    assert created.status_code == 200
    assert created.json()["display_name"] == "Tibor"
    assert created.json()["learning_enabled"] is True

    node = client.post(
        "/app/api/people/self/preference-profile/nodes",
        json={
            "domain": "willhaben",
            "category": "constraint",
            "key": "require_floorplan",
            "value_json": True,
            "confidence": 1.0,
        },
    )
    assert node.status_code == 200
    assert node.json()["key"] == "require_floorplan"

    evidence = client.post(
        "/app/api/people/self/preference-profile/evidence",
        json={
            "domain": "willhaben",
            "event_type": "listing_shortlisted",
            "object_type": "listing",
            "object_id": "listing-1",
            "interpreted_signal_json": {
                "preference_hints": [
                    {
                        "domain": "willhaben",
                        "category": "soft_preference",
                        "key": "preferred_districts",
                        "value_json": ["Waehring"],
                        "strength": "medium",
                        "merge_mode": "append_unique",
                    }
                ]
            },
        },
    )
    assert evidence.status_code == 200
    assert evidence.json()["applied_nodes"][0]["key"] == "preferred_districts"

    assessment = client.post(
        "/app/api/people/self/preference-profile/assessments",
        json={
            "domain": "willhaben",
            "object_type": "listing",
            "object_id": "listing-1",
            "object_payload": {
                "postal_name": "Waehring",
                "total_rent_eur": 2200.0,
                "rooms": 4.0,
                "area_sqm": 106.0,
                "heating": "Gasheizung",
                "floorplan_count": 1,
                "tour_media_mode": "panorama_360",
            },
        },
    )
    assert assessment.status_code == 200
    assert assessment.json()["domain"] == "willhaben"
    assert assessment.json()["recommendation"] in {"mention", "shortlist"}

    suggestions = client.post(
        "/app/api/people/self/preference-profile/property-feedback/suggestions",
        json={
            "property_facts": {
                "postal_name": "Waehring",
                "district": "Waehring",
                "total_rent_eur": 2200.0,
                "area_sqm": 106.0,
                "heating_type": "Gasheizung",
                "has_floorplan": True,
                "lift": False,
                "nearest_subway_m": 920.0,
                "nearest_playground_m": 180.0,
            },
            "assessment": assessment.json(),
        },
    )
    assert suggestions.status_code == 200
    suggestion_body = suggestions.json()
    assert any(item["key"] == "gas_heating" for item in suggestion_body["negative"])
    assert any(item["key"] == "floorplan_good" for item in suggestion_body["positive"])

    feedback = client.post(
        "/app/api/people/self/preference-profile/property-feedback",
        json={
            "property_slug": "waehring-flat-1",
            "property_url": "https://www.willhaben.at/iad/immobilien/d/mietwohnungen/wien/wien-1180-waehring/waehring-flat-1",
            "property_title": "Waehring Flat 1",
            "property_facts": {
                "postal_name": "Waehring",
                "district": "Waehring",
                "total_rent_eur": 2200.0,
                "area_sqm": 106.0,
                "heating_type": "Gasheizung",
                "has_floorplan": True,
                "lift": False,
                "nearest_subway_m": 920.0,
                "nearest_playground_m": 180.0,
            },
            "reaction": "dislike",
            "reason_keys": ["gas_heating", "no_lift"],
            "note": "Gas and stairs are both wrong.",
        },
    )
    assert feedback.status_code == 200
    feedback_body = feedback.json()
    assert feedback_body["status"] == "recorded"
    assert any(item["key"] == "avoid_heating_types" for item in feedback_body["evidence"]["applied_nodes"])
    assert any(item["key"] == "prefer_lift" for item in feedback_body["evidence"]["applied_nodes"])
    assert feedback_body["updated_assessment"]["domain"] == "willhaben"

    learning = client.get("/app/api/people/self/preference-profile/learning-summary")
    assert learning.status_code == 200
    learning_body = learning.json()
    assert "Avoid heating: Gasheizung" in learning_body["dislikes"]
    assert any(row["reaction"] == "dislike" for row in learning_body["recent_feedback"])

    bundle = client.get("/app/api/people/self/preference-profile")
    assert bundle.status_code == 200
    body = bundle.json()
    assert body["profile"]["display_name"] == "Tibor"
    assert any(item["key"] == "preferred_districts" for item in body["preference_nodes"])
    assert body["recent_decision_assessments"][0]["domain"] == "willhaben"

    partial = client.post(
        "/app/api/people/self/preference-profile",
        json={
            "display_name": "Updated Tibor",
        },
    )
    assert partial.status_code == 200
    assert partial.json()["display_name"] == "Updated Tibor"
    assert partial.json()["learning_enabled"] is True
    assert partial.json()["high_stakes_domains_enabled"] is True


def test_willhaben_property_tour_route_uses_personal_fit_assessment_when_profile_exists(monkeypatch) -> None:
    from app.domain.models import Artifact
    from app.services.registration_email import RegistrationEmailReceipt

    monkeypatch.setenv("EMAILIT_API_KEY", "test-emailit-key")
    monkeypatch.setenv("EA_WILLHABEN_PROPERTY_TOUR_REQUIRE_360", "0")
    principal_id = "cf-email:tibor.girschele@gmail.com"
    client = build_product_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Executive Office")
    client.post(
        "/app/api/people/self/preference-profile",
        json={
            "display_name": "Tibor",
            "consent_mode": "behavioral_learning",
            "learning_enabled": True,
        },
    )
    client.post(
        "/app/api/people/self/preference-profile/nodes",
        json={
            "domain": "willhaben",
            "category": "aversion",
            "key": "avoid_heating_types",
            "value_json": ["Gasheizung"],
            "confidence": 1.0,
        },
    )

    packet = {
        "property_url": "https://www.willhaben.at/iad/immobilien/d/mietwohnungen/wien/wien-1180-waehring/apartment-a-123",
        "listing_id": "listing-123",
        "listing_uuid": "listing-uuid-123",
        "title": "Bright Waehring apartment",
        "property_facts_json": {
            "postal_name": "Waehring",
            "area_label": "74 m²",
            "area_sqm": 74.0,
            "rooms_label": "3 rooms",
            "rooms": 3.0,
            "total_rent_eur": 1890.0,
            "heating": "Gasheizung",
            "floorplan_count": 1,
            "decision_summary": {
                "good_fit_reasons": ["A floor plan is available."],
                "bad_fit_reasons": [],
                "unknowns": ["Check noise in person."],
                "recommendation": "shortlist",
            },
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
        return RegistrationEmailReceipt(provider="emailit", message_id="property-tour-message-2", accepted_at="2026-05-02T00:00:00+00:00")

    monkeypatch.setattr(product_service, "send_property_tour_email", _fake_send_property_tour_email)

    def _fake_execute_task_artifact(request):  # type: ignore[no-untyped-def]
        return Artifact(
            artifact_id="artifact-property-tour-2",
            kind="property_tour_packet",
            content="Property tour created.",
            execution_session_id="session-property-tour-2",
            principal_id=principal_id,
            structured_output_json={
                "hosted_url": "https://myexternalbrain.com/tours/waehring-apartment-a",
                "public_url": "https://myexternalbrain.com/tours/waehring-apartment-a",
                "crezlo_public_url": "https://vendor.example.com/tours/waehring-apartment-a",
                "editor_url": "https://vendor.example.com/editor/waehring-apartment-a",
                "tour_id": "tour-456",
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
    assert body["personal_fit_assessment"]["assessment_id"]
    assert body["personal_fit_assessment"]["domain"] == "willhaben"
    assert any("Gasheizung" in entry for entry in body["personal_fit_assessment"]["mismatch_reasons_json"])
    assert observed_email["decision_summary_json"]["domain"] == "willhaben"


def test_willhaben_property_tour_records_video_followup_when_telegram_video_delivery_fails(monkeypatch, tmp_path) -> None:
    from app.domain.models import Artifact
    from app.services.registration_email import RegistrationEmailReceipt

    monkeypatch.setenv("EMAILIT_API_KEY", "test-emailit-key")
    monkeypatch.setenv("EA_WILLHABEN_PROPERTY_TOUR_REQUIRE_360", "0")
    monkeypatch.setenv("EA_PUBLIC_TOUR_DIR", str(tmp_path))
    principal_id = "cf-email:tibor.girschele@gmail.com"
    client = build_product_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Property Video Followup Office")

    packet = {
        "property_url": "https://www.willhaben.at/iad/immobilien/d/mietwohnungen/wien/wien-1180-waehring/video-fail-123",
        "listing_id": "listing-video-fail-123",
        "title": "Bright Waehring apartment",
        "property_facts_json": {
            "postal_name": "Waehring",
            "area_label": "74 m²",
            "rooms_label": "3 rooms",
            "total_rent_eur": 1890.0,
            "decision_summary": {"recommendation": "shortlist"},
        },
        "media_urls_json": ["https://cdn.example.com/apartment-a/photo-1.jpg"],
        "floorplan_urls_json": ["https://cdn.example.com/apartment-a/floorplan-1.jpg"],
        "tour_variants_json": [{"variant_key": "layout_first", "scene_strategy": "layout_first"}],
    }
    monkeypatch.setattr(product_service, "_load_willhaben_property_packet", lambda url: dict(packet))
    monkeypatch.setattr(
        product_service,
        "send_property_tour_email",
        lambda **kwargs: RegistrationEmailReceipt(provider="emailit", message_id="property-tour-message-3", accepted_at="2026-05-02T00:00:00+00:00"),
    )
    monkeypatch.setattr(
        product_service,
        "resolve_primary_telegram_binding",
        lambda tool_runtime, *, principal_id: SimpleNamespace(
            external_account_ref="1354554303",
            auth_metadata_json={"default_chat_ref": "1354554303"},
        ),
    )

    def _fake_execute_task_artifact(request):  # type: ignore[no-untyped-def]
        bundle_dir = tmp_path / "video-fail-123"
        bundle_dir.mkdir(parents=True, exist_ok=True)
        (bundle_dir / "tour.mp4").write_bytes(b"fake-video")
        (bundle_dir / "tour.json").write_text(
            '{"slug":"video-fail-123","video_relpath":"tour.mp4","scenes":[{"asset_relpath":"scene-01.jpg"}]}',
            encoding="utf-8",
        )
        (bundle_dir / "scene-01.jpg").write_bytes(b"scene")
        return Artifact(
            artifact_id="artifact-property-tour-video-fail",
            kind="property_tour_packet",
            content="Property tour created.",
            execution_session_id="session-property-tour-video-fail",
            principal_id=principal_id,
            structured_output_json={
                "hosted_url": "https://myexternalbrain.com/tours/video-fail-123",
                "public_url": "https://myexternalbrain.com/tours/video-fail-123",
                "crezlo_public_url": "https://vendor.example.com/tours/video-fail-123",
                "editor_url": "https://vendor.example.com/editor/video-fail-123",
                "tour_id": "tour-video-fail-123",
            },
        )

    client.app.state.container.orchestrator.execute_task_artifact = _fake_execute_task_artifact

    class _TelegramTextReceipt:
        chat_id = "1354554303"
        message_ids = ("tg-2",)

    monkeypatch.setattr(product_service, "send_telegram_message_for_principal", lambda *args, **kwargs: _TelegramTextReceipt())
    monkeypatch.setattr(product_service, "send_telegram_video_for_principal", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("telegram_video_audio_missing")))

    created = client.post(
        "/app/api/signals/willhaben/property-tour",
        json={"property_url": packet["property_url"], "binding_id": "browseract-binding-1"},
    )
    assert created.status_code == 200
    body = created.json()
    assert body["status"] == "sent"
    assert body["delivery_status"] == "sent"
    assert body["telegram_delivery_status"] == "sent"
    assert body["telegram_video_delivery_status"] == "failed"
    assert body["telegram_video_followup_ref"].startswith("human_task:")

    handoffs = client.get("/app/api/handoffs")
    assert handoffs.status_code == 200
    assert any(item["id"] == body["telegram_video_followup_ref"] for item in handoffs.json())

    events = client.get("/app/api/events", params={"channel": "product", "event_type": "willhaben_property_tour_telegram_video_failed"})
    assert events.status_code == 200
    assert any(item["payload"]["telegram_video_followup_ref"] == body["telegram_video_followup_ref"] for item in events.json()["items"])


def test_preference_profile_teable_projection_endpoints_return_live_rows() -> None:
    principal_id = "pref-teable-api"
    client = build_product_client(principal_id=principal_id)

    client.post(
        "/app/api/people/self/preference-profile",
        json={
            "display_name": "Tibor",
            "consent_mode": "behavioral_learning",
            "learning_enabled": True,
        },
    )
    client.post(
        "/app/api/people/self/preference-profile/nodes",
        json={
            "domain": "willhaben",
            "category": "soft_preference",
            "key": "preferred_districts",
            "value_json": ["Waehring"],
            "confidence": 0.8,
        },
    )

    projection = client.get("/app/api/people/self/preference-profile/teable-projection")
    assert projection.status_code == 200
    projection_body = projection.json()
    assert "preference_review_queue" in projection_body
    assert projection_body["preference_review_queue"][0]["display_name"] == "Tibor"
    assert projection_body["preference_review_queue"][0]["key"] == "preferred_districts"

    summary = client.get("/app/api/people/self/preference-profile/teable-projection-summary")
    assert summary.status_code == 200
    table = next(item for item in summary.json()["tables"] if item["table_name"] == "preference_review_queue")
    assert table["record_count"] >= 1


def test_property_feedback_records_preference_learning_and_updates_assessment() -> None:
    principal_id = "pref-property-feedback"
    client = build_product_client(principal_id=principal_id)
    container = client.app.state.container
    product = product_service.build_product_service(container)

    result = product.record_property_feedback(
        principal_id=principal_id,
        property_slug="feedback-flat-1",
        property_url="https://www.willhaben.at/iad/immobilien/d/mietwohnungen/wien/wien-1190-doebling/feedback-flat-1",
        property_title="Feedback Flat 1",
        property_facts={
            "postal_name": "Doebling",
            "district": "Doebling",
            "heating_type": "Gasheizung",
            "total_rent_eur": 2450.0,
            "area_sqm": 68.0,
            "nearest_subway_m": 1400.0,
            "has_floorplan": False,
            "lift": False,
        },
        reaction="dislike",
        reason_keys=("gas_heating", "underground_too_far", "no_lift"),
        note="Feels wrong for daily life.",
        actor="test",
    )

    assert result["status"] == "recorded"
    applied = result["evidence"]["applied_nodes"]
    assert any(item["key"] == "avoid_heating_types" for item in applied)
    assert any(item["key"] == "prefer_subway_nearby" for item in applied)
    assert any(item["key"] == "prefer_lift" for item in applied)
    assert any("heating aversion" in entry.lower() for entry in result["updated_assessment"]["mismatch_reasons_json"])
    assert "Avoid heating: Gasheizung" in result["learning_summary"]["dislikes"]


def test_preference_profile_teable_sync_preview_fails_closed_without_executable_lane() -> None:
    principal_id = "pref-teable-sync-preview"
    client = build_product_client(principal_id=principal_id)

    client.post(
        "/app/api/people/self/preference-profile",
        json={
            "display_name": "Tibor",
            "consent_mode": "behavioral_learning",
            "learning_enabled": True,
        },
    )
    client.post(
        "/app/api/people/self/preference-profile/nodes",
        json={
            "domain": "willhaben",
            "category": "soft_preference",
            "key": "preferred_districts",
            "value_json": ["Waehring"],
            "confidence": 0.8,
        },
    )

    preview = client.get("/app/api/people/self/preference-profile/teable-sync-preview")
    assert preview.status_code == 200
    preview_body = preview.json()
    assert preview_body["status"] == "blocked"
    assert preview_body["blocked_reason"] == "teable_table_sync_config_missing"
    assert preview_body["provider"]["provider_key"] == "teable"
    assert preview_body["provider"]["table_sync_configured"] is False
    assert preview_body["route"]["capability_key"] == "table_sync"
    assert preview_body["projected_record_count"] >= 1

    requested = client.post("/app/api/people/self/preference-profile/teable-sync")
    assert requested.status_code == 200
    requested_body = requested.json()
    assert requested_body["sync_attempted"] is False
    assert requested_body["sync_result"] == "blocked"
    assert requested_body["blocked_reason"] == "teable_table_sync_config_missing"


def test_preference_profile_teable_sync_can_use_executable_lane_when_available(monkeypatch) -> None:
    from app.domain.models import ToolInvocationResult

    principal_id = "pref-teable-sync-exec"
    client = build_product_client(principal_id=principal_id)
    container = client.app.state.container

    client.post(
        "/app/api/people/self/preference-profile",
        json={
            "display_name": "Tibor",
            "consent_mode": "behavioral_learning",
            "learning_enabled": True,
        },
    )
    client.post(
        "/app/api/people/self/preference-profile/nodes",
        json={
            "domain": "willhaben",
            "category": "soft_preference",
            "key": "preferred_districts",
            "value_json": ["Waehring"],
            "confidence": 0.8,
        },
    )

    monkeypatch.setattr(
        container.provider_registry,
        "candidate_routes_by_capability_with_context",
        lambda **_: (
            SimpleNamespace(
                provider_key="teable",
                capability_key="table_sync",
                tool_name="provider.teable.table_sync",
                executable=True,
            ),
        ),
    )
    monkeypatch.setenv(
        "TEABLE_TABLE_SYNC_CONFIG_JSON",
        json.dumps(
            {
                "preference_review_queue": {
                    "table_id": "tbl_preference_review_queue",
                    "key_field": "projection_id",
                    "field_key_type": "name",
                }
            }
        ),
    )
    monkeypatch.setattr(
        container.provider_registry,
        "binding_state",
        lambda provider_key, principal_id=None: SimpleNamespace(
            provider_key=provider_key,
            display_name="Teable",
            state="ready",
            enabled=True,
            executable=True,
            binding_id=f"{principal_id}:teable",
            secret_configured=True,
            updated_at="2026-05-25T00:00:00Z",
        ),
    )
    monkeypatch.setattr(product_service.ProductService, "_teable_sync_runtime_available", lambda self, *, base_url: (True, ""))

    def _execute(invocation):
        assert invocation.tool_name == "provider.teable.table_sync"
        assert invocation.action_kind == "table.sync"
        assert invocation.payload_json["projection_scope"] == "preference_profile"
        assert invocation.payload_json["person_id"] == "self"
        assert "preference_review_queue" in invocation.payload_json["tables_json"]
        return ToolInvocationResult(
            tool_name=invocation.tool_name,
            action_kind=invocation.action_kind,
            target_ref="teable-sync:pref-teable-sync-exec:self",
            output_json={"synced_tables": ["preference_review_queue"]},
            receipt_json={"status": "pass", "rows_upserted": 1},
        )

    monkeypatch.setattr(container.tool_execution, "execute_invocation", _execute)

    requested = client.post("/app/api/people/self/preference-profile/teable-sync")
    assert requested.status_code == 200
    requested_body = requested.json()
    assert requested_body["status"] == "ready"
    assert requested_body["sync_attempted"] is True
    assert requested_body["sync_result"] == "sent"
    assert requested_body["tool_execution"]["target_ref"] == "teable-sync:pref-teable-sync-exec:self"
    assert requested_body["tool_execution"]["receipt_json"]["rows_upserted"] == 1


def test_preference_profile_teable_sync_preview_blocks_when_runtime_is_unreachable(monkeypatch) -> None:
    principal_id = "pref-teable-sync-runtime-down"
    client = build_product_client(principal_id=principal_id)
    container = client.app.state.container

    client.post(
        "/app/api/people/self/preference-profile",
        json={
            "display_name": "Tibor",
            "consent_mode": "behavioral_learning",
            "learning_enabled": True,
        },
    )
    client.post(
        "/app/api/people/self/preference-profile/nodes",
        json={
            "domain": "willhaben",
            "category": "soft_preference",
            "key": "preferred_districts",
            "value_json": ["Waehring"],
            "confidence": 0.8,
        },
    )

    monkeypatch.setattr(
        container.provider_registry,
        "candidate_routes_by_capability_with_context",
        lambda **_: (
            SimpleNamespace(
                provider_key="teable",
                capability_key="table_sync",
                tool_name="provider.teable.table_sync",
                executable=True,
            ),
        ),
    )
    monkeypatch.setenv(
        "TEABLE_TABLE_SYNC_CONFIG_JSON",
        json.dumps(
            {
                "preference_review_queue": {
                    "table_id": "tbl_preference_review_queue",
                    "key_field": "projection_id",
                    "field_key_type": "name",
                }
            }
        ),
    )
    monkeypatch.setenv("TEABLE_API_KEY", "test-teable-key")
    monkeypatch.setenv("TEABLE_BASE_URL", "http://host.docker.internal:18787")
    monkeypatch.setattr(
        container.provider_registry,
        "binding_state",
        lambda provider_key, principal_id=None: SimpleNamespace(
            provider_key=provider_key,
            display_name="Teable",
            state="ready",
            enabled=True,
            executable=True,
            binding_id=f"{principal_id}:teable",
            secret_configured=True,
            updated_at="2026-05-25T00:00:00Z",
        ),
    )
    monkeypatch.setattr(
        product_service.ProductService,
        "_teable_sync_runtime_available",
        lambda self, *, base_url: (False, "teable_runtime_unreachable"),
    )

    preview = client.get("/app/api/people/self/preference-profile/teable-sync-preview")
    assert preview.status_code == 200
    preview_body = preview.json()
    assert preview_body["status"] == "blocked"
    assert preview_body["blocked_reason"] == "teable_runtime_unreachable"
    assert preview_body["provider"]["table_sync_configured"] is True
    assert preview_body["provider"]["runtime_reachable"] is False
    assert preview_body["provider"]["base_url"] == "http://host.docker.internal:18787"


def test_willhaben_property_tour_route_prefers_panorama_media_and_disables_floorplan_scene_in_360_mode(monkeypatch) -> None:
    from app.domain.models import Artifact

    principal_id = "cf-email:tibor.girschele@gmail.com"
    client = build_product_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Executive Office")

    packet = {
        "property_url": "https://www.willhaben.at/iad/immobilien/d/mietwohnungen/wien/panorama-apartment-123",
        "listing_id": "listing-panorama-123",
        "listing_uuid": "listing-uuid-panorama-123",
        "title": "Panorama apartment",
        "property_facts_json": {},
        "media_urls_json": ["https://cdn.example.com/apartment-panorama/photo-1.jpg"],
        "panorama_media_urls_json": ["https://cdn.example.com/apartment-panorama/room-360.jpg"],
        "floorplan_urls_json": ["https://cdn.example.com/apartment-panorama/floorplan-1.jpg"],
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

    def _fake_execute_task_artifact(request):  # type: ignore[no-untyped-def]
        assert request.input_json["media_urls_json"] == ["https://cdn.example.com/apartment-panorama/room-360.jpg"]
        assert request.input_json["floorplan_urls_json"] == []
        assert request.input_json["scene_strategy"] == "photo_only"
        assert request.input_json["scene_selection_json"]["include_floorplans"] is False
        assert request.input_json["property_facts_json"]["tour_media_mode"] == "panorama_360"
        assert request.input_json["runtime_inputs_json"]["tour_media_mode"] == "panorama_360"
        return Artifact(
            artifact_id="artifact-property-tour-panorama-1",
            kind="property_tour_packet",
            content="Property tour created.",
            execution_session_id="session-property-tour-panorama-1",
            principal_id=principal_id,
            structured_output_json={"public_url": "https://vendor.example.com/tours/panorama-apartment"},
        )

    client.app.state.container.orchestrator.execute_task_artifact = _fake_execute_task_artifact

    created = client.post(
        "/app/api/signals/willhaben/property-tour",
        json={
            "property_url": packet["property_url"],
            "binding_id": "browseract-binding-panorama-1",
            "auto_deliver": False,
        },
    )
    assert created.status_code == 200
    body = created.json()
    assert body["status"] == "created"
    assert body["tour_media_mode"] == "panorama_360"


def test_willhaben_property_tour_route_accepts_external_live_360_source_when_panorama_images_are_absent(monkeypatch) -> None:
    from app.domain.models import Artifact

    principal_id = "cf-email:tibor.girschele@gmail.com"
    client = build_product_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Executive Office")

    packet = {
        "property_url": "https://www.willhaben.at/iad/immobilien/d/mietwohnungen/wien/external-360-apartment-123",
        "listing_id": "listing-external-360-123",
        "listing_uuid": "listing-uuid-external-360-123",
        "title": "External 360 apartment",
        "property_facts_json": {},
        "media_urls_json": ["https://cdn.example.com/apartment/photo-1.jpg"],
        "panorama_media_urls_json": [],
        "floorplan_urls_json": ["https://cdn.example.com/apartment/floorplan-1.jpg"],
        "source_virtual_tour_url": "https://360.example.test/view/portal/id/external-360-apartment",
        "panorama_source": "feelestate_kalandra",
        "tour_variants_json": [
            {
                "variant_key": "layout_first",
                "scene_strategy": "layout_first",
                "theme_name": "clean_light",
                "tour_style": "guided_layout_walkthrough",
                "audience": "tenant_screening",
                "creative_brief": "Lead with the live 360 source.",
                "call_to_action": "Open the tour.",
                "scene_selection_json": {"include_floorplans": True},
                "tour_settings_json": {"showSceneNumbers": True},
            }
        ],
    }
    monkeypatch.setattr(product_service, "_load_willhaben_property_packet", lambda url: dict(packet))

    def _fake_execute_task_artifact(request):  # type: ignore[no-untyped-def]
        assert request.input_json["media_urls_json"] == ["https://cdn.example.com/apartment/photo-1.jpg"]
        assert request.input_json["floorplan_urls_json"] == ["https://cdn.example.com/apartment/floorplan-1.jpg"]
        assert request.input_json["source_virtual_tour_url"] == "https://360.example.test/view/portal/id/external-360-apartment"
        assert request.input_json["panorama_source"] == "feelestate_kalandra"
        assert request.input_json["property_facts_json"]["tour_media_mode"] == "panorama_360"
        assert request.input_json["runtime_inputs_json"]["tour_media_mode"] == "panorama_360"
        return Artifact(
            artifact_id="artifact-property-tour-external-360-1",
            kind="property_tour_packet",
            content="Property tour created.",
            execution_session_id="session-property-tour-external-360-1",
            principal_id=principal_id,
            structured_output_json={"public_url": "https://vendor.example.com/tours/external-360-apartment"},
        )

    client.app.state.container.orchestrator.execute_task_artifact = _fake_execute_task_artifact

    created = client.post(
        "/app/api/signals/willhaben/property-tour",
        json={
            "property_url": packet["property_url"],
            "binding_id": "browseract-binding-external-360-1",
            "auto_deliver": False,
        },
    )
    assert created.status_code == 200
    body = created.json()
    assert body["status"] == "created"
    assert body["tour_media_mode"] == "panorama_360"


def test_willhaben_property_tour_route_publishes_pure_360_bundle_when_crezlo_is_unavailable(monkeypatch, tmp_path: Path) -> None:
    principal_id = "cf-email:tibor.girschele@gmail.com"
    client = build_product_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Executive Office")

    monkeypatch.setattr(
        product_service,
        "_load_willhaben_property_packet",
        lambda url: {
            "property_url": url,
            "listing_id": "listing-pure-360-1",
            "listing_uuid": "listing-uuid-pure-360-1",
            "title": "Pure 360 apartment",
            "property_facts_json": {
                "attribute_map": {
                    "VIRTUAL_VIEW_LINK/URL": ["https://my.matterport.com/show/?m=BmVWxvZQZLq"],
                }
            },
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
        },
    )
    monkeypatch.setattr(
        client.app.state.container.orchestrator,
        "execute_task_artifact",
        lambda request: (_ for _ in ()).throw(RuntimeError("crezlo_property_tour_not_configured")),
    )
    monkeypatch.setattr(
        product_service,
        "_write_hosted_feelestate_pure_360_property_tour_bundle",
        lambda **kwargs: {
            "slug": "pure-360-apartment",
            "tour_id": "tour-pure-360-apartment",
            "public_url": "https://propertyquarry.com/tours/pure-360-apartment",
            "crezlo_public_url": "https://my.matterport.com/show/?m=BmVWxvZQZLq",
        },
    )
    monkeypatch.setenv("PROPERTYQUARRY_PUBLIC_TOUR_BASE_URL", "https://propertyquarry.com/tours")

    created = client.post(
        "/app/api/signals/willhaben/property-tour",
        json={
            "property_url": "https://www.willhaben.at/iad/object?adId=1585607380",
            "binding_id": "browseract-binding-pure-360-1",
            "auto_deliver": False,
        },
    )
    assert created.status_code == 200, created.text
    body = created.json()
    assert body["status"] == "created"
    assert body["tour_media_mode"] == "panorama_360"
    assert body["tour_url"].startswith("https://propertyquarry.com/tours/")
    assert body["vendor_tour_url"] == "https://my.matterport.com/show/?m=BmVWxvZQZLq"


def test_willhaben_property_tour_route_blocks_when_only_flat_listing_photos_exist_and_360_is_required(monkeypatch) -> None:
    principal_id = "cf-email:tibor.girschele@gmail.com"
    client = build_product_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Executive Office")

    monkeypatch.setattr(
        product_service,
        "_load_willhaben_property_packet",
        lambda url: {
            "property_url": url,
            "listing_id": "listing-flat-123",
            "listing_uuid": "listing-uuid-flat-123",
            "title": "Flat-photo apartment",
            "property_facts_json": {},
            "media_urls_json": ["https://cdn.example.com/apartment-flat/photo-1.jpg"],
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
            "property_url": "https://www.willhaben.at/iad/immobilien/d/mietwohnungen/wien/flat-photo-apartment-123",
            "binding_id": "browseract-binding-flat-1",
            "auto_deliver": False,
        },
    )
    assert created.status_code == 200
    body = created.json()
    assert body["status"] == "blocked"
    assert body["blocked_reason"] == "listing_360_media_missing"
    assert body["tour_media_mode"] == "flat_images"


def test_willhaben_property_tour_route_falls_back_to_projected_crezlo_task_when_base_contract_missing(monkeypatch) -> None:
    from app.domain.models import Artifact

    monkeypatch.setenv("EA_WILLHABEN_PROPERTY_TOUR_REQUIRE_360", "0")
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
        assert request.input_json["force_ui_worker"] is False
        assert request.input_json["proxy_result"] is True
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


def test_property_tour_url_resolver_does_not_fallback_to_vendor_as_primary(monkeypatch) -> None:
    monkeypatch.setenv("EA_PUBLIC_APP_BASE_URL", "https://myexternalbrain.com")
    branded_url, vendor_url = product_service._resolve_property_tour_urls(
        {
            "public_url": "https://vendor.example.com/tours/brigittenau-apartment-a",
            "share_url": "https://vendor.example.com/share/brigittenau-apartment-a",
        }
    )
    assert branded_url == ""
    assert vendor_url == "https://vendor.example.com/tours/brigittenau-apartment-a"


def test_property_scout_tour_auto_create_skips_existing_vendor_url(monkeypatch) -> None:
    principal_id = "cf-email:tibor.girschele@gmail.com"
    client = build_product_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Property Scout Office")
    service = ProductService(client.app.state.container)
    source_ref = "gmail-thread:tibor.girschele@gmail.com:legacy-kalandra-tour"

    service._record_product_event(
        principal_id=principal_id,
        event_type="generic_property_tour_created",
        source_id=source_ref,
        payload={
            "tour_url": "https://www.kalandra.at/objekt/legacy-tour-1",
            "vendor_tour_url": "https://vendor.example.com/tours/legacy-tour-1",
        },
    )

    create_calls: list[dict[str, object]] = []

    def _fake_create_willhaben_property_tour(**kwargs: object) -> dict[str, object]:
        create_calls.append(dict(kwargs))
        return {
            "status": "created",
            "tour_url": "https://myexternalbrain.com/tours/recreated-tour-1",
            "vendor_tour_url": "https://vendor.example.com/tours/recreated-tour-1",
            "blocked_reason": "",
        }

    monkeypatch.setattr(service, "create_willhaben_property_tour", _fake_create_willhaben_property_tour)

    result = service._maybe_auto_create_property_scout_tour(
        principal_id=principal_id,
        actor="property-scout",
        property_url="https://www.kalandra.at/objekt/14997053",
        source_ref=source_ref,
        assessment={"fit_score": 95.0, "recommendation": "shortlist"},
    )

    assert result["status"] == "created"
    assert result["tour_url"].startswith("https://myexternalbrain.com/tours/")
    assert len(create_calls) == 1


def test_property_scout_tour_auto_create_reuses_existing_branded_url(monkeypatch) -> None:
    principal_id = "cf-email:tibor.girschele@gmail.com"
    client = build_product_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Property Scout Office")
    service = ProductService(client.app.state.container)
    source_ref = "gmail-thread:tibor.girschele@gmail.com:branded-tourexisting"

    service._record_product_event(
        principal_id=principal_id,
        event_type="generic_property_tour_created",
        source_id=source_ref,
        payload={
            "tour_url": "https://myexternalbrain.com/tours/brigittenau-apartment-a",
            "vendor_tour_url": "https://vendor.example.com/tours/brigittenau-apartment-a",
        },
    )

    create_calls: list[dict[str, object]] = []

    def _fake_create_willhaben_property_tour(**kwargs: object) -> dict[str, object]:
        create_calls.append(dict(kwargs))
        return {
            "status": "created",
            "tour_url": "https://myexternalbrain.com/tours/recreated-tour-2",
            "vendor_tour_url": "https://vendor.example.com/tours/recreated-tour-2",
            "blocked_reason": "",
        }

    monkeypatch.setattr(service, "create_willhaben_property_tour", _fake_create_willhaben_property_tour)

    result = service._maybe_auto_create_property_scout_tour(
        principal_id=principal_id,
        actor="property-scout",
        property_url="https://www.kalandra.at/objekt/14997053",
        source_ref=source_ref,
        assessment={"fit_score": 95.0, "recommendation": "shortlist"},
    )

    assert result["status"] == "existing"
    assert result["tour_url"] == "https://myexternalbrain.com/tours/brigittenau-apartment-a"
    assert result["vendor_tour_url"] == "https://vendor.example.com/tours/brigittenau-apartment-a"
    assert not create_calls


def test_existing_hosted_property_tour_url_requires_real_bundle_assets(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("EA_PUBLIC_TOUR_DIR", str(tmp_path))
    monkeypatch.setenv("EA_PUBLIC_TOUR_BASE_URL", "https://myexternalbrain.com/tours")
    slug = "broken-bundle-tour"
    bundle_dir = tmp_path / slug
    bundle_dir.mkdir(parents=True)
    (bundle_dir / "tour.json").write_text(
        json.dumps(
            {
                "slug": slug,
                "scenes": [
                    {"asset_relpath": "scene-01.jpg"},
                ],
            }
        ),
        encoding="utf-8",
    )

    assert product_service._existing_hosted_property_tour_url({"slug": slug}) == ""

    (bundle_dir / "scene-01.jpg").write_bytes(b"real-asset")
    assert product_service._existing_hosted_property_tour_url({"slug": slug}) == (
        "https://myexternalbrain.com/tours/broken-bundle-tour"
    )


def test_existing_hosted_property_tour_url_deep_links_live_360_when_manifest_has_source_tour(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("EA_PUBLIC_TOUR_DIR", str(tmp_path))
    monkeypatch.setenv("EA_PUBLIC_TOUR_BASE_URL", "https://myexternalbrain.com/tours")
    slug = "live-360-tour"
    bundle_dir = tmp_path / slug
    bundle_dir.mkdir(parents=True)
    (bundle_dir / "scene-01.jpg").write_bytes(b"real-asset")
    (bundle_dir / "tour.json").write_text(
        json.dumps(
            {
                "slug": slug,
                "source_virtual_tour_url": "https://360.example.test/view/portal/id/live-360-tour",
                "scenes": [
                    {"asset_relpath": "scene-01.jpg"},
                ],
            }
        ),
        encoding="utf-8",
    )

    assert product_service._existing_hosted_property_tour_url({"slug": slug}) == (
        "https://myexternalbrain.com/tours/live-360-tour#live-360"
    )


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
    monkeypatch.setenv("EA_WILLHABEN_PROPERTY_TOUR_REQUIRE_360", "0")
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
    monkeypatch.setenv("EA_WILLHABEN_PROPERTY_TOUR_REQUIRE_360", "0")
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


def test_willhaben_property_tour_block_followup_sends_telegram_scout_update(monkeypatch) -> None:
    monkeypatch.delenv("BROWSERACT_API_KEY", raising=False)
    monkeypatch.setenv("EA_WILLHABEN_PROPERTY_TOUR_REQUIRE_360", "0")
    principal_id = "cf-email:tibor.girschele@gmail.com"
    client = build_product_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Executive Office")

    packet = {
        "property_url": "https://www.willhaben.at/iad/immobilien/d/mietwohnungen/wien/apartment-followup-telegram-001",
        "listing_id": "listing-followup-telegram-001",
        "title": "Quiet district apartment",
        "listing_uuid": "listing-followup-telegram-uuid-001",
        "property_facts_json": {},
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
    sent: list[dict[str, object]] = []
    monkeypatch.setattr(
        product_service,
        "send_telegram_message_for_principal",
        lambda *args, **kwargs: sent.append({"args": args, "kwargs": kwargs}) or SimpleNamespace(message_ids=["tg-followup-1"], chat_id="1354554303"),
    )

    created = client.post(
        "/app/api/signals/willhaben/property-tour",
        json={
            "property_url": packet["property_url"],
        },
    )
    assert created.status_code == 200
    body = created.json()
    assert body["status"] == "blocked"
    assert body["blocked_reason"] == "browseract_connector_unconfigured"
    assert sent
    assert "Scout update." in str(sent[0]["kwargs"]["text"])
    assert "Next: reconnect the tour worker and regenerate the tour." in str(sent[0]["kwargs"]["text"])

    events = client.get(
        "/app/api/events",
        params={"channel": "product", "event_type": "property_tour_followup_telegram_sent"},
    )
    assert events.status_code == 200
    assert any(item["payload"]["telegram_chat_ref"] == "1354554303" for item in events.json()["items"])


def test_office_signal_can_auto_create_willhaben_property_tour(monkeypatch) -> None:
    from app.domain.models import Artifact
    from app.services.registration_email import RegistrationEmailReceipt

    monkeypatch.setenv("EMAILIT_API_KEY", "test-emailit-key")
    monkeypatch.setenv("EA_WILLHABEN_PROPERTY_TOUR_REQUIRE_360", "0")
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


def test_noneverbia_meeting_import_from_local_json_archive(tmp_path, monkeypatch) -> None:
    principal_id = "exec-product-noneverbia-import"
    client = build_product_client(principal_id=principal_id)
    seed_product_state(client, principal_id=principal_id)
    export_path = tmp_path / "noneverbia_meetings.json"
    export_path.write_text(
        json.dumps(
            [
                {
                    "id": "meeting-1",
                    "title": "Pocket meeting",
                    "summary": {"markdown": "Prefers concise weekly planning and direct follow-ups."},
                    "transcript": {"text": "I prefer concise weekly planning and direct follow-ups."},
                    "participants": [{"name": "Sofia"}],
                    "action_items": ["Send the revised board packet"],
                    "tags": ["meeting", "sofia"],
                    "meeting_at": "2026-05-01T08:00:00Z",
                }
            ]
        ),
        encoding="utf-8",
    )

    monkeypatch.setenv("EA_NONEVERBIA_IMPORT_ROOT", str(tmp_path))
    imported = client.post("/app/api/signals/noneverbia/import-local", json={"path": str(export_path)})
    assert imported.status_code == 200
    body = imported.json()
    assert body["source_path"] == str(export_path)
    assert body["source_formats"] == ["json"]
    assert body["parsed_entry_total"] == 1
    assert body["total"] == 1
    assert body["synced_total"] == 1
    assert body["deduplicated_total"] == 0
    assert body["preference_evidence_total"] == 1
    assert body["preference_evidence_applied_total"] >= 0
    assert body["items"][0]["channel"] == "noneverbia"
    assert body["items"][0]["event_type"] == "office_signal_meeting_analysis"
    assert body["items"][0]["source_id"] == "noneverbia-meeting:meeting-1"

    events = client.get("/app/api/events", params={"channel": "noneverbia"})
    assert events.status_code == 200
    imported_event = next(item for item in events.json()["items"] if item["source_id"] == "noneverbia-meeting:meeting-1")
    assert imported_event["payload"]["summary_markdown"] == "Prefers concise weekly planning and direct follow-ups."
    assert imported_event["payload"]["action_items"] == "Send the revised board packet"

    preferences = client.get("/app/api/people/self/preference-profile")
    assert preferences.status_code == 200
    assert preferences.json()["profile"]["person_id"] == "self"
    assert preferences.json()["preference_nodes"]


def test_noneverbia_meeting_import_rejects_absolute_path_outside_allowed_root(tmp_path, monkeypatch) -> None:
    principal_id = "exec-product-noneverbia-import-blocked"
    client = build_product_client(principal_id=principal_id)
    seed_product_state(client, principal_id=principal_id)
    allowed_root = tmp_path / "allowed"
    allowed_root.mkdir(parents=True)
    outside = tmp_path / "outside.json"
    outside.write_text(json.dumps([{"id": "meeting-1", "title": "Blocked"}]), encoding="utf-8")
    monkeypatch.setenv("EA_NONEVERBIA_IMPORT_ROOT", str(allowed_root))

    imported = client.post("/app/api/signals/noneverbia/import-local", json={"path": str(outside)})
    assert imported.status_code == 403
    assert "noneverbia_import_path_not_allowed" in imported.text


def test_pocket_api_sync_ingests_completed_recordings(monkeypatch) -> None:
    principal_id = "exec-product-pocket-sync"
    client = build_product_client(principal_id=principal_id)
    seed_product_state(client, principal_id=principal_id)
    monkeypatch.setenv("EA_POCKET_AUDIO_ARCHIVE_ENABLED", "1")
    captured_rows: list[dict[str, object]] = []

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
    monkeypatch.setattr(
        product_service.ProductService,
        "_archive_pocket_recording_audio",
        lambda self, *, principal_id, actor, payload: {
            "archive_status": "archived",
            "archive_reason": "",
            "archive_root": "/mnt/pcloud/EA/pocket-ai-audio",
            "archive_path": "/mnt/pcloud/EA/pocket-ai-audio/exec-product-pocket-sync/2026/05/2026-05-01__done-1__pocket-meeting.mp3",
            "archive_sha256": "abc123",
            "duration_seconds": 62.0,
            "min_duration_seconds": 60.0,
            "recording_id": "done-1",
            "title": "Pocket meeting",
        },
    )
    def _capture_teable_rows(self, *, principal_id, rows):
        captured_rows[:] = [dict(row) for row in rows]
        return {
            "status": "synced",
            "sync_attempted": True,
            "row_total": len(rows),
            "blocked_reason": "",
        }

    monkeypatch.setattr(
        product_service.ProductService,
        "_sync_pocket_audio_archive_index_to_teable",
        _capture_teable_rows,
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
    assert body["archived_total"] == 1
    assert body["archive_dismissed_total"] == 0
    assert body["archive_failed_total"] == 0
    assert body["teable_index_status"] == "synced"
    assert body["teable_index_row_total"] == 1
    assert body["cursor_recording_id"] == "pending-1"
    assert body["cursor_updated_at"] == ""
    assert body["cursor_advanced"] is True
    assert body["items"][0]["channel"] == "pocket"
    assert body["items"][0]["event_type"] == "office_signal_audio_recording"
    assert body["items"][0]["source_id"] == "pocket-recording:done-1"
    assert captured_rows[0]["audio_download_url"] == ""
    assert "audio_download_url_host" not in captured_rows[0]
    assert "board" in str(captured_rows[0]["topic_keywords_csv"])
    assert "sofia" in str(captured_rows[0]["topic_keywords_csv"])

    events = client.get("/app/api/events", params={"channel": "pocket"})
    assert events.status_code == 200
    event = next(item for item in events.json()["items"] if item["source_id"] == "pocket-recording:done-1")
    assert event["payload"]["summary_markdown"] == "Send the revised board packet to Sofia today."
    assert event["payload"]["transcript_excerpt"] == "Discuss the board packet and send the revised version to Sofia."
    assert "audio_download_url" not in event["payload"]
    assert event["payload"]["audio_archive_status"] == "archived"
    assert event["payload"]["audio_archive_path"].endswith("__done-1__pocket-meeting.mp3")
    product_events = client.get("/app/api/events", params={"channel": "product", "event_type": "pocket_recording_archive_indexed"})
    assert product_events.status_code == 200
    archive_indexed = next(item for item in product_events.json()["items"] if item["payload"]["recording_id"] == "done-1")
    assert "board" in str(archive_indexed["payload"]["topic_keywords_csv"])


def test_pocket_api_sync_dismisses_subminute_recordings_from_continuous_archive(monkeypatch) -> None:
    principal_id = "exec-product-pocket-sync-short"
    client = build_product_client(principal_id=principal_id)
    seed_product_state(client, principal_id=principal_id)
    monkeypatch.setenv("EA_POCKET_AUDIO_ARCHIVE_ENABLED", "1")

    monkeypatch.setattr(
        product_service,
        "_pocket_list_recordings",
        lambda *, limit, page=1: {
            "success": True,
            "data": [
                {"id": "short-1", "title": "Pocket note", "state": "completed"},
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
                "title": "Pocket note",
                "state": "completed",
                "duration": 42.0,
                "language": "en",
                "recording_at": "2026-05-01T09:00:00Z",
                "created_at": "2026-05-01T09:00:10Z",
                "updated_at": "2026-05-01T09:00:20Z",
                "tags": ["memo"],
                "transcript": {
                    "text": "Remember the charger.",
                    "segments": [{"start": 0.0, "end": 2.0, "text": "Remember the charger."}],
                    "metadata": {"source": "api"},
                },
                "summarizations": {},
            },
        },
    )
    monkeypatch.setattr(
        product_service.ProductService,
        "_archive_pocket_recording_audio",
        lambda self, *, principal_id, actor, payload: {
            "archive_status": "dismissed",
            "archive_reason": "duration_below_minimum",
            "archive_root": "/mnt/pcloud/EA/pocket-ai-audio",
            "archive_path": "",
            "archive_sha256": "",
            "duration_seconds": 42.0,
            "min_duration_seconds": 60.0,
            "recording_id": "short-1",
            "title": "Pocket note",
        },
    )
    monkeypatch.setattr(
        product_service.ProductService,
        "_sync_pocket_audio_archive_index_to_teable",
        lambda self, *, principal_id, rows: {
            "status": "synced",
            "sync_attempted": True,
            "row_total": len(rows),
            "blocked_reason": "",
        },
    )

    synced = client.post("/app/api/signals/pocket/sync", params={"limit": 5})
    assert synced.status_code == 200
    body = synced.json()
    assert body["total"] == 0
    assert body["synced_total"] == 0
    assert body["suppressed_total"] == 1
    assert body["archived_total"] == 0
    assert body["archive_dismissed_total"] == 1
    assert body["archive_failed_total"] == 0


def test_pocket_api_sync_dismisses_completed_recording_when_audio_is_unavailable(monkeypatch) -> None:
    principal_id = "exec-product-pocket-sync-audio-unavailable"
    client = build_product_client(principal_id=principal_id)
    seed_product_state(client, principal_id=principal_id)
    monkeypatch.setenv("EA_POCKET_AUDIO_ARCHIVE_ENABLED", "1")

    monkeypatch.setattr(
        product_service,
        "_pocket_list_recordings",
        lambda *, limit, page=1: {
            "success": True,
            "data": [
                {"id": "sample-1", "title": "Getting Started with Pocket", "state": "completed"},
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
                "title": "Getting Started with Pocket",
                "state": "completed",
                "duration": 120.0,
                "language": "en",
                "recording_at": "2026-05-01T09:00:00Z",
                "created_at": "2026-05-01T09:00:10Z",
                "updated_at": "2026-05-01T09:00:20Z",
                "tags": ["sample"],
                "transcript": {
                    "text": "Welcome to Pocket.",
                    "segments": [{"start": 0.0, "end": 2.0, "text": "Welcome to Pocket."}],
                    "metadata": {"source": "api"},
                },
                "summarizations": {},
            },
        },
    )
    monkeypatch.setattr(
        product_service.ProductService,
        "_archive_pocket_recording_audio",
        lambda self, *, principal_id, actor, payload: (_ for _ in ()).throw(RuntimeError("pocket_recording_audio_unavailable")),
    )
    monkeypatch.setattr(
        product_service.ProductService,
        "_sync_pocket_audio_archive_index_to_teable",
        lambda self, *, principal_id, rows: {
            "status": "synced",
            "sync_attempted": True,
            "row_total": len(rows),
            "blocked_reason": "",
        },
    )

    synced = client.post("/app/api/signals/pocket/sync", params={"limit": 5})
    assert synced.status_code == 200
    body = synced.json()
    assert body["archive_dismissed_total"] == 1
    assert body["archive_failed_total"] == 0
    assert body["teable_index_row_total"] == 1

    product_events = client.get("/app/api/events", params={"channel": "product", "event_type": "pocket_recording_archive_indexed"})
    assert product_events.status_code == 200
    indexed = next(item for item in product_events.json()["items"] if item["payload"]["recording_id"] == "sample-1")
    assert indexed["payload"]["archive_status"] == "dismissed"


def test_pocket_api_sync_executes_assistant_shopping_list_trigger(monkeypatch) -> None:
    principal_id = "exec-product-pocket-sync-trigger"
    client = build_product_client(principal_id=principal_id)
    seed_product_state(client, principal_id=principal_id)
    captured_keep_calls: list[dict[str, object]] = []

    monkeypatch.setattr(
        product_service,
        "_pocket_list_recordings",
        lambda *, limit, page=1: {
            "success": True,
            "data": [
                {"id": "trigger-1", "title": "Pocket command", "state": "completed"},
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
                "title": "Pocket command",
                "state": "completed",
                "duration": 77.0,
                "language": "de",
                "recording_at": "2026-05-30T08:00:00Z",
                "created_at": "2026-05-30T08:00:10Z",
                "updated_at": "2026-05-30T08:00:20Z",
                "tags": ["memo"],
                "transcript": {
                    "text": "Assistent: put toilet paper on my shopping list.",
                    "segments": [{"start": 0.0, "end": 4.0, "text": "Assistent: put toilet paper on my shopping list."}],
                    "metadata": {"source": "api"},
                },
                "summarizations": {},
            },
        },
    )
    monkeypatch.setattr(
        product_service.ProductService,
        "_sync_pocket_audio_archive_index_to_teable",
        lambda self, *, principal_id, rows: {
            "status": "synced",
            "sync_attempted": True,
            "row_total": len(rows),
            "blocked_reason": "",
        },
    )

    monkeypatch.setattr(
        product_service.responses_upstream,
        "generate_text",
        lambda **kwargs: type(
            "UpstreamResultStub",
            (),
            {
                "text": json.dumps(
                    {
                        "action": "shopping_list_add",
                        "confidence": 0.93,
                        "reason": "spoken_request_to_add_item_to_shopping_list",
                        "params": {"item_text": "toilet paper"},
                    }
                )
            },
        )(),
    )
    monkeypatch.setattr(
        google_oauth_service,
        "create_google_keep_note",
        lambda **kwargs: (
            captured_keep_calls.append(dict(kwargs))
            or google_oauth_service.GoogleKeepNoteCreateResult(
                binding=object(),  # type: ignore[arg-type]
                note_name="notes/keep-op-1",
                title=str(kwargs.get("title") or ""),
                text_content=str(kwargs.get("text_content") or ""),
                list_item_texts=tuple(kwargs.get("list_item_texts") or ()),
                created_at="2026-05-30T08:00:30Z",
            )
        ),
    )

    synced = client.post("/app/api/signals/pocket/sync", params={"limit": 5})
    assert synced.status_code == 200
    body = synced.json()
    assert body["assistant_trigger_total"] == 1
    assert body["assistant_trigger_executed_total"] == 1
    assert body["assistant_trigger_blocked_total"] == 0
    assert captured_keep_calls[0]["title"] == "Shopping list"
    assert tuple(captured_keep_calls[0]["list_item_texts"]) == ("toilet paper",)

    product_events = client.get("/app/api/events", params={"channel": "product"})
    assert product_events.status_code == 200
    executed = next(item for item in product_events.json()["items"] if item["event_type"] == "pocket_assistant_command_executed")
    assert executed["payload"]["recording_id"] == "trigger-1"
    assert executed["payload"]["item_text"] == "toilet paper"
    assert executed["payload"]["classification_reason"] == "spoken_request_to_add_item_to_shopping_list"
    assert body["teable_index_status"] == "synced"
    assert body["teable_index_row_total"] == 1


def test_pocket_api_sync_executes_assistant_keep_note_trigger(monkeypatch) -> None:
    principal_id = "exec-product-pocket-sync-keep-note"
    client = build_product_client(principal_id=principal_id)
    seed_product_state(client, principal_id=principal_id)
    captured_keep_calls: list[dict[str, object]] = []

    monkeypatch.setattr(
        product_service,
        "_pocket_list_recordings",
        lambda *, limit, page=1: {
            "success": True,
            "data": [
                {"id": "trigger-keep-note-1", "title": "Pocket note command", "state": "completed"},
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
                "title": "Pocket note command",
                "state": "completed",
                "duration": 91.0,
                "language": "de",
                "recording_at": "2026-05-30T09:00:00Z",
                "created_at": "2026-05-30T09:00:10Z",
                "updated_at": "2026-05-30T09:00:20Z",
                "tags": ["memo"],
                "transcript": {
                    "text": "Assistent: speichere eine Keep-Notiz mit dem Titel Geschenkideen und dem Text neue Winterjacke fuer Noah.",
                    "segments": [{"start": 0.0, "end": 6.0, "text": "Assistent: speichere eine Keep-Notiz mit dem Titel Geschenkideen und dem Text neue Winterjacke fuer Noah."}],
                    "metadata": {"source": "api"},
                },
                "summarizations": {},
            },
        },
    )
    monkeypatch.setattr(
        product_service.ProductService,
        "_sync_pocket_audio_archive_index_to_teable",
        lambda self, *, principal_id, rows: {
            "status": "synced",
            "sync_attempted": True,
            "row_total": len(rows),
            "blocked_reason": "",
        },
    )
    monkeypatch.setattr(
        product_service.responses_upstream,
        "generate_text",
        lambda **kwargs: type(
            "UpstreamResultStub",
            (),
            {
                "text": json.dumps(
                    {
                        "action": "keep_note_append",
                        "confidence": 0.91,
                        "reason": "spoken_request_to_save_keep_note",
                        "params": {
                            "note_title": "Geschenkideen",
                            "note_text": "Neue Winterjacke fuer Noah",
                        },
                    }
                )
            },
        )(),
    )
    monkeypatch.setattr(
        google_oauth_service,
        "create_google_keep_note",
        lambda **kwargs: (
            captured_keep_calls.append(dict(kwargs))
            or google_oauth_service.GoogleKeepNoteCreateResult(
                binding=object(),  # type: ignore[arg-type]
                note_name="notes/keep-note-op-1",
                title=str(kwargs.get("title") or ""),
                text_content=str(kwargs.get("text_content") or ""),
                list_item_texts=tuple(kwargs.get("list_item_texts") or ()),
                created_at="2026-05-30T09:00:30Z",
            )
        ),
    )

    synced = client.post("/app/api/signals/pocket/sync", params={"limit": 5})
    assert synced.status_code == 200
    body = synced.json()
    assert body["assistant_trigger_total"] == 1
    assert body["assistant_trigger_executed_total"] == 1
    assert body["assistant_trigger_blocked_total"] == 0
    assert captured_keep_calls[0]["title"] == "Geschenkideen"
    assert captured_keep_calls[0]["text_content"] == "Neue Winterjacke fuer Noah"

    product_events = client.get("/app/api/events", params={"channel": "product"})
    assert product_events.status_code == 200
    executed = next(
        item
        for item in product_events.json()["items"]
        if item["event_type"] == "pocket_assistant_command_executed"
        and item["payload"]["recording_id"] == "trigger-keep-note-1"
    )
    assert executed["payload"]["classification_reason"] == "spoken_request_to_save_keep_note"


def test_pocket_api_sync_routes_keep_trigger_to_manual_followup_when_keep_scope_missing(monkeypatch) -> None:
    principal_id = "exec-product-pocket-sync-keep-followup"
    client = build_product_client(principal_id=principal_id)
    seed_product_state(client, principal_id=principal_id)

    monkeypatch.setattr(
        product_service,
        "_pocket_list_recordings",
        lambda *, limit, page=1: {
            "success": True,
            "data": [
                {"id": "trigger-keep-fallback-1", "title": "Pocket keep fallback command", "state": "completed"},
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
                "title": "Pocket keep fallback command",
                "state": "completed",
                "duration": 88.0,
                "language": "de",
                "recording_at": "2026-05-30T09:30:00Z",
                "created_at": "2026-05-30T09:30:10Z",
                "updated_at": "2026-05-30T09:30:20Z",
                "tags": ["memo"],
                "transcript": {
                    "text": "Assistent: setz Toilettenpapier auf meine Einkaufsliste.",
                    "segments": [{"start": 0.0, "end": 5.0, "text": "Assistent: setz Toilettenpapier auf meine Einkaufsliste."}],
                    "metadata": {"source": "api"},
                },
                "summarizations": {},
            },
        },
    )
    monkeypatch.setattr(
        product_service.ProductService,
        "_sync_pocket_audio_archive_index_to_teable",
        lambda self, *, principal_id, rows: {
            "status": "synced",
            "sync_attempted": True,
            "row_total": len(rows),
            "blocked_reason": "",
        },
    )
    monkeypatch.setattr(
        product_service.responses_upstream,
        "generate_text",
        lambda **kwargs: type(
            "UpstreamResultStub",
            (),
            {
                "text": json.dumps(
                    {
                        "action": "shopping_list_add",
                        "confidence": 0.93,
                        "reason": "spoken_request_to_add_item_to_shopping_list",
                        "params": {"item_text": "toilettenpapier"},
                    }
                )
            },
        )(),
    )
    monkeypatch.setattr(
        google_oauth_service,
        "create_google_keep_note",
        lambda **kwargs: (_ for _ in ()).throw(RuntimeError("google_keep_scope_missing")),
    )
    monkeypatch.setattr(
        product_service.ProductService,
        "_open_pocket_assistant_followup",
        lambda self, **kwargs: type("FollowupStub", (), {"task_id": "task-keep-1", "session_id": "sess-keep-1"})(),
    )

    synced = client.post("/app/api/signals/pocket/sync", params={"limit": 5})
    assert synced.status_code == 200
    body = synced.json()
    assert body["assistant_trigger_total"] == 1
    assert body["assistant_trigger_executed_total"] == 1
    assert body["assistant_trigger_blocked_total"] == 0

    product_events = client.get("/app/api/events", params={"channel": "product"})
    assert product_events.status_code == 200
    executed = next(
        item
        for item in product_events.json()["items"]
        if item["event_type"] == "pocket_assistant_command_executed"
        and item["payload"]["recording_id"] == "trigger-keep-fallback-1"
    )
    assert executed["payload"]["delivery_backend"] == "human_followup"
    assert executed["payload"]["delivery_status"] == "queued"
    assert executed["payload"]["delivery_result"]["reason"] == "google_keep_reconnect_required"


def test_pocket_api_sync_routes_gmail_trigger_to_manual_followup_by_default(monkeypatch) -> None:
    principal_id = "exec-product-pocket-sync-gmail-followup"
    client = build_product_client(principal_id=principal_id)
    seed_product_state(client, principal_id=principal_id)
    gmail_send_called = False

    monkeypatch.setattr(
        product_service,
        "_pocket_list_recordings",
        lambda *, limit, page=1: {
            "success": True,
            "data": [
                {"id": "trigger-gmail-1", "title": "Pocket gmail command", "state": "completed"},
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
                "title": "Pocket gmail command",
                "state": "completed",
                "duration": 93.0,
                "language": "de",
                "recording_at": "2026-05-30T10:00:00Z",
                "created_at": "2026-05-30T10:00:10Z",
                "updated_at": "2026-05-30T10:00:20Z",
                "tags": ["memo"],
                "transcript": {
                    "text": "Assistent: sende eine E-Mail an max@example.com mit dem Betreff Termin und dem Text ich komme spaeter.",
                    "segments": [{"start": 0.0, "end": 6.0, "text": "Assistent: sende eine E-Mail an max@example.com mit dem Betreff Termin und dem Text ich komme spaeter."}],
                    "metadata": {"source": "api"},
                },
                "summarizations": {},
            },
        },
    )
    monkeypatch.setattr(
        product_service.ProductService,
        "_sync_pocket_audio_archive_index_to_teable",
        lambda self, *, principal_id, rows: {
            "status": "synced",
            "sync_attempted": True,
            "row_total": len(rows),
            "blocked_reason": "",
        },
    )
    monkeypatch.setattr(
        product_service.responses_upstream,
        "generate_text",
        lambda **kwargs: type(
            "UpstreamResultStub",
            (),
            {
                "text": json.dumps(
                    {
                        "action": "gmail_send",
                        "confidence": 0.98,
                        "reason": "spoken_request_to_send_email",
                        "params": {
                            "recipient_email": "max@example.com",
                            "subject": "Termin",
                            "body_text": "Ich komme spaeter.",
                        },
                    }
                )
            },
        )(),
    )

    def _fake_send(**kwargs):  # type: ignore[no-untyped-def]
        nonlocal gmail_send_called
        gmail_send_called = True
        raise AssertionError("gmail send should not auto-execute by default")

    monkeypatch.setattr(google_oauth_service, "send_google_gmail_message", _fake_send)

    synced = client.post("/app/api/signals/pocket/sync", params={"limit": 5})
    assert synced.status_code == 200
    body = synced.json()
    assert body["assistant_trigger_total"] == 1
    assert body["assistant_trigger_executed_total"] == 1
    assert body["assistant_trigger_blocked_total"] == 0
    assert gmail_send_called is False

    product_events = client.get("/app/api/events", params={"channel": "product"})
    assert product_events.status_code == 200
    executed = next(
        item
        for item in product_events.json()["items"]
        if item["event_type"] == "pocket_assistant_command_executed"
        and item["payload"]["recording_id"] == "trigger-gmail-1"
    )
    assert executed["payload"]["delivery_backend"] == "human_followup"
    assert executed["payload"]["policy_reason"] == "action_policy_requires_manual_followup"


def test_pocket_api_sync_keeps_gmail_manual_without_explicit_dangerous_action_policy(monkeypatch) -> None:
    principal_id = "exec-product-pocket-sync-gmail-dangerous-policy"
    client = build_product_client(principal_id=principal_id)
    seed_product_state(client, principal_id=principal_id)
    gmail_send_called = False

    monkeypatch.setenv("EA_POCKET_ASSISTANT_AUTO_ACTIONS", "shopping_list_add,gmail_send,manual_followup,none")
    monkeypatch.delenv("EA_POCKET_ASSISTANT_DANGEROUS_AUTO_ACTIONS", raising=False)

    monkeypatch.setattr(
        product_service,
        "_pocket_list_recordings",
        lambda *, limit, page=1: {
            "success": True,
            "data": [
                {"id": "trigger-gmail-dangerous-1", "title": "Pocket gmail command", "state": "completed"},
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
                "title": "Pocket gmail command",
                "state": "completed",
                "duration": 93.0,
                "language": "de",
                "recording_at": "2026-05-30T10:00:00Z",
                "created_at": "2026-05-30T10:00:10Z",
                "updated_at": "2026-05-30T10:00:20Z",
                "tags": ["memo"],
                "transcript": {
                    "text": "Assistent: sende eine E-Mail an max@example.com mit dem Betreff Termin und dem Text ich komme spaeter.",
                    "segments": [{"start": 0.0, "end": 6.0, "text": "Assistent: sende eine E-Mail an max@example.com mit dem Betreff Termin und dem Text ich komme spaeter."}],
                    "metadata": {"source": "api"},
                },
                "summarizations": {},
            },
        },
    )
    monkeypatch.setattr(
        product_service.ProductService,
        "_sync_pocket_audio_archive_index_to_teable",
        lambda self, *, principal_id, rows: {
            "status": "synced",
            "sync_attempted": True,
            "row_total": len(rows),
            "blocked_reason": "",
        },
    )
    monkeypatch.setattr(
        product_service.responses_upstream,
        "generate_text",
        lambda **kwargs: type(
            "UpstreamResultStub",
            (),
            {
                "text": json.dumps(
                    {
                        "action": "gmail_send",
                        "confidence": 0.98,
                        "reason": "spoken_request_to_send_email",
                        "params": {
                            "recipient_email": "max@example.com",
                            "subject": "Termin",
                            "body_text": "Ich komme spaeter.",
                        },
                    }
                )
            },
        )(),
    )

    def _fake_send(**kwargs):  # type: ignore[no-untyped-def]
        nonlocal gmail_send_called
        gmail_send_called = True
        raise AssertionError("gmail send should not auto-execute without dangerous action policy")

    monkeypatch.setattr(google_oauth_service, "send_google_gmail_message", _fake_send)

    synced = client.post("/app/api/signals/pocket/sync", params={"limit": 5})
    assert synced.status_code == 200
    body = synced.json()
    assert body["assistant_trigger_total"] == 1
    assert body["assistant_trigger_executed_total"] == 1
    assert body["assistant_trigger_blocked_total"] == 0
    assert gmail_send_called is False

    product_events = client.get("/app/api/events", params={"channel": "product"})
    assert product_events.status_code == 200
    executed = next(
        item
        for item in product_events.json()["items"]
        if item["event_type"] == "pocket_assistant_command_executed"
        and item["payload"]["recording_id"] == "trigger-gmail-dangerous-1"
    )
    assert executed["payload"]["delivery_backend"] == "human_followup"
    assert executed["payload"]["policy_reason"] == "action_policy_requires_manual_followup"


def test_google_location_history_import_enriches_pocket_archive_search(monkeypatch, tmp_path) -> None:
    principal_id = "exec-product-pocket-location"
    client = build_product_client(principal_id=principal_id)
    seed_product_state(client, principal_id=principal_id)
    monkeypatch.setenv("EA_POCKET_AUDIO_ARCHIVE_ENABLED", "1")

    timeline_path = tmp_path / "Records.json"
    timeline_path.write_text(
        json.dumps(
            {
                "timelineObjects": [
                    {
                        "placeVisit": {
                            "location": {
                                "name": "Hanusch Krankenhaus",
                                "address": "Heinrich Collin-Strasse 30, Wien",
                                "latitudeE7": 481900000,
                                "longitudeE7": 163150000,
                            },
                            "duration": {
                                "startTimestamp": "2026-05-20T10:00:00Z",
                                "endTimestamp": "2026-05-20T11:30:00Z",
                            },
                        }
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        product_service,
        "_pocket_list_recordings",
        lambda *, limit, page=1: {
            "success": True,
            "data": [{"id": "hospital-1", "title": "Talk with father", "state": "completed"}],
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
                "title": "Talk with father",
                "state": "completed",
                "duration": 420.0,
                "language": "de",
                "recording_at": "2026-05-20T10:45:00Z",
                "created_at": "2026-05-20T10:45:10Z",
                "updated_at": "2026-05-20T10:46:10Z",
                "tags": ["hospital", "family"],
                "transcript": {
                    "text": "Mein Vater spricht über seinen Zustand und die Familie.",
                    "segments": [{"start": 0.0, "end": 5.0, "text": "Mein Vater spricht ueber seinen Zustand."}],
                    "metadata": {"source": "api"},
                },
                "summarizations": {
                    "summary-1": {
                        "id": "summary-1",
                        "v2": {"summary": {"markdown": "Gespräch mit dem Vater im Krankenhaus."}},
                    }
                },
            },
        },
    )
    monkeypatch.setattr(
        product_service.ProductService,
        "_archive_pocket_recording_audio",
        lambda self, *, principal_id, actor, payload: {
            "archive_status": "archived",
            "archive_reason": "",
            "archive_root": "/mnt/pcloud/EA/pocket-ai-audio",
            "archive_path": "/mnt/pcloud/EA/pocket-ai-audio/exec-product-pocket-location/2026/05/2026-05-20__hospital-1__talk-with-father.mp3",
            "archive_sha256": "abc123",
            "duration_seconds": 420.0,
            "min_duration_seconds": 60.0,
            "recording_id": "hospital-1",
            "title": "Talk with father",
        },
    )
    monkeypatch.setattr(
        product_service.ProductService,
        "_sync_pocket_audio_archive_index_to_teable",
        lambda self, *, principal_id, rows: {
            "status": "synced",
            "sync_attempted": True,
            "row_total": len(rows),
            "blocked_reason": "",
        },
    )

    imported = client.post("/app/api/signals/google/location-history/import", json={"path": str(timeline_path)})
    assert imported.status_code == 200
    assert imported.json()["imported_total"] == 1

    synced = client.post("/app/api/signals/pocket/sync", params={"limit": 5})
    assert synced.status_code == 200
    assert synced.json()["location_matched_total"] == 1

    searched = client.get(
        "/app/api/signals/pocket/recordings/search",
        params={"q": "Hanusch Krankenhaus Vater", "before": "2026-05-21", "limit": 5},
    )
    assert searched.status_code == 200
    body = searched.json()
    assert body["total"] == 1
    assert body["items"][0]["recording_id"] == "hospital-1"
    assert body["items"][0]["location_name"] == "Hanusch Krankenhaus"
    assert body["items"][0]["archive_path"].endswith("talk-with-father.mp3")


def test_google_location_history_import_supports_maps_myactivity_zip(monkeypatch, tmp_path) -> None:
    principal_id = "exec-product-pocket-location-myactivity"
    client = build_product_client(principal_id=principal_id)
    seed_product_state(client, principal_id=principal_id)
    monkeypatch.setenv("EA_POCKET_AUDIO_ARCHIVE_ENABLED", "1")

    archive_path = tmp_path / "google-maps-myactivity.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr(
            "Portability/My Activity/Maps/MyActivity.json",
            json.dumps(
                [
                    {
                        "header": "Maps",
                        "title": "Directions to Hanusch Spital, Heinrich-Collin-Straße, Vienna",
                        "titleUrl": "https://www.google.at/maps/dir//Klinik,+Heinrich-Collin-Stra%C3%9Fe+30,+1140+Wien/@48.1991917,16.3060776,14z/data=!3m1!4b1!4m7!4m6!1m0!1m2!1m1!1s0x476da739f700908b:0x4ad30a7262ba5eef!2m1!7e2",
                        "description": "Current location\nKlinik, Heinrich-Collin-Straße 30, 1140 Wien",
                        "time": "2026-05-22T15:11:05.637Z",
                        "products": ["Maps"],
                        "activityControls": ["Web & App Activity"],
                        "locationInfos": [
                            {
                                "name": "At this general area",
                                "url": "https://www.google.com/maps/@?api=1&map_action=map&center=48.205655,16.333764&zoom=12",
                                "source": "From your device",
                            }
                        ],
                    }
                ]
            ),
        )

    monkeypatch.setattr(
        product_service,
        "_pocket_list_recordings",
        lambda *, limit, page=1: {
            "success": True,
            "data": [{"id": "hospital-2", "title": "Talk with father", "state": "completed"}],
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
                "title": "Talk with father",
                "state": "completed",
                "duration": 420.0,
                "language": "de",
                "recording_at": "2026-05-22T15:28:13Z",
                "created_at": "2026-05-22T15:28:20Z",
                "updated_at": "2026-05-22T15:29:20Z",
                "tags": ["hospital", "family"],
                "transcript": {
                    "text": "Mein Vater spricht über seinen Zustand und die Familie.",
                    "segments": [{"start": 0.0, "end": 5.0, "text": "Mein Vater spricht ueber seinen Zustand."}],
                    "metadata": {"source": "api"},
                },
                "summarizations": {
                    "summary-1": {
                        "id": "summary-1",
                        "v2": {"summary": {"markdown": "Gespräch mit dem Vater im Hanusch Spital."}},
                    }
                },
            },
        },
    )
    monkeypatch.setattr(
        product_service.ProductService,
        "_archive_pocket_recording_audio",
        lambda self, *, principal_id, actor, payload: {
            "archive_status": "archived",
            "archive_reason": "",
            "archive_root": "/mnt/pcloud/EA/pocket-ai-audio",
            "archive_path": "/mnt/pcloud/EA/pocket-ai-audio/exec-product-pocket-location-myactivity/2026/05/2026-05-22__hospital-2__talk-with-father.mp3",
            "archive_sha256": "def456",
            "duration_seconds": 420.0,
            "min_duration_seconds": 60.0,
            "recording_id": "hospital-2",
            "title": "Talk with father",
        },
    )
    monkeypatch.setattr(
        product_service.ProductService,
        "_sync_pocket_audio_archive_index_to_teable",
        lambda self, *, principal_id, rows: {
            "status": "synced",
            "sync_attempted": True,
            "row_total": len(rows),
            "blocked_reason": "",
        },
    )

    imported = client.post("/app/api/signals/google/location-history/import", json={"path": str(archive_path)})
    assert imported.status_code == 200
    assert imported.json()["imported_total"] == 1

    synced = client.post("/app/api/signals/pocket/sync", params={"limit": 5})
    assert synced.status_code == 200
    assert synced.json()["location_matched_total"] == 1

    searched = client.get(
        "/app/api/signals/pocket/recordings/search",
        params={"q": "Hanusch Vater", "before": "2026-05-23", "limit": 5},
    )
    assert searched.status_code == 200
    body = searched.json()
    assert body["total"] == 1
    assert body["items"][0]["recording_id"] == "hospital-2"
    assert body["items"][0]["location_name"] == "Hanusch Spital"
    assert body["items"][0]["location_match_status"] in {"matched", "nearest"}
    assert "hanusch" in str(body["items"][0]["topic_keywords_csv"])
    assert "vater" in str(body["items"][0]["topic_keywords_csv"])


def test_google_location_history_import_reindexes_existing_pocket_archive_with_transcript(monkeypatch, tmp_path) -> None:
    principal_id = "local-user"
    client = build_product_client(principal_id=principal_id)
    seed_product_state(client, principal_id=principal_id)
    archive_root = tmp_path / "archive"
    monkeypatch.setattr(product_service, "_pocket_audio_archive_root", lambda: archive_root)

    archive_dir = archive_root / "local-user" / "2026" / "05"
    archive_dir.mkdir(parents=True)
    audio_path = archive_dir / "2026-05-20__hospital-reindex-1__talk-with-father.mp3"
    audio_path.write_bytes(b"audio")
    metadata_path = audio_path.with_suffix(".json")
    metadata_path.write_text(
        json.dumps(
            {
                "recording_id": "hospital-reindex-1",
                "title": "Talk with father",
                "principal_id": principal_id,
                "recording_at": "2026-05-20T10:45:00Z",
                "archive_path": str(audio_path),
                "archive_sha256": "abc123",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    service = ProductService(client.app.state.container)
    service._record_pocket_archive_index(
        principal_id=principal_id,
        recording_id="hospital-reindex-1",
        title="Talk with father",
        recording_at="2026-05-20T10:45:00Z",
        archive_result={
            "archive_status": "already_archived",
            "archive_path": str(audio_path),
            "archive_sha256": "abc123",
        },
        summary_markdown="Gespräch mit dem Vater im Krankenhaus.",
        transcript_text="Mein Vater spricht über seinen Zustand und die Familie.",
        transcript_excerpt="Mein Vater spricht über seinen Zustand.",
        location_match={"location_match_status": "unmatched", "location_match_reason": "no_timeline_window_match"},
        topic_keywords_csv="vater, krankenhaus",
        tags=["hospital", "family"],
    )
    service.ingest_office_signal(
        principal_id=principal_id,
        signal_type="audio_recording",
        channel="pocket",
        title="Talk with father",
        summary="Gespräch mit dem Vater im Krankenhaus.",
        text="Gespräch mit dem Vater im Krankenhaus.",
        source_ref="pocket-recording:hospital-reindex-1",
        external_id="hospital-reindex-1",
        counterparty="Pocket",
        payload={
            "recording_id": "hospital-reindex-1",
            "summary_markdown": "Gespräch mit dem Vater im Krankenhaus.",
            "transcript_excerpt": "Mein Vater spricht über seinen Zustand.",
        },
        actor="operator-office",
    )

    timeline_path = tmp_path / "Records.json"
    timeline_path.write_text(
        json.dumps(
            {
                "timelineObjects": [
                    {
                        "placeVisit": {
                            "location": {
                                "name": "Hanusch Krankenhaus",
                                "address": "Heinrich Collin-Strasse 30, Wien",
                                "latitudeE7": 481900000,
                                "longitudeE7": 163150000,
                            },
                            "duration": {
                                "startTimestamp": "2026-05-20T10:00:00Z",
                                "endTimestamp": "2026-05-20T11:30:00Z",
                            },
                        }
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    imported = service.import_google_location_history(
        principal_id=principal_id,
        actor="operator-office",
        path=str(timeline_path),
    )

    assert imported["imported_total"] == 1
    assert imported["matched_recording_total"] == 1
    assert imported["indexed_recording_total"] == 1
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    assert metadata["location_match"]["location_match_status"] == "matched"
    events = client.get(
        "/app/api/events",
        params={"channel": "product", "event_type": "pocket_recording_archive_indexed"},
    )
    assert events.status_code == 200
    reindexed = next(
        item
        for item in events.json()["items"]
        if item["payload"]["recording_id"] == "hospital-reindex-1"
        and item["payload"]["location_match_status"] == "matched"
    )
    assert reindexed["payload"]["transcript_text"] == "Mein Vater spricht über seinen Zustand und die Familie."
    assert reindexed["payload"]["location_name"] == "Hanusch Krankenhaus"


def test_pocket_recording_search_deliver_telegram_route_sends_best_match(monkeypatch) -> None:
    principal_id = "exec-product-pocket-search-telegram"
    client = build_product_client(principal_id=principal_id)
    seed_product_state(client, principal_id=principal_id)

    monkeypatch.setattr(
        ProductService,
        "search_pocket_recordings",
        lambda self, *, principal_id, actor, query="", before="", after="", limit=10: {
            "generated_at": "2026-05-30T00:00:00Z",
            "query": query,
            "before": before,
            "after": after,
            "total": 2,
            "items": [
                {
                    "recording_id": "rec-hanusch",
                    "title": "Hospital medical discussion and care",
                    "recording_at": "2026-05-22T15:28:13Z",
                    "archive_status": "already_archived",
                    "archive_path": "/mnt/pcloud/EA/pocket-ai-audio/x.mp3",
                    "archive_sha256": "abc",
                    "summary_markdown": "",
                    "transcript_excerpt": "",
                    "location_match_status": "nearest",
                    "location_match_reason": "nearest_timeline_window",
                    "location_name": "Hanusch Spital",
                    "location_address": "Hanusch Spital, Heinrich-Collin-Straße, Vienna",
                    "location_latitude": 48.1991917,
                    "location_longitude": 16.3060776,
                    "location_start_at": "2026-05-22T15:11:05.637000+00:00",
                    "location_end_at": "2026-05-22T15:11:05.637000+00:00",
                    "location_source": "google-location-history-export.zip",
                    "location_confidence": 0.9524,
                    "match_score": 3.0,
                }
            ],
        },
    )
    monkeypatch.setattr(
        ProductService,
        "deliver_pocket_recording_to_telegram",
        lambda self, *, principal_id, actor, recording_id: {
            "recording_id": recording_id,
            "title": "Hospital medical discussion and care",
            "telegram_delivery_status": "sent",
            "telegram_delivery_error": "",
            "telegram_message_ids": ["1315"],
            "telegram_chat_ref": "1354554303",
            "audio_download_url": "https://example.invalid/audio.mp3",
            "audio_expires_at": "2026-05-30T01:00:00Z",
        },
    )

    delivered = client.post(
        "/app/api/signals/pocket/recordings/deliver-telegram",
        params={"q": "Hanusch Vater", "before": "2026-05-23"},
    )
    assert delivered.status_code == 200
    body = delivered.json()
    assert body["recording_id"] == "rec-hanusch"
    assert body["matched_total"] == 2
    assert body["location_name"] == "Hanusch Spital"
    assert body["telegram_message_ids"] == ["1315"]


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


def test_pocket_api_sync_records_preference_profile_evidence_from_housing_conversations(monkeypatch) -> None:
    principal_id = "exec-product-pocket-preference-profile"
    client = build_product_client(principal_id=principal_id)
    seed_product_state(client, principal_id=principal_id)
    created = client.post(
        "/app/api/people/self/preference-profile",
        json={
            "display_name": "Tibor",
            "consent_mode": "behavioral_learning",
            "learning_enabled": True,
        },
    )
    assert created.status_code == 200

    monkeypatch.setattr(
        product_service,
        "_pocket_list_recordings",
        lambda *, limit, page=1: {
            "success": True,
            "data": [
                {
                    "id": "housing-1",
                    "title": "Willhaben shortlist review",
                    "state": "completed",
                    "created_at": "2026-05-01T08:30:00Z",
                    "updated_at": "2026-05-01T08:31:00Z",
                    "recording_at": "2026-05-01T08:30:00Z",
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
                "title": "Willhaben shortlist review",
                "state": "completed",
                "duration": 145.0,
                "language": "en",
                "recording_at": "2026-05-01T08:30:00Z",
                "created_at": "2026-05-01T08:30:00Z",
                "updated_at": "2026-05-01T08:31:00Z",
                "tags": ["housing", "willhaben", "family"],
                "transcript": {
                    "text": (
                        "Compare the Willhaben apartment options side by side. "
                        "We need a proper floor plan and ideally a 360 panorama for remote review. "
                        "A balcony would help, a lift would be better for daily family use, and please avoid Gasheizung. "
                        "Send me the written summary after the shortlist review."
                    ),
                    "segments": [{"start": 0.0, "end": 6.0, "text": "Compare the Willhaben apartment options."}],
                    "metadata": {"source": "api"},
                },
                "summarizations": {
                    "summary-housing": {
                        "id": "summary-housing",
                        "v2": {
                            "summary": {
                                "markdown": (
                                    "Compare shortlisted Willhaben apartments, require a floor plan and 360 tour, "
                                    "prefer balcony and lift, avoid Gasheizung, and send a written summary."
                                )
                            }
                        },
                    }
                },
            },
        },
    )

    synced = client.post("/app/api/signals/pocket/sync", params={"limit": 5})
    assert synced.status_code == 200
    synced_body = synced.json()
    assert synced_body["preference_evidence_total"] == 1
    assert synced_body["preference_evidence_applied_total"] >= 4

    bundle = client.get("/app/api/people/self/preference-profile")
    assert bundle.status_code == 200
    body = bundle.json()
    nodes_by_key = {item["key"]: item for item in body["preference_nodes"]}
    assert nodes_by_key["requires_floorplan_for_remote_review"]["domain"] == "willhaben"
    assert nodes_by_key["prefer_360_for_remote_review"]["value_json"] is True
    assert nodes_by_key["prefer_balcony"]["value_json"] is True
    assert nodes_by_key["prefer_lift"]["value_json"] is True
    assert "Gasheizung" in (nodes_by_key["avoid_heating_types"]["value_json"] or [])
    assert nodes_by_key["prefers_written_follow_up"]["domain"] == "general"
    assert nodes_by_key["needs_side_by_side_comparison"]["domain"] == "general"
    assert body["recent_evidence_events"][0]["domain"] == "conversation"


def test_pocket_api_sync_can_use_onemin_audio_fallback_for_profile_evidence(monkeypatch) -> None:
    principal_id = "exec-product-pocket-preference-profile-onemin"
    client = build_product_client(principal_id=principal_id)
    seed_product_state(client, principal_id=principal_id)
    created = client.post(
        "/app/api/people/self/preference-profile",
        json={
            "display_name": "Tibor",
            "consent_mode": "behavioral_learning",
            "learning_enabled": True,
        },
    )
    assert created.status_code == 200

    monkeypatch.setattr(
        product_service,
        "_pocket_list_recordings",
        lambda *, limit, page=1: {
            "success": True,
            "data": [
                {
                    "id": "housing-onemin-1",
                    "title": "Willhaben shortlist review",
                    "state": "completed",
                    "created_at": "2026-05-01T08:30:00Z",
                    "updated_at": "2026-05-01T08:31:00Z",
                    "recording_at": "2026-05-01T08:30:00Z",
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
                "title": "Willhaben shortlist review",
                "state": "completed",
                "duration": 90.0,
                "language": "en",
                "recording_at": "2026-05-01T08:30:00Z",
                "created_at": "2026-05-01T08:30:00Z",
                "updated_at": "2026-05-01T08:31:00Z",
                "tags": ["housing", "willhaben"],
                "transcript": {
                    "text": "Okay yes.",
                    "segments": [],
                    "metadata": {"source": "partial"},
                },
                "summarizations": {},
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
    monkeypatch.setattr(product_service, "_pocket_audio_transcribe_webhook_url", lambda: "")
    monkeypatch.setattr(product_service, "_pocket_onemin_api_keys", lambda: ("onemin-live-key",))
    monkeypatch.setattr(
        product_service,
        "_pocket_retranscribe_with_onemin",
        lambda **kwargs: {
            "transcript_text": "Need a proper floor plan, 360 tour, lift, and avoid Gasheizung.",
            "transcript_segment_count": 1,
            "transcript_metadata": {"source": "ea_audio_fallback", "transcriber": "1min.ai/whisper-1"},
        },
    )

    synced = client.post("/app/api/signals/pocket/sync", params={"limit": 5})
    assert synced.status_code == 200
    synced_body = synced.json()
    assert synced_body["preference_evidence_total"] == 1
    assert synced_body["preference_evidence_applied_total"] >= 3

    events = client.get("/app/api/events", params={"channel": "pocket"})
    assert events.status_code == 200
    event = next(item for item in events.json()["items"] if item["source_id"] == "pocket-recording:housing-onemin-1")
    assert event["payload"]["transcript_quality_status"] in {"good", "usable"}
    assert event["payload"]["retranscription_status"] == "applied"

    bundle = client.get("/app/api/people/self/preference-profile")
    assert bundle.status_code == 200
    nodes_by_key = {item["key"]: item for item in bundle.json()["preference_nodes"]}
    assert nodes_by_key["requires_floorplan_for_remote_review"]["value_json"] is True
    assert nodes_by_key["prefer_360_for_remote_review"]["value_json"] is True
    assert nodes_by_key["prefer_lift"]["value_json"] is True


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


def test_pocket_api_backfill_limit_zero_drains_all_pages(monkeypatch) -> None:
    principal_id = "exec-product-pocket-backfill-all"
    client = build_product_client(principal_id=principal_id)
    seed_product_state(client, principal_id=principal_id)
    seen_pages: list[int] = []

    def _list_recordings(*, limit, page=1):
        seen_pages.append(page)
        assert limit == 25
        if page == 1:
            return {
                "success": True,
                "data": [
                    {
                        "id": "all-1",
                        "title": "Pocket first item",
                        "state": "completed",
                        "created_at": "2026-05-01T09:10:00Z",
                        "updated_at": "2026-05-01T09:11:00Z",
                        "recording_at": "2026-05-01T09:10:00Z",
                    }
                ],
                "pagination": {"total": 3, "has_more": True},
            }
        if page == 2:
            return {
                "success": True,
                "data": [
                    {
                        "id": "all-2",
                        "title": "Pocket second item",
                        "state": "completed",
                        "created_at": "2026-05-01T09:00:00Z",
                        "updated_at": "2026-05-01T09:01:00Z",
                        "recording_at": "2026-05-01T09:00:00Z",
                    },
                    {
                        "id": "all-3",
                        "title": "Pocket third item",
                        "state": "completed",
                        "created_at": "2026-05-01T08:50:00Z",
                        "updated_at": "2026-05-01T08:51:00Z",
                        "recording_at": "2026-05-01T08:50:00Z",
                    },
                ],
                "pagination": {"total": 3, "has_more": False},
            }
        return {"success": True, "data": [], "pagination": {"total": 3, "has_more": False}}

    def _detail(recording_id: str):
        return {
            "success": True,
            "data": {
                "id": recording_id,
                "title": f"Pocket {recording_id}",
                "state": "completed",
                "duration": 180.0,
                "language": "en",
                "recording_at": "2026-05-01T09:00:00Z",
                "created_at": "2026-05-01T09:00:10Z",
                "updated_at": "2026-05-01T09:01:00Z",
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

    backfill = client.post("/app/api/signals/pocket/backfill", params={"limit": 0})
    assert backfill.status_code == 200
    body = backfill.json()
    assert seen_pages == [1, 2]
    assert body["mode"] == "backfill"
    assert body["cursor_used"] is False
    assert body["cursor_persisted"] is False
    assert body["recording_total"] == 3
    assert body["total"] == 3
    assert body["scan_truncated"] is False


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
    assert body["transcript_quality_status"] in {"good", "usable"}
    assert body["retranscription_attempted"] is False


def test_pocket_recording_detail_uses_audio_fallback_transcription_when_transcript_is_weak(monkeypatch) -> None:
    principal_id = "exec-product-pocket-detail-fallback"
    client = build_product_client(principal_id=principal_id)
    seed_product_state(client, principal_id=principal_id)

    monkeypatch.setattr(
        product_service,
        "_pocket_get_recording_details",
        lambda recording_id: {
            "success": True,
            "data": {
                "id": recording_id,
                "title": "Weak pocket detail",
                "state": "completed",
                "duration": 20.0,
                "language": "en",
                "recording_at": "2026-05-01T07:00:00Z",
                "created_at": "2026-05-01T07:00:10Z",
                "updated_at": "2026-05-01T07:00:20Z",
                "tags": ["detail"],
                "transcript": {
                    "text": "Okay yes.",
                    "segments": [],
                    "metadata": {"source": "partial"},
                },
                "summarizations": {},
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
    monkeypatch.setattr(product_service, "_pocket_audio_transcribe_webhook_url", lambda: "https://transcriber.example/pocket")
    monkeypatch.setattr(
        product_service,
        "_pocket_retranscribe_from_audio_url",
        lambda **kwargs: {
            "transcript_text": "Compare the shortlist and send the written summary.",
            "transcript_segment_count": 1,
            "transcript_metadata": {"source": "ea_audio_fallback", "transcriber": "test"},
        },
    )

    detail = client.get("/app/api/signals/pocket/recordings/rec-weak")
    assert detail.status_code == 200
    body = detail.json()
    assert body["transcript_text"] == "Compare the shortlist and send the written summary."
    assert body["retranscription_attempted"] is True
    assert body["retranscription_status"] == "applied"
    assert body["transcript_quality_status"] in {"good", "usable"}
    assert body["audio_download_url"] == "https://audio.example/rec-weak.mp3"


def test_pocket_recording_detail_can_force_audio_fallback_even_when_transcript_is_usable(monkeypatch) -> None:
    principal_id = "exec-product-pocket-detail-force-fallback"
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
                "duration": 35.0,
                "language": "en",
                "recording_at": "2026-05-01T07:00:00Z",
                "created_at": "2026-05-01T07:00:10Z",
                "updated_at": "2026-05-01T07:00:20Z",
                "tags": ["detail"],
                "transcript": {
                    "text": "Transcript body with enough detail to be usable.",
                    "segments": [{"start": 0.0, "end": 1.0, "text": "Transcript body with enough detail to be usable."}],
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
    monkeypatch.setattr(product_service, "_pocket_audio_transcribe_webhook_url", lambda: "https://transcriber.example/pocket")
    monkeypatch.setattr(
        product_service,
        "_pocket_retranscribe_from_audio_url",
        lambda **kwargs: {
            "transcript_text": "Refined transcript from audio fallback.",
            "transcript_segment_count": 1,
            "transcript_metadata": {"source": "ea_audio_fallback", "transcriber": "test"},
        },
    )

    detail = client.get("/app/api/signals/pocket/recordings/rec-force", params={"prefer_audio_fallback": "true"})
    assert detail.status_code == 200
    body = detail.json()
    assert body["retranscription_attempted"] is True
    assert body["retranscription_status"] == "applied"
    assert body["transcript_text"] == "Refined transcript from audio fallback."


def test_pocket_recording_detail_uses_onemin_audio_fallback_when_webhook_is_unset(monkeypatch) -> None:
    principal_id = "exec-product-pocket-detail-onemin-fallback"
    client = build_product_client(principal_id=principal_id)
    seed_product_state(client, principal_id=principal_id)

    monkeypatch.setattr(
        product_service,
        "_pocket_get_recording_details",
        lambda recording_id: {
            "success": True,
            "data": {
                "id": recording_id,
                "title": "Weak pocket detail",
                "state": "completed",
                "duration": 22.0,
                "language": "en",
                "recording_at": "2026-05-01T07:00:00Z",
                "created_at": "2026-05-01T07:00:10Z",
                "updated_at": "2026-05-01T07:00:20Z",
                "tags": ["detail"],
                "transcript": {
                    "text": "Okay yes.",
                    "segments": [],
                    "metadata": {"source": "partial"},
                },
                "summarizations": {},
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
    monkeypatch.setattr(product_service, "_pocket_audio_transcribe_webhook_url", lambda: "")
    monkeypatch.setattr(product_service, "_pocket_onemin_api_keys", lambda: ("onemin-live-key",))
    monkeypatch.setattr(
        product_service,
        "_pocket_retranscribe_with_onemin",
        lambda **kwargs: {
            "transcript_text": "Take the apartment with the lift and compare it to the shortlist.",
            "transcript_segment_count": 2,
            "transcript_metadata": {"source": "ea_audio_fallback", "transcriber": "1min.ai/whisper-1"},
        },
    )

    detail = client.get("/app/api/signals/pocket/recordings/rec-onemin")
    assert detail.status_code == 200
    body = detail.json()
    assert body["retranscription_attempted"] is True
    assert body["retranscription_status"] == "applied"
    assert body["transcript_text"] == "Take the apartment with the lift and compare it to the shortlist."
    assert body["transcript_metadata"]["transcriber"] == "1min.ai/whisper-1"


def test_pocket_recording_retranscribe_route_forces_fallback_and_records_event(monkeypatch) -> None:
    principal_id = "exec-product-pocket-retranscribe-route"
    client = build_product_client(principal_id=principal_id)
    seed_product_state(client, principal_id=principal_id)
    created = client.post(
        "/app/api/people/self/preference-profile",
        json={
            "display_name": "Tibor",
            "consent_mode": "behavioral_learning",
            "learning_enabled": True,
        },
    )
    assert created.status_code == 200

    monkeypatch.setattr(
        product_service,
        "_pocket_get_recording_details",
        lambda recording_id: {
            "success": True,
            "data": {
                "id": recording_id,
                "title": "Weak pocket detail",
                "state": "completed",
                "duration": 22.0,
                "language": "en",
                "recording_at": "2026-05-01T07:00:00Z",
                "created_at": "2026-05-01T07:00:10Z",
                "updated_at": "2026-05-01T07:00:20Z",
                "tags": ["detail"],
                "transcript": {
                    "text": "Short note.",
                    "segments": [],
                    "metadata": {"source": "partial"},
                },
                "summarizations": {},
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
    monkeypatch.setattr(product_service, "_pocket_audio_transcribe_webhook_url", lambda: "")
    monkeypatch.setattr(product_service, "_pocket_onemin_api_keys", lambda: ("onemin-live-key",))
    monkeypatch.setattr(
        product_service,
        "_pocket_retranscribe_with_onemin",
        lambda **kwargs: {
            "transcript_text": (
                "Compare the flats side by side. "
                "We need a proper floor plan and ideally a 360 panorama for remote review. "
                "A lift would be better for daily family use, and send the written summary."
            ),
            "transcript_segment_count": 1,
            "transcript_metadata": {"source": "ea_audio_fallback", "transcriber": "1min.ai/whisper-1"},
        },
    )

    detail = client.post("/app/api/signals/pocket/recordings/rec-retranscribe/retranscribe")
    assert detail.status_code == 200
    body = detail.json()
    assert body["retranscription_attempted"] is True
    assert body["retranscription_status"] == "applied"
    assert "proper floor plan" in body["transcript_text"]
    assert body["preference_evidence_recorded"] is True
    assert body["preference_evidence_applied_total"] >= 0

    events = client.get("/app/api/events", params={"channel": "product"})
    assert events.status_code == 200
    event = next(item for item in events.json()["items"] if item["event_type"] == "pocket_recording_retranscribed")
    assert event["source_id"] == "pocket-recording:rec-retranscribe"
    assert event["payload"]["status"] == "applied"
    assert event["payload"]["transcriber"] == "1min.ai/whisper-1"
    assert event["payload"]["prefer_audio_fallback"] is True

    bundle = client.get("/app/api/people/self/preference-profile")
    assert bundle.status_code == 200
    nodes_by_key = {item["key"]: item for item in bundle.json()["preference_nodes"]}
    assert nodes_by_key["requires_floorplan_for_remote_review"]["value_json"] is True
    assert nodes_by_key["prefer_360_for_remote_review"]["value_json"] is True
    assert nodes_by_key["prefer_lift"]["value_json"] is True
    assert nodes_by_key["prefers_written_follow_up"]["value_json"] is True
    assert nodes_by_key["needs_side_by_side_comparison"]["value_json"] is True


def test_pocket_recording_deliver_telegram_route_sends_audio_and_records_event(monkeypatch) -> None:
    principal_id = "exec-product-pocket-telegram-delivery"
    client = build_product_client(principal_id=principal_id)
    seed_product_state(client, principal_id=principal_id)

    monkeypatch.setattr(
        product_service,
        "_pocket_get_recording_details",
        lambda recording_id: {
            "success": True,
            "data": {
                "id": recording_id,
                "title": "Hospital medical discussion and care",
                "state": "completed",
                "duration": 22.0,
                "language": "en",
                "recording_at": "2026-05-01T07:00:00Z",
                "created_at": "2026-05-01T07:00:10Z",
                "updated_at": "2026-05-01T07:00:20Z",
                "tags": ["hospital"],
                "transcript": {
                    "text": "Please send me the earlier hospital recording.",
                    "segments": [{"text": "Please send me the earlier hospital recording."}],
                    "metadata": {"source": "api"},
                },
                "summarizations": {},
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
    monkeypatch.setattr(
        product_service,
        "send_telegram_audio_for_principal",
        lambda tool_runtime, *, principal_id, audio_ref, caption="": SimpleNamespace(
            chat_id="1354554303",
            bot_key="default",
            bot_handle="tibor_concierge_bot",
            message_ids=("tg-audio-1",),
        ),
    )

    delivered = client.post("/app/api/signals/pocket/recordings/rec-telegram/deliver-telegram")
    assert delivered.status_code == 200
    body = delivered.json()
    assert body["recording_id"] == "rec-telegram"
    assert body["telegram_delivery_status"] == "sent"
    assert body["telegram_message_ids"] == ["tg-audio-1"]
    assert body["telegram_chat_ref"] == "1354554303"
    assert body["audio_download_url"] == "https://audio.example/rec-telegram.mp3"

    events = client.get("/app/api/events", params={"channel": "product"})
    assert events.status_code == 200
    event = next(item for item in events.json()["items"] if item["event_type"] == "pocket_recording_telegram_sent")
    assert event["source_id"] == "pocket-recording:rec-telegram"
    assert event["payload"]["telegram_chat_ref"] == "1354554303"
    assert event["payload"]["telegram_message_ids"] == ["tg-audio-1"]


def test_pocket_recording_enhance_audio_keeps_original_and_records_policy(monkeypatch, tmp_path) -> None:
    principal_id = "exec-product-pocket-audio-enhance"
    client = build_product_client(principal_id=principal_id)
    seed_product_state(client, principal_id=principal_id)
    original_path = tmp_path / "recording.mp3"
    original_path.write_bytes(b"original-audio")
    original_path.with_suffix(".json").write_text(
        json.dumps({"recording_id": "rec-enhance", "archive_path": str(original_path), "archive_sha256": "orig-sha"})
        + "\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(
        product_service,
        "_pocket_get_recording_details",
        lambda recording_id: {
            "success": True,
            "data": {
                "id": recording_id,
                "title": "Hospital medical discussion and care",
                "state": "completed",
                "duration": 120.0,
                "language": "de",
                "recording_at": "2026-05-01T07:00:00Z",
                "created_at": "2026-05-01T07:00:10Z",
                "updated_at": "2026-05-01T07:00:20Z",
                "tags": ["hospital"],
                "transcript": {"text": "Bitte verbessere die Aufnahme.", "segments": [], "metadata": {"source": "api"}},
                "summarizations": {},
            },
        },
    )
    monkeypatch.setattr(
        product_service,
        "_pocket_get_audio_download_url",
        lambda recording_id: {
            "success": True,
            "data": {"signed_url": f"https://audio.example/{recording_id}.mp3"},
        },
    )
    monkeypatch.setattr(
        product_service.ProductService,
        "_archive_pocket_recording_audio",
        lambda self, *, principal_id, actor, payload: {
            "archive_status": "already_archived",
            "archive_path": str(original_path),
            "archive_sha256": "orig-sha",
            "recording_id": "rec-enhance",
            "title": "Hospital medical discussion and care",
        },
    )
    monkeypatch.setattr(product_service, "_pocket_audio_enhance_ffmpeg_bin", lambda: "/usr/bin/ffmpeg")
    monkeypatch.setattr(
        product_service,
        "_pocket_audio_probe_duration_seconds",
        lambda path: 120.0 if Path(path) == original_path else 119.5,
    )

    def _fake_run(command, **kwargs):
        Path(command[-1]).write_bytes(b"enhanced-audio")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(product_service.subprocess, "run", _fake_run)

    enhanced = client.post("/app/api/signals/pocket/recordings/rec-enhance/enhance-audio")
    assert enhanced.status_code == 200
    body = enhanced.json()
    assert body["enhancement_status"] == "enhanced"
    assert body["original_audio_path"] == str(original_path)
    assert body["enhanced_audio_path"].endswith("__enhanced.mp3")
    assert Path(body["enhanced_audio_path"]).read_bytes() == b"enhanced-audio"
    assert not any("stop_periods" in item for item in body["filters_applied"])
    assert body["voice_profile_status"] == "not_supported"
    assert body["voice_profile_reason"] == "voice_cloning_real_person_not_supported"
    original_metadata = json.loads(original_path.with_suffix(".json").read_text(encoding="utf-8"))
    assert original_metadata["enhanced_audio"]["enhanced_audio_path"] == body["enhanced_audio_path"]

    events = client.get("/app/api/events", params={"channel": "product", "event_type": "pocket_recording_audio_enhanced"})
    assert events.status_code == 200
    event = next(item for item in events.json()["items"] if item["source_id"] == "pocket-recording:rec-enhance")
    assert event["payload"]["policy"]["original_preserved"] is True
    assert event["payload"]["policy"]["voice_cloning"] == "not_supported"


def test_pocket_recording_deliver_telegram_route_falls_back_to_local_upload_when_remote_audio_is_unreachable(monkeypatch) -> None:
    principal_id = "exec-product-pocket-telegram-delivery-fallback"
    client = build_product_client(principal_id=principal_id)
    seed_product_state(client, principal_id=principal_id)

    monkeypatch.setattr(
        product_service,
        "_pocket_get_recording_details",
        lambda recording_id: {
            "success": True,
            "data": {
                "id": recording_id,
                "title": "Hospital medical discussion and care",
                "state": "completed",
                "duration": 22.0,
                "language": "en",
                "recording_at": "2026-05-01T07:00:00Z",
                "created_at": "2026-05-01T07:00:10Z",
                "updated_at": "2026-05-01T07:00:20Z",
                "tags": ["hospital"],
                "transcript": {"text": "Please send me the earlier hospital recording.", "segments": [], "metadata": {"source": "api"}},
                "summarizations": {},
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

    class _FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return b"fake-mp3-bytes"

    monkeypatch.setattr(product_service.urllib.request, "urlopen", lambda *args, **kwargs: _FakeResponse())
    seen: list[str] = []

    def _fake_send(tool_runtime, *, principal_id, audio_ref, caption=""):
        seen.append(audio_ref)
        if audio_ref.startswith("https://"):
            raise RuntimeError("telegram_audio_unreachable")
        assert Path(audio_ref).is_file()
        return SimpleNamespace(
            chat_id="1354554303",
            bot_key="default",
            bot_handle="tibor_concierge_bot",
            message_ids=("tg-audio-2",),
        )

    monkeypatch.setattr(product_service, "send_telegram_audio_for_principal", _fake_send)

    delivered = client.post("/app/api/signals/pocket/recordings/rec-telegram-fallback/deliver-telegram")
    assert delivered.status_code == 200
    body = delivered.json()
    assert body["telegram_delivery_status"] == "sent"
    assert body["telegram_message_ids"] == ["tg-audio-2"]
    assert seen[0] == "https://audio.example/rec-telegram-fallback.mp3"
    assert len(seen) == 2
    assert seen[1].startswith("/tmp/")


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


def test_google_signal_sync_saves_pdf_attachments_to_onedrive_and_enrolls_onedrive_answerly(
    monkeypatch,
    tmp_path: Path,
) -> None:
    principal_id = "exec-product-google-pdf-import"
    client = build_product_client(principal_id=principal_id)

    monkeypatch.setenv("EA_ONEDRIVE_ATTACHMENT_ROOT", str(tmp_path))
    monkeypatch.setenv("EA_PUBLIC_APP_BASE_URL", "https://myexternalbrain.com")
    monkeypatch.setenv("EA_ANSWERLY_AUTO_IMPORT_GMAIL_PDFS", "1")
    monkeypatch.setenv("EA_ANSWERLY_ONEDRIVE_API_KEY", "onedrive-key")
    monkeypatch.setenv("EA_ANSWERLY_ONEDRIVE_TRAINING_ID", "onedrive-training")
    monkeypatch.setenv("EA_ANSWERLY_ONEDRIVE_LABEL", "OneDrive documents")
    monkeypatch.setenv("EA_ANSWERLY_SHAREONE_API_KEY", "shareone-key")
    monkeypatch.setenv("EA_ANSWERLY_SHAREONE_AGENT_ID", "shareone-agent")

    captured_answerly: list[dict[str, object]] = []

    def _fake_create_onedrive_data_item(self, *, config, source_url):  # type: ignore[no-untyped-def]
        captured_answerly.append({"config": dict(config), "source_url": source_url})
        return {"id": "answerly-data-item-1"}

    monkeypatch.setattr(ProductService, "_answerly_create_onedrive_data_item", _fake_create_onedrive_data_item)
    monkeypatch.setattr(
        google_oauth_service,
        "list_recent_workspace_signals",
        lambda **_: google_oauth_service.GoogleWorkspaceSignalSync(
            account_email="tibor.girschele@gmail.com",
            account_emails=("tibor.girschele@gmail.com",),
            granted_scopes=(google_oauth_service.GOOGLE_SCOPE_GMAIL_MODIFY,),
            signals=(
                google_oauth_service.GoogleWorkspaceSignal(
                    signal_type="email_thread",
                    channel="gmail",
                    title="Noah birth certificate",
                    summary="Birth certificate attached as PDF.",
                    text="Birth certificate attached as PDF.",
                    source_ref="gmail-thread:tibor.girschele@gmail.com:pdf-import-1",
                    external_id="gmail-message:tibor.girschele@gmail.com:pdf-import-1",
                    counterparty="Magistrat",
                    due_at=None,
                    payload={
                        "thread_id": "pdf-import-1",
                        "message_id": "msg-pdf-import-1",
                        "account_email": "tibor.girschele@gmail.com",
                    },
                    attachments=(
                        google_oauth_service.GoogleWorkspaceAttachment(
                            attachment_id="att-pdf-1",
                            filename="Noah Birth Certificate.pdf",
                            mime_type="application/pdf",
                            part_id="1",
                            size_bytes=18,
                            content_bytes=b"%PDF-1.7 birth-cert",
                        ),
                    ),
                ),
            ),
        ),
    )

    synced = client.post("/app/api/signals/google/sync", params={"email_limit": 1, "calendar_limit": 0})
    assert synced.status_code == 200
    body = synced.json()
    gmail_item = body["items"][0]
    assert gmail_item["attachment_imports"]
    imported = gmail_item["attachment_imports"][0]
    assert imported["filename"].endswith(".pdf")
    assert imported["enrolled"] is True
    assert imported["answerly_data_item_id"] == "answerly-data-item-1"
    assert Path(imported["path"]).exists()
    assert Path(imported["path"]).read_bytes() == b"%PDF-1.7 birth-cert"

    assert captured_answerly
    assert captured_answerly[0]["config"]["training_id"] == "onedrive-training"
    assert captured_answerly[0]["config"]["label"] == "OneDrive documents"
    assert "shareone" not in json.dumps(captured_answerly[0]).lower()
    assert str(captured_answerly[0]["source_url"]).startswith("https://myexternalbrain.com/documents/onedrive-mail/")

    download_path = urlparse(str(captured_answerly[0]["source_url"])).path
    download = client.get(download_path)
    assert download.status_code == 200
    assert download.content == b"%PDF-1.7 birth-cert"
    assert download.headers["content-type"].startswith("application/pdf")

    events = client.get("/app/api/events")
    assert events.status_code == 200
    event_types = {item["event_type"] for item in events.json()["items"]}
    assert "gmail_pdf_attachment_saved_to_onedrive" in event_types
    assert "answerly_onedrive_pdf_enrolled" in event_types


def test_google_signal_sync_marks_pdf_attachment_pending_when_answerly_training_is_not_ready(
    monkeypatch,
    tmp_path: Path,
) -> None:
    principal_id = "exec-product-google-pdf-import-pending"
    client = build_product_client(principal_id=principal_id)

    monkeypatch.setenv("EA_ONEDRIVE_ATTACHMENT_ROOT", str(tmp_path))
    monkeypatch.setenv("EA_PUBLIC_APP_BASE_URL", "https://myexternalbrain.com")
    monkeypatch.setenv("EA_ANSWERLY_AUTO_IMPORT_GMAIL_PDFS", "1")
    monkeypatch.setenv("EA_ANSWERLY_ONEDRIVE_API_KEY", "onedrive-key")
    monkeypatch.setenv("EA_ANSWERLY_ONEDRIVE_WORKSPACE_ID", "answerly-workspace-1")
    monkeypatch.delenv("EA_ANSWERLY_ONEDRIVE_TRAINING_ID", raising=False)

    monkeypatch.setattr(
        google_oauth_service,
        "list_recent_workspace_signals",
        lambda **_: google_oauth_service.GoogleWorkspaceSignalSync(
            account_email="tibor.girschele@gmail.com",
            account_emails=("tibor.girschele@gmail.com",),
            granted_scopes=(google_oauth_service.GOOGLE_SCOPE_GMAIL_MODIFY,),
            signals=(
                google_oauth_service.GoogleWorkspaceSignal(
                    signal_type="email_thread",
                    channel="gmail",
                    title="Medication plan",
                    summary="Medication PDF attached.",
                    text="Medication PDF attached.",
                    source_ref="gmail-thread:tibor.girschele@gmail.com:pdf-import-pending-1",
                    external_id="gmail-message:tibor.girschele@gmail.com:pdf-import-pending-1",
                    counterparty="Apotheke",
                    due_at=None,
                    payload={
                        "thread_id": "pdf-import-pending-1",
                        "message_id": "msg-pdf-import-pending-1",
                        "account_email": "tibor.girschele@gmail.com",
                    },
                    attachments=(
                        google_oauth_service.GoogleWorkspaceAttachment(
                            attachment_id="att-pdf-pending-1",
                            filename="Medication Plan.pdf",
                            mime_type="application/pdf",
                            part_id="1",
                            size_bytes=16,
                            content_bytes=b"%PDF-1.7 meds",
                        ),
                    ),
                ),
            ),
        ),
    )

    synced = client.post("/app/api/signals/google/sync", params={"email_limit": 1, "calendar_limit": 0})
    assert synced.status_code == 200
    imported = synced.json()["items"][0]["attachment_imports"][0]
    assert imported["enrolled"] is False
    assert imported["pending_answerly_import"] is True
    assert imported["answerly_error"] == "answerly_training_id_missing"

    events = client.get("/app/api/events")
    assert events.status_code == 200
    event_types = {item["event_type"] for item in events.json()["items"]}
    assert "gmail_pdf_attachment_saved_to_onedrive" in event_types
    assert "answerly_onedrive_pdf_import_pending" in event_types


def test_google_willhaben_signal_sync_targets_secondary_account_and_auto_sends_to_tibor(monkeypatch) -> None:
    from app.domain.models import Artifact

    monkeypatch.setenv("EA_WILLHABEN_SEARCH_AGENT_AUTO_CREATE_PROPERTY_TOUR", "1")
    monkeypatch.setenv("EA_WILLHABEN_PROPERTY_TOUR_REQUIRE_360", "0")
    monkeypatch.setenv("EA_WILLHABEN_PROPERTY_TOUR_DEFAULT_RECIPIENT_EMAIL", "tibor.girschele@gmail.com")
    monkeypatch.setenv(
        "EA_WILLHABEN_PROPERTY_TOUR_RECIPIENT_MAP_JSON",
        '{"elisabeth.girschele@gmail.com":"tibor.girschele@gmail.com"}',
    )
    monkeypatch.delenv("EMAILIT_API_KEY", raising=False)

    principal_id = "cf-email:tibor.girschele@gmail.com"
    client = build_product_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Willhaben Google Sync Office")

    observed_sync_kwargs: dict[str, object] = {}

    def _fake_list_recent_workspace_signals(**kwargs):  # type: ignore[no-untyped-def]
        observed_sync_kwargs.update(kwargs)
        return google_oauth_service.GoogleWorkspaceSignalSync(
            account_email="elisabeth.girschele@gmail.com",
            account_emails=("elisabeth.girschele@gmail.com",),
            granted_scopes=(google_oauth_service.GOOGLE_SCOPE_GMAIL_MODIFY,),
            signals=(
                google_oauth_service.GoogleWorkspaceSignal(
                    signal_type="email_thread",
                    channel="gmail",
                    title='"Mietwohnungen 2,20, 09" hat 1 neue Anzeige für dich gefunden',
                    summary='"Mietwohnungen 2,20, 09" hat 1 neue Anzeige für dich gefunden',
                    text="Neue Anzeige gefunden. https://www.willhaben.at/iad/immobilien/d/mietwohnungen/wien/google-sync-apartment-777",
                    source_ref="gmail-thread:elisabeth.girschele@gmail.com:google-sync-willhaben-1",
                    external_id="gmail-message:elisabeth.girschele@gmail.com:google-sync-willhaben-1",
                    counterparty="willhaben-Suchagent",
                    due_at=None,
                    payload={
                        "from_email": "no-reply@agent.willhaben.at",
                        "from_name": "willhaben-Suchagent",
                        "account_email": "elisabeth.girschele@gmail.com",
                        "body_text_excerpt": (
                            "Neue Anzeige gefunden. "
                            "https://www.willhaben.at/iad/immobilien/d/mietwohnungen/wien/google-sync-apartment-777"
                        ),
                        "binding_id": "browseract-binding-google-sync",
                        "labels": ["CATEGORY_UPDATES", "INBOX"],
                    },
                ),
            ),
        )

    monkeypatch.setattr(google_oauth_service, "list_recent_workspace_signals", _fake_list_recent_workspace_signals)
    monkeypatch.setattr(
        product_service,
        "_load_willhaben_property_packet",
        lambda url: {
            "property_url": url,
            "listing_id": "listing-google-sync-777",
            "title": "Google sync apartment",
            "property_facts_json": {},
            "media_urls_json": ["https://cdn.example.com/apartment-google-sync/photo-1.jpg"],
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

    def _fake_send_google_gmail_message(**kwargs):  # type: ignore[no-untyped-def]
        observed_email.update(kwargs)
        return google_oauth_service.GoogleGmailSendResult(
            binding=SimpleNamespace(binding_id="google-binding-elisabeth"),
            sender_email="elisabeth.girschele@gmail.com",
            recipient_email=str(kwargs["recipient_email"]),
            subject=str(kwargs["subject"]),
            rfc822_message_id="<property-tour-google-sync@ea.local>",
            gmail_message_id="gmail-property-tour-google-sync",
            sent_at="2026-05-02T00:00:00+00:00",
        )

    monkeypatch.setattr(google_oauth_service, "send_google_gmail_message", _fake_send_google_gmail_message)
    monkeypatch.setattr(
        google_oauth_service,
        "list_google_accounts",
        lambda **_: [
            SimpleNamespace(
                binding=SimpleNamespace(binding_id="google-binding-elisabeth"),
                google_email="elisabeth.girschele@gmail.com",
            )
        ],
    )

    def _fake_execute_task_artifact(request):  # type: ignore[no-untyped-def]
        assert request.input_json["binding_id"] == "browseract-binding-google-sync"
        return Artifact(
            artifact_id="artifact-property-tour-google-sync",
            kind="property_tour_packet",
            content="Property tour created.",
            execution_session_id="session-property-tour-google-sync",
            principal_id=principal_id,
            structured_output_json={
                "public_url": "https://myexternalbrain.com/tours/google-sync-apartment",
                "crezlo_public_url": "https://vendor.example.com/tours/google-sync-apartment",
            },
        )

    client.app.state.container.orchestrator.execute_task_artifact = _fake_execute_task_artifact

    synced = client.post(
        "/app/api/signals/google/willhaben-sync",
        params={"account_email": "elisabeth.girschele@gmail.com", "email_limit": 5},
    )
    assert synced.status_code == 200
    body = synced.json()
    assert body["account_email"] == "elisabeth.girschele@gmail.com"
    assert body["account_emails"] == ["elisabeth.girschele@gmail.com"]
    assert body["total"] == 1
    assert body["synced_total"] == 1
    assert observed_email["recipient_email"] == "tibor.girschele@gmail.com"
    assert observed_email["binding_id"] == "google-binding-elisabeth"
    assert "google-sync-apartment-777" in observed_email["body_text"]
    assert observed_sync_kwargs["account_email_filter"] == "elisabeth.girschele@gmail.com"
    assert observed_sync_kwargs["gmail_query"] == (
        "from:("
        "agent.willhaben.at OR "
        "no-reply@agent.willhaben.at OR "
        "immmo.at OR "
        "mailrobot@immmo.at OR "
        "immoscout24.at OR "
        "immoscout24.com OR "
        "immobilienscout24.at OR "
        "immobilienscout24.de OR "
        "no-reply@immoscout24.at OR "
        "no-reply@immobilienscout24.de"
        ")"
    )


def test_google_property_sync_uses_configured_property_alert_query(monkeypatch) -> None:
    monkeypatch.setenv("EA_PROPERTY_ALERT_GMAIL_QUERY", "from:(immmo.at OR immoscout.example)")
    principal_id = "cf-email:tibor.girschele@gmail.com"
    client = build_product_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Executive Office")

    observed_sync_kwargs: dict[str, object] = {}

    def _fake_list_recent_workspace_signals(**kwargs):
        observed_sync_kwargs.update(kwargs)
        return google_oauth_service.GoogleWorkspaceSignalSync(
            account_email="elisabeth.girschele@gmail.com",
            account_emails=("elisabeth.girschele@gmail.com",),
            granted_scopes=(),
            signals=(),
        )

    monkeypatch.setattr(google_oauth_service, "list_recent_workspace_signals", _fake_list_recent_workspace_signals)

    response = client.post(
        "/app/api/signals/google/property-sync",
        params={"account_email": "elisabeth.girschele@gmail.com", "email_limit": 5},
    )
    assert response.status_code == 200
    assert observed_sync_kwargs["gmail_query"] == "from:(immmo.at OR immoscout.example)"
    assert observed_sync_kwargs["calendar_limit"] == 0


def test_google_property_sync_suppresses_telegram_for_weak_digest_alert(monkeypatch) -> None:
    principal_id = "cf-email:tibor.girschele@gmail.com"
    client = build_product_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Quiet Property Alert Office")

    monkeypatch.setattr(
        google_oauth_service,
        "list_recent_workspace_signals",
        lambda **_: google_oauth_service.GoogleWorkspaceSignalSync(
            account_email="elisabeth.girschele@gmail.com",
            account_emails=("elisabeth.girschele@gmail.com",),
            granted_scopes=(google_oauth_service.GOOGLE_SCOPE_GMAIL_MODIFY,),
            signals=(
                google_oauth_service.GoogleWorkspaceSignal(
                    signal_type="email_thread",
                    channel="gmail",
                    title='"Eigentumswohnungen" hat 5 neue Anzeigen für dich gefunden',
                    summary="Recent mail from willhaben-Suchagent.",
                    text="Neue Anzeigen gefunden.",
                    source_ref="gmail-thread:elisabeth.girschele@gmail.com:quiet-digest-1",
                    external_id="gmail-message:elisabeth.girschele@gmail.com:quiet-digest-1",
                    counterparty="willhaben-Suchagent",
                    due_at=None,
                    payload={
                        "from_email": "no-reply@agent.willhaben.at",
                        "from_name": "willhaben-Suchagent",
                        "account_email": "elisabeth.girschele@gmail.com",
                        "body_text_excerpt": "Neue Anzeigen gefunden.",
                        "labels": ["CATEGORY_UPDATES", "INBOX"],
                    },
                ),
            ),
        ),
    )
    sent: list[dict[str, object]] = []
    monkeypatch.setattr(
        product_service,
        "send_telegram_message_for_principal",
        lambda *args, **kwargs: sent.append({"args": args, "kwargs": kwargs}) or SimpleNamespace(message_ids=["1"], chat_id="chat"),
    )

    synced = client.post(
        "/app/api/signals/google/property-sync",
        params={"account_email": "elisabeth.girschele@gmail.com", "email_limit": 5},
    )
    assert synced.status_code == 200
    assert synced.json()["synced_total"] == 1
    assert sent == []

    events = client.get("/app/api/events", params={"channel": "product"})
    assert events.status_code == 200
    event_types = [item["event_type"] for item in events.json()["items"]]
    assert "property_alert_review_created" in event_types
    assert "property_alert_review_telegram_suppressed" in event_types


def test_google_property_sync_scores_elisabeth_mailbox_against_elisabeth_profile(monkeypatch) -> None:
    monkeypatch.setenv("EA_PROPERTY_SCOUT_DEFAULT_PERSON_ID", "elisabeth")
    principal_id = "cf-email:tibor.girschele@gmail.com"
    client = build_product_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Elisabeth Property Alert Office")

    listing_url = "https://www.willhaben.at/iad/immobilien/d/mietwohnungen/wien/waehring/high-fit-mailbox-1"
    monkeypatch.setattr(
        google_oauth_service,
        "list_recent_workspace_signals",
        lambda **_: google_oauth_service.GoogleWorkspaceSignalSync(
            account_email="elisabeth.girschele@gmail.com",
            account_emails=("elisabeth.girschele@gmail.com",),
            granted_scopes=(google_oauth_service.GOOGLE_SCOPE_GMAIL_MODIFY,),
            signals=(
                google_oauth_service.GoogleWorkspaceSignal(
                    signal_type="email_thread",
                    channel="gmail",
                    title='"Mietwohnungen 1180" hat 1 neue Anzeige fuer dich gefunden',
                    summary="Recent mail from willhaben-Suchagent.",
                    text=listing_url,
                    source_ref="gmail-thread:elisabeth.girschele@gmail.com:high-fit-mailbox-1",
                    external_id="gmail-message:elisabeth.girschele@gmail.com:high-fit-mailbox-1",
                    counterparty="willhaben-Suchagent",
                    due_at=None,
                    payload={
                        "from_email": "no-reply@agent.willhaben.at",
                        "from_name": "willhaben-Suchagent",
                        "account_email": "elisabeth.girschele@gmail.com",
                        "body_text_excerpt": listing_url,
                        "labels": ["CATEGORY_UPDATES", "INBOX"],
                    },
                ),
            ),
        ),
    )
    monkeypatch.setattr(
        product_service,
        "_load_willhaben_property_packet",
        lambda url: {
            "property_url": url,
            "listing_id": "high-fit-mailbox-1",
            "title": "Waehring high fit mailbox flat",
            "property_facts_json": {
                "postal_name": "Waehring",
                "heating": "Fernwaerme",
                "floorplan_count": 1,
            },
            "media_urls_json": ["https://cdn.example.com/photo.jpg"],
            "floorplan_urls_json": ["https://cdn.example.com/floorplan.jpg"],
            "tour_variants_json": [],
        },
    )
    assessed: list[dict[str, object]] = []

    def _fake_assess_candidate(**kwargs):
        assessed.append(dict(kwargs))
        return {
            "fit_score": 94.0,
            "confidence": 0.9,
            "predicted_reaction": "shortlist",
            "recommendation": "shortlist",
            "match_reasons_json": ["Matches Elisabeth."],
            "mismatch_reasons_json": [],
            "unknowns_json": [],
            "blocking_constraints_json": [],
        }

    monkeypatch.setattr(client.app.state.container.preference_profiles, "assess_candidate", _fake_assess_candidate)
    monkeypatch.setattr(
        ProductService,
        "create_willhaben_property_tour",
        lambda self, **kwargs: {
            "status": "created",
            "tour_url": "https://myexternalbrain.com/tours/high-fit-mailbox-1",
            "vendor_tour_url": "https://vendor.example.com/tours/high-fit-mailbox-1",
            "blocked_reason": "",
        },
    )
    sent: list[dict[str, object]] = []
    monkeypatch.setattr(
        product_service,
        "send_telegram_message_for_principal",
        lambda *args, **kwargs: sent.append({"args": args, "kwargs": kwargs}) or SimpleNamespace(message_ids=["1"], chat_id="chat"),
    )

    synced = client.post(
        "/app/api/signals/google/property-sync",
        params={"account_email": "elisabeth.girschele@gmail.com", "email_limit": 5},
    )
    assert synced.status_code == 200
    assert synced.json()["synced_total"] == 1
    assert assessed
    assert any(
        row["person_id"] == "elisabeth" and row["object_id"] == "high-fit-mailbox-1"
        for row in assessed
    )
    assert sent
    assert "Preference profile: elisabeth" in sent[0]["kwargs"]["text"]
    assert "3D tour: https://myexternalbrain.com/tours/high-fit-mailbox-1" in sent[0]["kwargs"]["text"]
    assert listing_url not in sent[0]["kwargs"]["text"]

    events = client.get("/app/api/events", params={"channel": "product", "event_type": "property_alert_review_created"})
    assert events.status_code == 200
    created = [item for item in events.json()["items"] if item["payload"].get("source_ref") == "gmail-thread:elisabeth.girschele@gmail.com:high-fit-mailbox-1"]
    assert created
    assert created[0]["payload"]["preference_person_id"] == "elisabeth"
    assert created[0]["payload"]["personal_fit_assessment"]["fit_score"] == 94.0
    assert created[0]["payload"]["tour_url"] == "https://myexternalbrain.com/tours/high-fit-mailbox-1"


def test_google_property_sync_splits_digest_into_per_listing_reviews(monkeypatch) -> None:
    principal_id = "cf-email:tibor.girschele@gmail.com"
    client = build_product_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Split Digest Property Office")

    monkeypatch.setattr(
        google_oauth_service,
        "list_recent_workspace_signals",
        lambda **_: google_oauth_service.GoogleWorkspaceSignalSync(
            account_email="elisabeth.girschele@gmail.com",
            account_emails=("elisabeth.girschele@gmail.com",),
            granted_scopes=(google_oauth_service.GOOGLE_SCOPE_GMAIL_MODIFY,),
            signals=(
                google_oauth_service.GoogleWorkspaceSignal(
                    signal_type="email_thread",
                    channel="gmail",
                    title='"Eigentumswohnungen" hat 2 neue Anzeigen für dich gefunden',
                    summary="Recent mail from willhaben-Suchagent.",
                    text=(
                        "https://www.willhaben.at/iad/immobilien/d/mietwohnungen/wien/waehring/top-fit-1 "
                        "https://www.willhaben.at/iad/immobilien/d/mietwohnungen/wien/floridsdorf/weak-fit-2"
                    ),
                    source_ref="gmail-thread:elisabeth.girschele@gmail.com:split-digest-1",
                    external_id="gmail-message:elisabeth.girschele@gmail.com:split-digest-1",
                    counterparty="willhaben-Suchagent",
                    due_at=None,
                    payload={
                        "from_email": "no-reply@agent.willhaben.at",
                        "from_name": "willhaben-Suchagent",
                        "account_email": "elisabeth.girschele@gmail.com",
                        "body_text_excerpt": (
                            "https://www.willhaben.at/iad/immobilien/d/mietwohnungen/wien/waehring/top-fit-1 "
                            "https://www.willhaben.at/iad/immobilien/d/mietwohnungen/wien/floridsdorf/weak-fit-2"
                        ),
                        "labels": ["CATEGORY_UPDATES", "INBOX"],
                    },
                ),
            ),
        ),
    )
    monkeypatch.setattr(
        product_service,
        "_load_willhaben_property_packet",
        lambda url: {
            "property_url": url,
            "listing_id": ("listing-top-fit-1" if "top-fit-1" in url else "listing-weak-fit-2"),
            "title": "Mock listing",
            "property_facts_json": {
                "district": "Waehring" if "top-fit-1" in url else "Floridsdorf",
                "heating_type": "Fernwaerme" if "top-fit-1" in url else "Gasheizung",
                "has_360": True if "top-fit-1" in url else False,
                "has_floorplan": True if "top-fit-1" in url else False,
                "lift": True if "top-fit-1" in url else False,
            },
            "media_urls_json": ["https://cdn.example.com/property.jpg"],
            "floorplan_urls_json": ["https://cdn.example.com/floorplan.jpg"] if "top-fit-1" in url else [],
            "tour_variants_json": [],
        },
    )
    sent: list[dict[str, object]] = []
    monkeypatch.setattr(
        product_service,
        "send_telegram_message_for_principal",
        lambda *args, **kwargs: sent.append({"args": args, "kwargs": kwargs}) or SimpleNamespace(message_ids=["1"], chat_id="chat"),
    )

    profile = client.post(
        "/app/api/people/self/preference-profile",
        json={
            "display_name": "Tibor",
            "consent_mode": "behavioral_learning",
            "learning_enabled": True,
            "high_stakes_domains_enabled": True,
        },
    )
    assert profile.status_code == 200
    for node_payload in (
        {"domain": "willhaben", "category": "soft_preference", "key": "preferred_districts", "value_json": ["Waehring"], "confidence": 1.0},
        {"domain": "willhaben", "category": "aversion", "key": "avoid_heating_types", "value_json": ["Gasheizung"], "confidence": 1.0},
        {"domain": "willhaben", "category": "constraint", "key": "require_floorplan", "value_json": True, "confidence": 1.0},
        {"domain": "willhaben", "category": "soft_preference", "key": "prefer_360_for_remote_review", "value_json": True, "confidence": 1.0},
    ):
        node = client.post("/app/api/people/self/preference-profile/nodes", json=node_payload)
        assert node.status_code == 200

    synced = client.post(
        "/app/api/signals/google/property-sync",
        params={"account_email": "elisabeth.girschele@gmail.com", "email_limit": 5},
    )
    assert synced.status_code == 200
    assert synced.json()["synced_total"] == 1

    events = client.get("/app/api/events", params={"channel": "product"})
    assert events.status_code == 200
    created = [item for item in events.json()["items"] if item["event_type"] == "property_alert_review_created"]
    assert len(created) == 2
    assert any("top-fit-1" in json.dumps(item.get("payload") or {}) for item in created)
    assert len(sent) <= 1


def test_google_property_sync_reranks_digest_using_learned_feedback_conflicts(monkeypatch) -> None:
    principal_id = "cf-email:tibor.girschele@gmail.com"
    client = build_product_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Feedback Ranked Property Office")

    monkeypatch.setattr(
        google_oauth_service,
        "list_recent_workspace_signals",
        lambda **_: google_oauth_service.GoogleWorkspaceSignalSync(
            account_email="elisabeth.girschele@gmail.com",
            account_emails=("elisabeth.girschele@gmail.com",),
            granted_scopes=(google_oauth_service.GOOGLE_SCOPE_GMAIL_MODIFY,),
            signals=(
                google_oauth_service.GoogleWorkspaceSignal(
                    signal_type="email_thread",
                    channel="gmail",
                    title='"Mietwohnungen Wien" hat 2 neue Anzeigen fuer dich gefunden',
                    summary="Recent mail from willhaben-Suchagent.",
                    text=(
                        "https://www.willhaben.at/iad/immobilien/d/mietwohnungen/wien/doebling/conflict-flat-1 "
                        "https://www.willhaben.at/iad/immobilien/d/mietwohnungen/wien/waehring/good-flat-2"
                    ),
                    source_ref="gmail-thread:elisabeth.girschele@gmail.com:feedback-rank-1",
                    external_id="gmail-message:elisabeth.girschele@gmail.com:feedback-rank-1",
                    counterparty="willhaben-Suchagent",
                    due_at=None,
                    payload={
                        "from_email": "no-reply@agent.willhaben.at",
                        "from_name": "willhaben-Suchagent",
                        "account_email": "elisabeth.girschele@gmail.com",
                        "body_text_excerpt": (
                            "https://www.willhaben.at/iad/immobilien/d/mietwohnungen/wien/doebling/conflict-flat-1 "
                            "https://www.willhaben.at/iad/immobilien/d/mietwohnungen/wien/waehring/good-flat-2"
                        ),
                        "labels": ["CATEGORY_UPDATES", "INBOX"],
                    },
                ),
            ),
        ),
    )
    monkeypatch.setattr(
        product_service,
        "_load_willhaben_property_packet",
        lambda url: {
            "property_url": url,
            "listing_id": ("conflict-flat-1" if "conflict-flat-1" in url else "good-flat-2"),
            "title": ("Conflict flat" if "conflict-flat-1" in url else "Good flat"),
            "property_facts_json": (
                {
                    "district": "Doebling",
                    "postal_name": "Doebling",
                    "heating_type": "Gasheizung",
                    "has_floorplan": False,
                    "lift": False,
                    "nearest_subway_m": 1500,
                }
                if "conflict-flat-1" in url
                else {
                    "district": "Waehring",
                    "postal_name": "Waehring",
                    "heating_type": "Fernwaerme",
                    "has_floorplan": True,
                    "lift": True,
                    "nearest_subway_m": 280,
                }
            ),
            "media_urls_json": ["https://cdn.example.com/property.jpg"],
            "floorplan_urls_json": ([] if "conflict-flat-1" in url else ["https://cdn.example.com/floorplan.jpg"]),
            "tour_variants_json": [],
        },
    )

    def _flat_high_assessment(**kwargs):
        return {
            "fit_score": 91.0,
            "confidence": 0.95,
            "predicted_reaction": "shortlist",
            "recommendation": "shortlist",
            "match_reasons_json": ["Base model score is high."],
            "mismatch_reasons_json": [],
            "unknowns_json": [],
            "blocking_constraints_json": [],
        }

    monkeypatch.setattr(client.app.state.container.preference_profiles, "assess_candidate", _flat_high_assessment)
    monkeypatch.setattr(
        ProductService,
        "create_willhaben_property_tour",
        lambda self, **kwargs: {
            "status": "created",
            "tour_url": f"https://myexternalbrain.com/tours/{kwargs['property_url'].rsplit('/', 1)[-1]}",
            "vendor_tour_url": "",
            "blocked_reason": "",
        },
    )
    sent: list[dict[str, object]] = []
    monkeypatch.setattr(
        product_service,
        "send_telegram_message_for_principal",
        lambda *args, **kwargs: sent.append({"args": args, "kwargs": kwargs}) or SimpleNamespace(message_ids=["1"], chat_id="chat"),
    )

    profile = client.post(
        "/app/api/people/self/preference-profile",
        json={
            "display_name": "Tibor",
            "consent_mode": "behavioral_learning",
            "learning_enabled": True,
            "high_stakes_domains_enabled": True,
        },
    )
    assert profile.status_code == 200
    for node_payload in (
        {"domain": "willhaben", "category": "aversion", "key": "avoid_heating_types", "value_json": ["Gasheizung"], "confidence": 1.0},
        {"domain": "willhaben", "category": "constraint", "key": "require_floorplan", "value_json": True, "confidence": 1.0},
        {"domain": "willhaben", "category": "soft_preference", "key": "prefer_lift", "value_json": True, "confidence": 1.0},
        {"domain": "willhaben", "category": "soft_preference", "key": "prefer_subway_nearby", "value_json": True, "confidence": 1.0},
    ):
        node = client.post("/app/api/people/self/preference-profile/nodes", json=node_payload)
        assert node.status_code == 200

    synced = client.post(
        "/app/api/signals/google/property-sync",
        params={"account_email": "elisabeth.girschele@gmail.com", "email_limit": 5},
    )
    assert synced.status_code == 200

    events = client.get("/app/api/events", params={"channel": "product", "event_type": "property_alert_review_created"})
    assert events.status_code == 200
    created = [item for item in events.json()["items"] if "feedback-rank-1" in str(item.get("payload", {}).get("source_ref") or "")]
    assert len(created) == 2
    primary = next(item for item in created if item["payload"]["source_ref"] == "gmail-thread:elisabeth.girschele@gmail.com:feedback-rank-1")
    assert primary["payload"]["property_url"].endswith("good-flat-2")
    if sent:
        assert "good-flat-2" in sent[0]["kwargs"]["text"]
        assert "conflict-flat-1" not in sent[0]["kwargs"]["text"]


def test_google_property_sync_suppresses_high_raw_score_when_learned_conflicts_stack(monkeypatch) -> None:
    principal_id = "cf-email:tibor.girschele@gmail.com"
    client = build_product_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Feedback Suppression Property Office")

    listing_url = "https://www.willhaben.at/iad/immobilien/d/mietwohnungen/wien/doebling/stacked-conflict-flat-1"
    monkeypatch.setattr(
        google_oauth_service,
        "list_recent_workspace_signals",
        lambda **_: google_oauth_service.GoogleWorkspaceSignalSync(
            account_email="elisabeth.girschele@gmail.com",
            account_emails=("elisabeth.girschele@gmail.com",),
            granted_scopes=(google_oauth_service.GOOGLE_SCOPE_GMAIL_MODIFY,),
            signals=(
                google_oauth_service.GoogleWorkspaceSignal(
                    signal_type="email_thread",
                    channel="gmail",
                    title='"Mietwohnungen Wien" hat 1 neue Anzeige fuer dich gefunden',
                    summary="Recent mail from willhaben-Suchagent.",
                    text=listing_url,
                    source_ref="gmail-thread:elisabeth.girschele@gmail.com:feedback-suppress-1",
                    external_id="gmail-message:elisabeth.girschele@gmail.com:feedback-suppress-1",
                    counterparty="willhaben-Suchagent",
                    due_at=None,
                    payload={
                        "from_email": "no-reply@agent.willhaben.at",
                        "from_name": "willhaben-Suchagent",
                        "account_email": "elisabeth.girschele@gmail.com",
                        "body_text_excerpt": listing_url,
                        "labels": ["CATEGORY_UPDATES", "INBOX"],
                    },
                ),
            ),
        ),
    )
    monkeypatch.setattr(
        product_service,
        "_load_willhaben_property_packet",
        lambda url: {
            "property_url": url,
            "listing_id": "stacked-conflict-flat-1",
            "title": "Stacked conflict flat",
            "property_facts_json": {
                "district": "Doebling",
                "postal_name": "Doebling",
                "heating_type": "Gasheizung",
                "has_floorplan": False,
                "lift": False,
                "nearest_subway_m": 1800,
            },
            "media_urls_json": ["https://cdn.example.com/property.jpg"],
            "floorplan_urls_json": [],
            "tour_variants_json": [],
        },
    )
    monkeypatch.setattr(
        client.app.state.container.preference_profiles,
        "assess_candidate",
        lambda **kwargs: {
            "fit_score": 92.0,
            "confidence": 0.95,
            "predicted_reaction": "shortlist",
            "recommendation": "shortlist",
            "match_reasons_json": ["Base model score is high."],
            "mismatch_reasons_json": [],
            "unknowns_json": [],
            "blocking_constraints_json": [],
        },
    )
    sent: list[dict[str, object]] = []
    monkeypatch.setattr(
        product_service,
        "send_telegram_message_for_principal",
        lambda *args, **kwargs: sent.append({"args": args, "kwargs": kwargs}) or SimpleNamespace(message_ids=["1"], chat_id="chat"),
    )

    profile = client.post(
        "/app/api/people/self/preference-profile",
        json={
            "display_name": "Tibor",
            "consent_mode": "behavioral_learning",
            "learning_enabled": True,
            "high_stakes_domains_enabled": True,
        },
    )
    assert profile.status_code == 200
    for node_payload in (
        {"domain": "willhaben", "category": "aversion", "key": "avoid_heating_types", "value_json": ["Gasheizung"], "confidence": 1.0},
        {"domain": "willhaben", "category": "constraint", "key": "require_floorplan", "value_json": True, "confidence": 1.0},
        {"domain": "willhaben", "category": "soft_preference", "key": "prefer_lift", "value_json": True, "confidence": 1.0},
        {"domain": "willhaben", "category": "soft_preference", "key": "prefer_subway_nearby", "value_json": True, "confidence": 1.0},
    ):
        node = client.post("/app/api/people/self/preference-profile/nodes", json=node_payload)
        assert node.status_code == 200

    synced = client.post(
        "/app/api/signals/google/property-sync",
        params={"account_email": "elisabeth.girschele@gmail.com", "email_limit": 5},
    )
    assert synced.status_code == 200
    assert sent == []

    events = client.get("/app/api/events", params={"channel": "product"})
    assert events.status_code == 200
    created = [item for item in events.json()["items"] if item["event_type"] == "property_alert_review_created"]
    assert any(item["payload"]["source_ref"] == "gmail-thread:elisabeth.girschele@gmail.com:feedback-suppress-1" for item in created)
    suppressed = [item for item in events.json()["items"] if item["event_type"] == "property_alert_review_telegram_suppressed"]
    assert any(item["payload"]["source_ref"] == "gmail-thread:elisabeth.girschele@gmail.com:feedback-suppress-1" for item in suppressed)


def test_resolve_primary_telegram_binding_prefers_real_numeric_chat_ref() -> None:
    class _Runtime:
        def list_connector_bindings(self, principal_id: str, limit: int = 200):
            return [
                SimpleNamespace(
                    connector_name="telegram_identity",
                    status="enabled",
                    external_account_ref="telegram-live-policy-test",
                    auth_metadata_json={"default_chat_ref": "telegram-live-policy-test"},
                    updated_at="2026-05-27T08:45:09+02:00",
                ),
                SimpleNamespace(
                    connector_name="telegram_identity",
                    status="enabled",
                    external_account_ref="1354554303",
                    auth_metadata_json={"default_chat_ref": "1354554303"},
                    updated_at="2026-05-27T08:40:09+02:00",
                ),
            ]

    from app.services.telegram_delivery import resolve_primary_telegram_binding

    binding = resolve_primary_telegram_binding(_Runtime(), principal_id="cf-email:tibor.girschele@gmail.com")
    assert binding is not None
    assert str(binding.external_account_ref) == "1354554303"


def test_willhaben_property_tour_route_retries_gmail_delivery_with_fallback_binding(monkeypatch) -> None:
    from app.domain.models import Artifact

    monkeypatch.setenv("EA_WILLHABEN_PROPERTY_TOUR_REQUIRE_360", "0")
    principal_id = "cf-email:tibor.girschele@gmail.com"
    client = build_product_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Executive Office")

    packet = {
        "property_url": "https://www.willhaben.at/iad/immobilien/d/mietwohnungen/wien/live-apartment-fallback-1",
        "listing_id": "listing-fallback-1",
        "listing_uuid": "listing-uuid-fallback-1",
        "title": "Fallback Gmail apartment",
        "property_facts_json": {},
        "media_urls_json": ["https://cdn.example.com/apartment-fallback/photo-1.jpg"],
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

    def _fake_execute_task_artifact(request):  # type: ignore[no-untyped-def]
        return Artifact(
            artifact_id="artifact-property-tour-fallback-1",
            kind="property_tour_packet",
            content="Property tour created.",
            execution_session_id="session-property-tour-fallback-1",
            principal_id=principal_id,
            structured_output_json={
                "public_url": "https://myexternalbrain.com/tours/fallback-gmail-apartment",
                "crezlo_public_url": "https://vendor.example.com/tours/fallback-gmail-apartment",
                "editor_url": "https://vendor.example.com/editor/fallback-gmail-apartment",
                "tour_id": "tour-fallback-1",
            },
        )

    client.app.state.container.orchestrator.execute_task_artifact = _fake_execute_task_artifact

    def _fake_list_google_accounts(**kwargs):  # type: ignore[no-untyped-def]
        principal = str(kwargs.get("principal_id") or "")
        if principal == principal_id:
            return [
                SimpleNamespace(
                    binding=SimpleNamespace(binding_id="google-binding-stale"),
                    google_email="tibor.girschele@gmail.com",
                )
            ]
        if principal == "local-user":
            return [
                SimpleNamespace(
                    binding=SimpleNamespace(binding_id="google-binding-fallback"),
                    google_email="tibor.girschele@gmail.com",
                )
            ]
        return []

    monkeypatch.setattr(google_oauth_service, "list_google_accounts", _fake_list_google_accounts)

    attempts: list[tuple[str, str]] = []

    def _fake_send_google_gmail_message(**kwargs):  # type: ignore[no-untyped-def]
        binding_id = str(kwargs.get("binding_id") or "")
        attempts.append((str(kwargs.get("principal_id") or ""), binding_id))
        if binding_id == "google-binding-stale":
            raise RuntimeError("google_oauth_refresh_failed invalid_grant")
        return google_oauth_service.GoogleGmailSendResult(
            binding=SimpleNamespace(binding_id=binding_id),
            sender_email="tibor.girschele@gmail.com",
            recipient_email=str(kwargs["recipient_email"]),
            subject=str(kwargs["subject"]),
            rfc822_message_id="<property-tour-fallback@ea.local>",
            gmail_message_id="gmail-property-tour-fallback",
            sent_at="2026-05-25T00:00:00+00:00",
        )

    monkeypatch.setattr(google_oauth_service, "send_google_gmail_message", _fake_send_google_gmail_message)

    created = client.post(
        "/app/api/signals/willhaben/property-tour",
        json={
            "property_url": packet["property_url"],
            "binding_id": "browseract-binding-fallback-1",
        },
    )
    assert created.status_code == 200
    body = created.json()
    assert body["status"] == "sent"
    assert body["delivery_status"] == "sent"
    assert attempts == [
        (principal_id, "google-binding-stale"),
        ("local-user", "google-binding-fallback"),
    ]

    events = client.get(
        "/app/api/events",
        params={"channel": "product", "event_type": "willhaben_property_tour_email_sent"},
    )
    assert events.status_code == 200
    assert any(item["payload"]["google_binding_id"] == "google-binding-fallback" for item in events.json()["items"])


def test_willhaben_property_tour_route_backfills_hosted_url_from_structured_output(monkeypatch) -> None:
    from app.domain.models import Artifact

    monkeypatch.setenv("EA_WILLHABEN_PROPERTY_TOUR_REQUIRE_360", "0")
    principal_id = "cf-email:tibor.girschele@gmail.com"
    client = build_product_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Executive Office")

    packet = {
        "property_url": "https://www.willhaben.at/iad/immobilien/d/mietwohnungen/wien/live-apartment-hosted-fallback-1",
        "listing_id": "listing-hosted-fallback-1",
        "listing_uuid": "listing-uuid-hosted-fallback-1",
        "title": "Hosted fallback apartment",
        "property_facts_json": {},
        "media_urls_json": ["https://cdn.example.com/apartment-hosted/photo-1.jpg"],
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

    def _fake_hosted_url(structured_output):  # type: ignore[no-untyped-def]
        payload = dict(structured_output or {})
        payload["hosted_url"] = "https://myexternalbrain.com/tours/hosted-fallback-apartment"
        payload["public_url"] = "https://myexternalbrain.com/tours/hosted-fallback-apartment"
        payload["crezlo_public_url"] = "https://ea-property-tours-20260320.crezlotours.com/tours/hosted-fallback-apartment"
        return payload

    monkeypatch.setattr("app.product.service._ensure_hosted_property_tour_url", _fake_hosted_url)

    def _fake_execute_task_artifact(request):  # type: ignore[no-untyped-def]
        return Artifact(
            artifact_id="artifact-property-tour-hosted-fallback-1",
            kind="property_tour_packet",
            content="Property tour created.",
            execution_session_id="session-property-tour-hosted-fallback-1",
            principal_id=principal_id,
            structured_output_json={
                "public_url": "https://ea-property-tours-20260320.crezlotours.com/tours/hosted-fallback-apartment",
                "editor_url": "https://ea-property-tours-20260320.crezlotours.com/admin/tours/hosted-fallback-apartment",
                "tour_id": "tour-hosted-fallback-1",
            },
        )

    client.app.state.container.orchestrator.execute_task_artifact = _fake_execute_task_artifact

    created = client.post(
        "/app/api/signals/willhaben/property-tour",
        json={
            "property_url": packet["property_url"],
            "binding_id": "browseract-binding-hosted-fallback-1",
            "auto_deliver": False,
        },
    )
    assert created.status_code == 200
    body = created.json()
    assert body["status"] == "created"
    assert body["tour_url"] == "https://myexternalbrain.com/tours/hosted-fallback-apartment"
    assert body["vendor_tour_url"] == "https://ea-property-tours-20260320.crezlotours.com/tours/hosted-fallback-apartment"


def test_generic_property_tour_blocks_generated_listing_fallback_payload(monkeypatch) -> None:
    from app.domain.models import Artifact

    principal_id = "cf-email:tibor.girschele@gmail.com"
    client = build_product_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Executive Office")
    service = ProductService(client.app.state.container)
    property_url = "https://www.immobilienscout24.at/expose/abc-1"

    monkeypatch.setattr(ProductService, "_resolve_browseract_property_tour_binding_id", lambda self, **kwargs: "browseract-binding-1")
    monkeypatch.setattr(
        product_service,
        "_property_scout_page_preview",
        lambda url: {
            "listing_id": "abc-1",
            "title": "Scout flat abc-1",
            "summary": "Fallback only",
            "property_facts_json": {"has_360": True},
            "media_urls_json": [],
            "floorplan_urls_json": [],
            "panorama_media_urls_json": [],
            "source_virtual_tour_url": "https://360.example.test/view/portal/id/abc-1",
            "panorama_source": "360.example.test",
        },
    )

    client.app.state.container.orchestrator.execute_task_artifact = lambda request: Artifact(  # type: ignore[no-untyped-def]
        artifact_id="artifact-fallback-1",
        kind="property_tour_packet",
        content="Fallback tour created.",
        execution_session_id="session-fallback-1",
        principal_id=principal_id,
        structured_output_json={
            "slug": "fallback-tour-disabled",
            "hosted_url": "https://myexternalbrain.com/tours/fallback-tour-disabled",
            "public_url": "https://myexternalbrain.com/tours/fallback-tour-disabled",
            "scene_strategy": "generated_listing_summary",
            "creation_mode": "hosted_listing_fallback",
            "scenes": [
                {
                    "name": "Generated listing overview",
                    "role": "generated_overview",
                    "asset_relpath": "scene-01.svg",
                }
            ],
        },
    )

    result = service.create_generic_property_tour(
        principal_id=principal_id,
        property_url=property_url,
        source_ref="gmail-thread:elisabeth:generated-fallback",
        auto_deliver=False,
        actor="test",
    )

    assert result["status"] == "blocked"
    assert result["blocked_reason"] == "property_tour_fallback_disabled"
    assert result["tour_url"] == ""


def test_willhaben_property_tour_blocks_generated_listing_fallback_payload(monkeypatch) -> None:
    from app.domain.models import Artifact

    monkeypatch.setenv("EA_WILLHABEN_PROPERTY_TOUR_REQUIRE_360", "0")
    principal_id = "cf-email:tibor.girschele@gmail.com"
    client = build_product_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Executive Office")

    packet = {
        "property_url": "https://www.willhaben.at/iad/immobilien/d/mietwohnungen/wien/live-apartment-fallback-disabled-1",
        "listing_id": "listing-fallback-disabled-1",
        "listing_uuid": "listing-uuid-fallback-disabled-1",
        "title": "Hosted fallback apartment",
        "property_facts_json": {},
        "media_urls_json": ["https://cdn.example.com/apartment-hosted/photo-1.jpg"],
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

    client.app.state.container.orchestrator.execute_task_artifact = lambda request: Artifact(  # type: ignore[no-untyped-def]
        artifact_id="artifact-property-tour-fallback-disabled-1",
        kind="property_tour_packet",
        content="Fallback tour created.",
        execution_session_id="session-property-tour-fallback-disabled-1",
        principal_id=principal_id,
        structured_output_json={
            "hosted_url": "https://myexternalbrain.com/tours/fallback-disabled-apartment",
            "public_url": "https://myexternalbrain.com/tours/fallback-disabled-apartment",
            "editor_url": "https://ea-property-tours-20260320.crezlotours.com/admin/tours/fallback-disabled-apartment",
            "scene_strategy": "generated_listing_summary",
            "creation_mode": "hosted_listing_fallback",
            "scenes": [
                {
                    "name": "Generated listing overview",
                    "role": "generated_overview",
                    "asset_relpath": "scene-01.svg",
                }
            ],
        },
    )

    created = client.post(
        "/app/api/signals/willhaben/property-tour",
        json={
            "property_url": packet["property_url"],
            "binding_id": "browseract-binding-hosted-fallback-1",
            "auto_deliver": False,
        },
    )
    assert created.status_code == 200
    body = created.json()
    assert body["status"] == "blocked"
    assert body["blocked_reason"] == "property_tour_fallback_disabled"
    assert body["tour_url"] == ""


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


def test_google_photos_picker_session_route_returns_picker_uri(monkeypatch) -> None:
    principal_id = "exec-product-google-photos-session"
    client = build_product_client(principal_id=principal_id)
    seed_product_state(client, principal_id=principal_id)

    monkeypatch.setattr(
        google_oauth_service,
        "create_google_photos_picker_session",
        lambda **_: google_oauth_service.GooglePhotosPickerSession(
            account_email="elisabeth.girschele@gmail.com",
            binding_id="exec-google-photos:google_gmail:acct:elisabeth",
            granted_scopes=(google_oauth_service.GOOGLE_SCOPE_PHOTOS_PICKER,),
            session_id="photos-session-1",
            picker_uri="https://photos.google.com/picker/session-1",
            poll_interval="5s",
            timeout_in="300s",
            media_items_set=False,
        ),
    )

    created = client.post(
        "/app/api/signals/google/photos/session",
        json={
            "account_email": "elisabeth.girschele@gmail.com",
            "max_item_count": 25,
            "autoclose": True,
        },
    )
    assert created.status_code == 200
    body = created.json()
    assert body["status"] == "ready_for_selection"
    assert body["account_email"] == "elisabeth.girschele@gmail.com"
    assert body["session_id"] == "photos-session-1"
    assert body["picker_uri"].endswith("/autoclose")
    assert google_oauth_service.GOOGLE_SCOPE_PHOTOS_PICKER in body["granted_scopes"]


def test_google_photos_sync_ingests_analyzed_photo_signals(monkeypatch) -> None:
    principal_id = "exec-product-google-photos-sync"
    client = build_product_client(principal_id=principal_id)
    seed_product_state(client, principal_id=principal_id)

    monkeypatch.setattr(
        google_oauth_service,
        "sync_google_photos_picker_session",
        lambda **_: google_oauth_service.GooglePhotosSignalSync(
            account_email="tibor.girschele@gmail.com",
            account_emails=("tibor.girschele@gmail.com",),
            binding_id="exec-google-photos:google_gmail",
            session_id="photos-session-2",
            granted_scopes=(google_oauth_service.GOOGLE_SCOPE_PHOTOS_PICKER,),
            media_items_set=True,
            signals=(
                google_oauth_service.GoogleWorkspaceSignal(
                    signal_type="photo_library_item",
                    channel="google_photos",
                    title="IMG_1001.JPG",
                    summary="PHOTO · 4032x3024 · Apple iPhone",
                    text="Google Photos photo selected by tibor.girschele@gmail.com.",
                    source_ref="google-photo:tibor.girschele@gmail.com:item-1001",
                    external_id="google-photo:tibor.girschele@gmail.com:item-1001",
                    counterparty="tibor.girschele@gmail.com",
                    due_at=None,
                    payload={
                        "account_email": "tibor.girschele@gmail.com",
                        "google_photos_session_id": "photos-session-2",
                        "google_photos_media_item_id": "item-1001",
                        "mime_type": "image/jpeg",
                        "filename": "IMG_1001.JPG",
                        "preview_url": "https://example.test/photo-1001.jpg",
                        "suppress_candidate_staging": True,
                    },
                ),
            ),
        ),
    )
    from app.services import photo_signal_analysis

    monkeypatch.setattr(
        photo_signal_analysis,
        "analyze_photo_url",
        lambda **_: {
            "summary": "Family outing in a green park with bikes and a playground nearby.",
            "signal_kind": "outing",
            "tags": ["family", "park", "bike", "playground"],
            "suggestions": [
                "This strengthens green-space and bike-infrastructure signals.",
                "Consider saving this as a family lifestyle reference for housing scoring.",
            ],
            "notable_details": ["bikes", "green lawn", "playground"],
            "sensitivity": "medium",
            "confidence": 0.82,
            "provider": "overlay_vision",
            "status": "analyzed",
        },
    )
    monkeypatch.setattr(
        "app.product.service.send_telegram_message_for_principal",
        lambda **_: {"message_ids": ["tg-photo-1"]},
    )

    synced = client.post(
        "/app/api/signals/google/photos/sync",
        json={
            "session_id": "photos-session-2",
            "account_email": "tibor.girschele@gmail.com",
            "max_items": 10,
            "delete_session": False,
        },
    )
    assert synced.status_code == 200
    body = synced.json()
    assert body["account_email"] == "tibor.girschele@gmail.com"
    assert body["session_id"] == "photos-session-2"
    assert body["selected_total"] == 1
    assert body["analyzed_total"] == 1
    assert body["suggestion_total"] == 2
    assert body["top_suggestions"][0].startswith("This strengthens green-space")
    assert body["items"][0]["event_type"] == "office_signal_photo_library_item"

    events = client.get("/app/api/events", params={"channel": "google_photos"})
    assert events.status_code == 200
    assert any(item["event_type"] == "office_signal_photo_library_item" for item in events.json()["items"])

    product_events = client.get("/app/api/events", params={"channel": "product"})
    assert product_events.status_code == 200
    assert any(item["event_type"] == "google_photos_sync_telegram_sent" for item in product_events.json()["items"])


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
    start_workspace(client, mode="personal", workspace_name="Public Host Delivery Office")
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
    assert "https://public.example.com/workspace-access/" in delivery_body["plain_text"]
    assert "return_to=/app/" in delivery_body["plain_text"]
    assert "/app/api/" not in delivery_body["plain_text"]


def test_workspace_sign_in_email_links_fall_back_to_google_gmail_when_emailit_is_disabled(monkeypatch) -> None:
    principal_id = "exec-product-signin-gmail-fallback"
    client = build_product_client(principal_id=principal_id)
    seed_product_state(client, principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Sign In Fallback Office")
    product = ProductService(client.app.state.container)
    product.issue_workspace_access_session(
        principal_id=principal_id,
        email="tibor.girschele@gmail.com",
        role="principal",
        display_name="Tibor Girschele",
        source_kind="sign_in_email",
        expires_in_hours=24,
    )
    monkeypatch.setattr(product_service, "email_delivery_enabled", lambda: False)
    sent: list[dict[str, object]] = []

    class _FakeGmailReceipt:
        provider = "google_gmail"
        gmail_message_id = "gmail-msg-1"

    monkeypatch.setattr(
        google_oauth_service,
        "send_google_gmail_message",
        lambda **kwargs: sent.append(dict(kwargs)) or _FakeGmailReceipt(),
    )

    result = product.request_workspace_sign_in_email_links(
        email="tibor.girschele@gmail.com",
        base_url="https://myexternalbrain.com",
    )
    assert result["status"] == "sent"
    assert result["sent_total"] == 1
    assert result["failed_total"] == 0
    assert sent
    assert sent[0]["recipient_email"] == "tibor.girschele@gmail.com"
    assert "https://myexternalbrain.com/workspace-access/" in str(sent[0]["body_text"])
    assert "It is not your app login." in str(sent[0]["body_text"])
    sessions = product.list_workspace_access_sessions(principal_id=principal_id, status="active", limit=10)
    assert sessions
    assert sessions[0]["default_target"] == "/app/settings/access"


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
    assert access_body["default_target"] == "/app/properties"
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
    assert opened_access_external.headers["location"] == "/app/properties"
    opened_access_today = client.get(
        access_body["access_url"],
        params={"return_to": "/app/properties"},
        follow_redirects=False,
    )
    assert opened_access_today.status_code == 303
    assert opened_access_today.headers["location"] == "/app/properties"
    opened_access = client.get(access_body["access_url"], follow_redirects=False)
    assert opened_access.status_code == 303
    assert opened_access.headers["location"] == "/app/properties"
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
    assert head_opened_access.headers["location"] == "/app/properties"
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


def test_workspace_session_cookie_secure_for_proxy_protocol_chain(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("EA_ENABLE_PUBLIC_SIGNIN", "1")
    principal_id = "exec-workspace-cookie-chain"
    client = build_product_client(principal_id=principal_id)
    start_workspace(client, mode="team", workspace_name="Cookie Protocol Team")

    access_body = client.post(
        "/app/api/workspace-access",
        json={
            "return_to": "/app/today",
            "role": "operator",
            "display_name": "Cookie check",
            "recipient_email": "ops@example.com",
        },
    ).json()
    assert access_body["access_url"].startswith("/workspace-access/")

    opened_secure = client.get(
        access_body["access_url"],
        follow_redirects=False,
        headers={"x-forwarded-proto": "http, https"},
    )
    assert opened_secure.status_code == 303
    secure_cookie = str(opened_secure.headers.get("set-cookie") or "")
    assert "ea_workspace_session=" in secure_cookie
    assert "Secure" in secure_cookie

    opened_nonsecure = client.get(
        access_body["access_url"],
        follow_redirects=False,
        headers={"x-forwarded-proto": "http, http"},
    )
    assert opened_nonsecure.status_code == 303
    nonsecure_cookie = str(opened_nonsecure.headers.get("set-cookie") or "")
    assert "ea_workspace_session=" in nonsecure_cookie
    assert "Secure" not in nonsecure_cookie


def test_property_search_run_blocks_free_plan_when_limits_exceed_free_tier() -> None:
    principal_id = "exec-property-free-gate"
    client = build_product_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Free Gate Office")

    response = client.post(
        "/app/api/signals/property/search/run",
        json={
            "selected_platforms": ["willhaben", "kalandra"],
            "property_preferences": {"preference_person_id": "self"},
            "max_results_per_source": 4,
        },
    )

    assert response.status_code == 409
    assert response.json()["error"]["details"] == "property_plan_upgrade_required:plus"


def test_property_search_run_allows_free_plan_across_multiple_platforms_when_result_cap_is_respected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    principal_id = "exec-property-free-multi-platform"
    client = build_product_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Free Multi Platform Office")

    monkeypatch.setattr(
        ProductService,
        "sync_direct_property_scout",
        lambda self, **_: {
            "generated_at": product_api_delivery_routes.now_iso(),
            "status": "processed",
            "sources_total": 2,
            "listing_total": 2,
            "review_created_total": 0,
            "review_existing_total": 0,
            "notified_total": 0,
            "tour_created_total": 0,
            "tour_existing_total": 0,
            "high_fit_total": 0,
            "watch_notified_total": 0,
            "sources": [],
        },
    )

    response = client.post(
        "/app/api/signals/property/search/run",
        json={
            "selected_platforms": ["willhaben", "kalandra"],
            "property_preferences": {"preference_person_id": "self"},
            "max_results_per_source": 2,
        },
    )

    assert response.status_code == 200, response.text


def test_property_paypal_checkout_and_capture_updates_property_commercial_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    principal_id = "exec-property-paypal"
    client = build_product_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="PropertyQuarry Office")

    monkeypatch.setattr(product_api_delivery_routes, "paypal_configured", lambda: True)
    monkeypatch.setattr(
        product_api_delivery_routes,
        "create_paypal_property_order",
        lambda **_: {
            "order_id": "ORDER-123",
            "approve_url": "https://paypal.example/approve/ORDER-123",
            "status": "created",
            "plan_key": "plus",
            "amount_eur": "29.00",
        },
    )
    monkeypatch.setattr(
        product_api_delivery_routes,
        "capture_paypal_property_order",
        lambda **_: {
            "order_id": "ORDER-123",
            "capture_id": "CAPTURE-123",
            "payment_status": "completed",
            "payer_email": "buyer@example.com",
            "amount_eur": "29.00",
        },
    )

    created = client.post(
        "/app/api/signals/property/billing/paypal/order",
        json={"plan_key": "plus"},
    )
    assert created.status_code == 200, created.text
    created_body = created.json()
    assert created_body["order_id"] == "ORDER-123"
    assert created_body["approve_url"] == "https://paypal.example/approve/ORDER-123"

    status_after_order = client.get("/v1/onboarding/property-search/preferences")
    assert status_after_order.status_code == 200
    pending = status_after_order.json()["property_search_preferences"]["property_commercial"]
    assert pending["pending_order_id"] == "ORDER-123"
    assert pending["pending_plan_key"] == "plus"

    captured = client.post(
        "/app/api/signals/property/billing/paypal/capture",
        json={"order_id": "ORDER-123", "plan_key": "plus"},
    )
    assert captured.status_code == 200, captured.text
    captured_body = captured.json()
    assert captured_body["current_plan_key"] == "plus"
    assert captured_body["payment_status"] == "completed"
    assert captured_body["capture_id"] == "CAPTURE-123"

    status_after_capture = client.get("/v1/onboarding/property-search/preferences")
    assert status_after_capture.status_code == 200
    commercial = status_after_capture.json()["property_search_preferences"]["property_commercial"]
    assert commercial["active_plan_key"] == "plus"
    assert commercial["pending_order_id"] == ""
    assert commercial["last_capture_id"] == "CAPTURE-123"
    assert commercial["last_payer_email"] == "buyer@example.com"


def test_property_payfunnels_checkout_and_webhook_activate_plus_plan(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    principal_id = "exec-property-payfunnels"
    client = build_product_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="PropertyQuarry Office")

    monkeypatch.setenv("PAYFUNNELS_PLUS_CHECKOUT_URL", "https://checkout.payfunnels.example/plus")
    monkeypatch.setenv("PAYFUNNELS_WEBHOOK_SECRET", "pf-secret")

    created = client.post(
        "/app/api/signals/property/billing/payfunnels/order",
        json={"plan_key": "plus"},
    )
    assert created.status_code == 200, created.text
    created_body = created.json()
    assert created_body["plan_key"] == "plus"
    assert created_body["approve_url"].startswith("https://checkout.payfunnels.example/plus?")
    assert created_body["amount_eur"] == "3.00"

    status_after_order = client.get("/v1/onboarding/property-search/preferences")
    assert status_after_order.status_code == 200
    pending = status_after_order.json()["property_search_preferences"]["property_commercial"]
    assert pending["pending_order_id"] == created_body["order_id"]
    assert pending["pending_plan_key"] == "plus"
    assert pending["plan_source"] == "payfunnels"

    webhook_payload = {
        "event_type": "payment.completed",
        "client_reference_id": principal_id,
        "external_id": created_body["order_id"],
        "plan_key": "plus",
        "payment_status": "completed",
        "payer_email": "buyer@example.com",
        "amount_eur": "3.00",
    }
    raw = json.dumps(webhook_payload, separators=(",", ":")).encode("utf-8")
    signature = hmac.new(b"pf-secret", raw, hashlib.sha256).hexdigest()
    webhook = client.post(
        "/app/api/signals/property/billing/payfunnels/webhook",
        content=raw,
        headers={
            "content-type": "application/json",
            "x-payfunnels-signature": signature,
        },
    )
    assert webhook.status_code == 200, webhook.text
    assert webhook.json()["current_plan_key"] == "plus"

    status_after_webhook = client.get("/v1/onboarding/property-search/preferences")
    assert status_after_webhook.status_code == 200
    commercial = status_after_webhook.json()["property_search_preferences"]["property_commercial"]
    assert commercial["active_plan_key"] == "plus"
    assert commercial["pending_order_id"] == ""
    assert commercial["last_order_id"] == created_body["order_id"]
    assert commercial["last_payer_email"] == "buyer@example.com"


def test_property_paypal_checkout_uses_propertyquarry_base_url_on_property_host(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    principal_id = "exec-property-paypal-propertyquarry-host"
    client = build_product_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="PropertyQuarry Office")

    monkeypatch.setattr(product_api_delivery_routes, "paypal_configured", lambda: True)
    observed: dict[str, object] = {}

    def _fake_create_paypal_property_order(**kwargs):
        observed.update(kwargs)
        return {
            "order_id": "ORDER-PQ-123",
            "approve_url": "https://paypal.example/approve/ORDER-PQ-123",
            "status": "created",
            "plan_key": "plus",
            "amount_eur": "29.00",
        }

    monkeypatch.setattr(
        product_api_delivery_routes,
        "create_paypal_property_order",
        _fake_create_paypal_property_order,
    )

    created = client.post(
        "/app/api/signals/property/billing/paypal/order",
        json={"plan_key": "plus"},
        headers={"host": "propertyquarry.com", "x-forwarded-host": "propertyquarry.com", "x-forwarded-proto": "https"},
    )
    assert created.status_code == 200, created.text
    assert observed["return_url"].startswith("https://propertyquarry.com/")
    assert observed["cancel_url"].startswith("https://propertyquarry.com/")


def test_property_payfunnels_checkout_uses_api_created_link_when_api_key_is_present(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    principal_id = "exec-property-payfunnels-api"
    client = build_product_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="PropertyQuarry Office")

    monkeypatch.delenv("PAYFUNNELS_PLUS_CHECKOUT_URL", raising=False)
    monkeypatch.setenv("PAYFUNNELS_API_KEY", "pf-api-key")
    monkeypatch.setenv("PAYFUNNELS_WEBHOOK_SECRET", "pf-secret")

    from app.services import property_billing as billing_service

    class _Response:
        status_code = 201

        def json(self) -> dict[str, object]:
            return {
                "id": "pflink_123",
                "url": "https://pfnl.co/test-plus-link",
            }

    observed: dict[str, object] = {}

    def _fake_post(url, headers=None, json=None, timeout=0):
        observed["url"] = url
        observed["headers"] = dict(headers or {})
        observed["json"] = dict(json or {})
        observed["timeout"] = timeout
        return _Response()

    monkeypatch.setattr(billing_service.requests, "post", _fake_post)

    created = client.post(
        "/app/api/signals/property/billing/payfunnels/order",
        json={"plan_key": "plus"},
    )
    assert created.status_code == 200, created.text
    body = created.json()
    assert body["approve_url"] == "https://pfnl.co/test-plus-link"
    assert body["status"] == "redirect"
    assert observed["url"] == "https://api.payfunnels.com/v1/paymentlinks/recurring"
    assert observed["headers"]["x-pf-api-key"] == "pf-api-key"
    payload = dict(observed["json"])
    assert payload["interval"] == "month"
    assert "PropertyQuarry Plus" in payload["title"]
    assert any(field["label"] == "pq_principal" for field in payload["additionalFields"])


def test_property_payfunnels_webhook_accepts_documented_callback_shape(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    principal_id = "exec-property-payfunnels-callback"
    client = build_product_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="PropertyQuarry Office")
    monkeypatch.setenv("PAYFUNNELS_WEBHOOK_SECRET", "pf-secret")

    title = (
        "PropertyQuarry Plus | "
        f"pq_principal:{urllib.parse.quote(principal_id, safe='')} | "
        "pq_order:pf-plus-123"
    )
    webhook_payload = {
        "invoiceTitle": title,
        "customerEmail": "buyer@example.com",
        "chargeAmount": "3.00",
        "chargeId": "ch_123",
        "invoiceId": "inv_123",
        "event_type": "payment.completed",
        "payment_status": "completed",
    }
    raw = json.dumps(webhook_payload, separators=(",", ":")).encode("utf-8")
    signature = hmac.new(b"pf-secret", raw, hashlib.sha256).hexdigest()
    webhook = client.post(
        "/app/api/signals/property/billing/payfunnels/webhook",
        content=raw,
        headers={
            "content-type": "application/json",
            "x-payfunnels-signature": signature,
        },
    )
    assert webhook.status_code == 200, webhook.text
    assert webhook.json()["current_plan_key"] == "plus"

    status_after_webhook = client.get("/v1/onboarding/property-search/preferences")
    assert status_after_webhook.status_code == 200
    commercial = status_after_webhook.json()["property_search_preferences"]["property_commercial"]
    assert commercial["active_plan_key"] == "plus"
    assert commercial["last_payer_email"] == "buyer@example.com"


def test_property_payfunnels_webhook_accepts_hidden_additional_fields_shape(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    principal_id = "exec-property-payfunnels-hidden-fields"
    client = build_product_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="PropertyQuarry Office")
    monkeypatch.setenv("PAYFUNNELS_WEBHOOK_SECRET", "pf-secret")

    webhook_payload = {
        "additionalFields": [
            {"label": "pq_principal", "hiddenFieldValue": principal_id},
            {"label": "pq_order", "hiddenFieldValue": "pf-plus-456"},
            {"label": "pq_plan", "hiddenFieldValue": "plus"},
        ],
        "customer": {"email": "buyer@example.com"},
        "chargeAmount": "3.00",
        "status": "paid",
        "event": "checkout.completed",
    }
    raw = json.dumps(webhook_payload, separators=(",", ":")).encode("utf-8")
    signature = hmac.new(b"pf-secret", raw, hashlib.sha256).hexdigest()
    webhook = client.post(
        "/app/api/signals/property/billing/payfunnels/webhook",
        content=raw,
        headers={
            "content-type": "application/json",
            "x-payfunnels-signature": signature,
        },
    )
    assert webhook.status_code == 200, webhook.text
    assert webhook.json()["current_plan_key"] == "plus"

    status_after_webhook = client.get("/v1/onboarding/property-search/preferences")
    assert status_after_webhook.status_code == 200
    commercial = status_after_webhook.json()["property_search_preferences"]["property_commercial"]
    assert commercial["active_plan_key"] == "plus"
    assert commercial["last_order_id"] == "pf-plus-456"


def test_property_investment_comp_samples_filter_to_matching_location(monkeypatch: pytest.MonkeyPatch) -> None:
    candidate_urls = [
        "https://example.test/rent-linz",
        "https://example.test/rent-vienna-1",
        "https://example.test/rent-vienna-2",
    ]

    monkeypatch.setattr(
        product_service,
        "generated_property_source_specs",
        lambda *, preferences, selected_platforms=(): (
            {
                "platform": "willhaben",
                "label": "Willhaben | Austria | Rent | 1160 Wien",
                "url": "https://example.test/search",
            },
        ),
    )
    monkeypatch.setattr(product_service, "_property_scout_fetch_html", lambda *args, **kwargs: "<html></html>")
    monkeypatch.setattr(product_service, "_property_scout_extract_listing_urls", lambda **kwargs: list(candidate_urls))

    previews = {
        "https://example.test/rent-linz": {
            "title": "Flat in Linz, 55 m², € 700,-, (4020 Linz)",
            "summary": "Linz sample",
            "property_facts_json": {"area_m2": 55.0, "total_rent_eur": 700.0, "postal_name": "4020 Linz"},
            "media_urls_json": [],
        },
        "https://example.test/rent-vienna-1": {
            "title": "Apartment in Ottakring, 60 m², € 990,-, (1160 Wien)",
            "summary": "Vienna comp one",
            "property_facts_json": {"area_m2": 60.0, "total_rent_eur": 990.0, "postal_name": "1160 Wien"},
            "media_urls_json": [],
        },
        "https://example.test/rent-vienna-2": {
            "title": "Apartment in Währing, 63 m², € 1.050,-, (1180 Wien)",
            "summary": "Vienna comp two",
            "property_facts_json": {"area_m2": 63.0, "total_rent_eur": 1050.0, "postal_name": "1180 Wien"},
            "media_urls_json": [],
        },
    }

    monkeypatch.setattr(product_service, "_property_scout_page_preview", lambda url, prefer_fast=False: dict(previews[url]))
    monkeypatch.setattr(
        product_service,
        "_merge_property_facts_with_source_research",
        lambda *, property_url, property_facts, image_urls=(): dict(property_facts),
    )

    samples = product_service._property_investment_comp_samples(
        property_url="https://example.test/current-buy",
        country_code="AT",
        listing_mode="rent",
        location_query="1160 Wien",
        selected_platforms=("willhaben",),
        max_samples=5,
    )

    assert len(samples) == 1
    assert samples[0]["property_url"] == "https://example.test/rent-vienna-1"


def test_property_investment_text_enrichment_prefers_larger_area_when_title_mentions_terrace() -> None:
    enriched = product_service._property_enrich_facts_from_listing_text(
        facts={},
        title="Maisonette with terrace, 127 m², terrace 37 m², € 2.667,72, (1030 Wien)",
        summary="",
        listing_mode="rent",
    )

    assert enriched["area_m2"] == 127.0
