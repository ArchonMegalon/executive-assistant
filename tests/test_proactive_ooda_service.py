from __future__ import annotations

import json

from app.services.proactive_ooda_safe_work import build_safe_work_result
from app.services.proactive_ooda_service import (
    JsonOodaStateStore,
    ProactiveOodaService,
    build_run_receipt,
    format_telegram_digest,
)
from app.services.proactive_ooda_stage_packets import build_stage_packets


def test_proactive_ooda_notifies_only_actionable_signals_and_keeps_evidence(tmp_path) -> None:
    sent: list[tuple[str, str]] = []
    service = ProactiveOodaService(
        notify=lambda principal_id, text: sent.append((principal_id, text)),
        state_store=JsonOodaStateStore(tmp_path / "ooda.json"),
    )

    digest, notification_result = service.run(
        principal_id="exec",
        signals=[
            {
                "source_ref": "gmail:FYI",
                "signal_type": "email_thread",
                "channel": "gmail",
                "title": "FYI: newsletter",
                "summary": "General reading for later.",
            },
            {
                "source_ref": "gmail:APPROVAL",
                "signal_type": "email_thread",
                "channel": "gmail",
                "title": "Approval needed for provider budget",
                "summary": "Please approve the provider renewal today.",
                "counterparty": "Ops",
            },
        ],
    )

    assert [item.signal_ref for item in digest.items] == ["gmail:APPROVAL"]
    assert notification_result is None
    assert digest.items[0].approval_required is True
    assert digest.items[0].priority == "high"
    assert "gmail:gmail:APPROVAL" in digest.items[0].evidence
    assert sent and sent[0][0] == "exec"
    assert sent[0][1].startswith("EA needs your decision")
    assert "Please decide:" in sent[0][1]
    assert "Receipts:" in sent[0][1]
    assert "gmail:gmail:APPROVAL" not in sent[0][1]


def test_proactive_ooda_treats_assistant_task_verbs_as_actionable() -> None:
    service = ProactiveOodaService()

    digest = service.build_digest(
        principal_id="exec",
        signals=[
            {
                "source_ref": "observation:alexa-history-1",
                "signal_type": "alexa_transcript",
                "channel": "product",
                "title": "Kitchen note",
                "summary": "Compare florist options for next week and stage the best candidate.",
                "counterparty": "Alexa",
            },
            {
                "source_ref": "observation:alexa-history-2",
                "signal_type": "alexa_transcript",
                "channel": "product",
                "title": "Timer note",
                "summary": "Tea timer update.",
                "counterparty": "Alexa",
            },
        ],
    )

    assert [item.signal_ref for item in digest.items] == ["observation:alexa-history-1"]
    assert digest.items[0].priority == "normal"
    assert digest.items[0].approval_required is False


def test_proactive_ooda_suppresses_low_signal_gmail_social_promotions_and_auto_alerts() -> None:
    service = ProactiveOodaService()

    digest = service.build_digest(
        principal_id="exec",
        signals=[
            {
                "source_ref": "gmail:social-update",
                "signal_type": "email_thread",
                "channel": "gmail",
                "title": "Stefan Stacher hat ein Update gepostet",
                "summary": "Stefan posted an update on a social network.",
                "counterparty": "Stefan auf Facebook",
                "payload": {"labels": ["INBOX", "CATEGORY_SOCIAL"]},
            },
            {
                "source_ref": "gmail:promo-pay",
                "signal_type": "email_thread",
                "channel": "gmail",
                "title": "Neu: Vela Pilates - die schoensten Reformer fuer zu Hause",
                "summary": "Newsletter promotion. Dutch Design Sale. Pay later and shop the newest product line.",
                "counterparty": "Westwing",
                "payload": {"labels": ["CATEGORY_PROMOTIONS"], "list_unsubscribe": "<mailto:unsubscribe@example.test>"},
            },
            {
                "source_ref": "gmail:auto-alert",
                "signal_type": "email_thread",
                "channel": "gmail",
                "title": "[Alert] Tunnel propertyquarry is now down",
                "summary": "Automated monitoring alert. Review the event in the dashboard.",
                "counterparty": "Cloudflare",
                "payload": {"auto_submitted": "auto-generated"},
            },
        ],
    )

    assert digest.items == ()


def test_proactive_ooda_suppresses_gmail_receipts_and_order_confirmations_without_action() -> None:
    service = ProactiveOodaService()

    digest = service.build_digest(
        principal_id="exec",
        signals=[
            {
                "source_ref": "gmail:paypal-receipt",
                "signal_type": "email_thread",
                "channel": "gmail",
                "title": "Beleg fuer Ihre Zahlung an AppSumo",
                "summary": "PayPal receipt. You paid AppSumo for your order.",
                "counterparty": "PayPal",
            },
            {
                "source_ref": "gmail:appsumo-order",
                "signal_type": "email_thread",
                "channel": "gmail",
                "title": "Order Confirmation: Sendr",
                "summary": "Thanks for your order. Your AppSumo purchase receipt is attached.",
                "counterparty": "AppSumo",
            },
        ],
    )

    assert digest.items == ()


def test_proactive_ooda_suppresses_product_commitment_candidates_from_receipts_without_action() -> None:
    service = ProactiveOodaService()

    digest = service.build_digest(
        principal_id="exec",
        signals=[
            {
                "source_ref": "observation:paypal-receipt",
                "signal_type": "commitment_candidate",
                "channel": "product",
                "title": "Beleg fuer Ihre Zahlung an AppSumo",
                "summary": "EA staged a commitment candidate for review.",
                "counterparty": "PayPal",
            },
            {
                "source_ref": "observation:appsumo-order",
                "signal_type": "commitment_candidate",
                "channel": "product",
                "title": "Order Confirmation: Sendr [Thanks for your order!]",
                "summary": "EA staged a commitment candidate for review.",
                "counterparty": "AppSumo",
            },
        ],
    )

    assert digest.items == ()


def test_proactive_ooda_allows_low_signal_gmail_only_when_action_is_explicit() -> None:
    service = ProactiveOodaService()

    digest = service.build_digest(
        principal_id="exec",
        signals=[
            {
                "source_ref": "gmail:promo-action-required",
                "signal_type": "email_thread",
                "channel": "gmail",
                "title": "Action required: contract signature deadline today",
                "summary": "Please approve the contract before the deadline.",
                "counterparty": "Vendor Portal",
                "payload": {"labels": ["CATEGORY_UPDATES"], "list_unsubscribe": "<mailto:unsubscribe@example.test>"},
            },
        ],
    )

    assert [item.signal_ref for item in digest.items] == ["gmail:promo-action-required"]
    assert digest.items[0].approval_required is True
    assert digest.items[0].priority == "high"


def test_proactive_ooda_dedupes_previously_notified_signals(tmp_path) -> None:
    state_path = tmp_path / "ooda.json"
    service = ProactiveOodaService(
        notify=lambda _principal_id, _text: None,
        state_store=JsonOodaStateStore(state_path),
    )
    signal = {
        "source_ref": "calendar:deadline",
        "signal_type": "calendar_note",
        "channel": "calendar",
        "title": "Launch review meeting tomorrow",
        "summary": "Bring the release decision notes.",
        "due_at": "2026-06-21T09:00:00+02:00",
    }

    first, _ = service.run(principal_id="exec", signals=[signal])
    second, _ = service.run(principal_id="exec", signals=[signal])

    assert len(first.items) == 1
    assert second.items == ()
    payload = json.loads(state_path.read_text(encoding="utf-8"))
    assert "exec" not in payload
    stored_refs = next(iter(payload.values()))
    assert stored_refs != ["calendar:deadline"]
    assert len(stored_refs[0]) == 64


def test_proactive_ooda_dedupes_hashed_refs(tmp_path) -> None:
    state_path = tmp_path / "ooda.json"
    service = ProactiveOodaService(state_store=JsonOodaStateStore(state_path))
    signal = {
        "source_ref": "calendar:deadline",
        "signal_type": "calendar_note",
        "channel": "calendar",
        "title": "Launch review meeting tomorrow",
        "summary": "Bring the release decision notes.",
    }
    first, _ = service.run(principal_id="exec", signals=[signal])
    second, _ = service.run(principal_id="exec", signals=[signal])

    assert len(first.items) == 1
    assert second.items == ()


def test_proactive_ooda_dedupes_same_external_id_across_sources_in_one_run(tmp_path) -> None:
    sent: list[tuple[str, str]] = []
    service = ProactiveOodaService(
        notify=lambda principal_id, text: sent.append((principal_id, text)),
        state_store=JsonOodaStateStore(tmp_path / "ooda.json"),
    )

    digest, _notification_result = service.run(
        principal_id="exec",
        signals=[
            {
                "source_ref": "rss:https://example.test/vendor-a",
                "external_id": "https://example.test/vendor-a",
                "signal_type": "market_signal",
                "channel": "market_watch",
                "title": "Vendor option review today",
                "summary": "Review the same vendor opportunity today.",
            },
            {
                "source_ref": "json:mirror:vendor-a",
                "external_id": "https://example.test/vendor-a",
                "signal_type": "operator_signal",
                "channel": "operator_feed",
                "title": "Vendor option review today",
                "summary": "Review the same vendor opportunity today.",
            },
        ],
    )

    assert [item.signal_ref for item in digest.items] == ["rss:https://example.test/vendor-a"]
    assert sent and sent[0][0] == "exec"


def test_proactive_ooda_dedupes_previously_notified_external_id_across_sources(tmp_path) -> None:
    state_path = tmp_path / "ooda.json"
    service = ProactiveOodaService(
        notify=lambda _principal_id, _text: None,
        state_store=JsonOodaStateStore(state_path),
    )

    first, _ = service.run(
        principal_id="exec",
        signals=[
            {
                "source_ref": "rss:https://example.test/vendor-a",
                "external_id": "https://example.test/vendor-a",
                "signal_type": "market_signal",
                "channel": "market_watch",
                "title": "Vendor option review today",
                "summary": "Review the same vendor opportunity today.",
            }
        ],
    )
    second, _ = service.run(
        principal_id="exec",
        signals=[
            {
                "source_ref": "json:mirror:vendor-a",
                "external_id": "https://example.test/vendor-a",
                "signal_type": "operator_signal",
                "channel": "operator_feed",
                "title": "Vendor option review today",
                "summary": "Review the same vendor opportunity today.",
            }
        ],
    )

    assert len(first.items) == 1
    assert second.items == ()
    payload = json.loads(state_path.read_text(encoding="utf-8"))
    serialized = json.dumps(payload, sort_keys=True)
    assert "https://example.test/vendor-a" not in serialized


def test_ooda_state_store_tracks_interruption_events_under_hashed_principal(tmp_path) -> None:
    state_path = tmp_path / "ooda.json"
    store = JsonOodaStateStore(state_path)

    store.save_notified_refs("exec", {"gmail:approval"})
    store.save_interruption_events("exec", ["2026-06-26T10:00:00+00:00"])

    payload = json.loads(state_path.read_text(encoding="utf-8"))

    assert "exec" not in payload
    assert "gmail:approval" not in json.dumps(payload, sort_keys=True)
    assert store.load_interruption_events("exec") == ("2026-06-26T10:00:00+00:00",)
    assert JsonOodaStateStore.INTERRUPTION_EVENTS_KEY in payload


def test_ooda_state_store_hashes_opportunity_rule_state_keys(tmp_path) -> None:
    state_path = tmp_path / "ooda.json"
    store = JsonOodaStateStore(state_path)

    store.save_opportunity_rule_state(
        "exec",
        "cool-weather-window",
        {"last_condition": True, "occurrence": 2, "first_matched_at": 123},
    )

    payload = json.loads(state_path.read_text(encoding="utf-8"))

    assert "exec" not in payload
    assert "cool-weather-window" not in json.dumps(payload, sort_keys=True)
    assert store.load_opportunity_rule_state("exec", "cool-weather-window") == {
        "last_condition": True,
        "occurrence": 2,
        "first_matched_at": 123,
    }
    assert JsonOodaStateStore.OPPORTUNITY_RULE_STATE_KEY in payload


def test_run_receipt_redacts_principal_and_refs() -> None:
    service = ProactiveOodaService()
    digest = service.build_digest(
        principal_id="exec",
        signals=[
            {
                "source_ref": "gmail:secret-ref",
                "signal_type": "email_thread",
                "channel": "gmail",
                "title": "Approval needed today",
                "summary": "Approve renewal.",
            }
        ],
    )

    receipt = build_run_receipt(digest=digest, dry_run=False, notification_result={"message_id": 123})

    assert receipt.notification_status == "sent"
    assert receipt.telegram_message_ids == ("123",)
    assert receipt.principal_id_hash != "exec"
    assert "gmail:secret-ref" not in receipt.notified_ref_hashes


def test_run_receipt_marks_deferred_notifications() -> None:
    service = ProactiveOodaService()
    digest = service.build_digest(
        principal_id="exec",
        signals=[
            {
                "source_ref": "opportunity:quiet",
                "signal_type": "opportunity",
                "channel": "assistant_opportunity",
                "title": "Review vendor options",
                "summary": "Review the provider notes.",
            }
        ],
    )

    receipt = build_run_receipt(digest=digest, dry_run=False, error_code="deferred_by_quiet_hours")

    assert receipt.notification_status == "deferred"
    assert receipt.error_code == "deferred_by_quiet_hours"


def test_proactive_ooda_prefers_structured_ooda_loop() -> None:
    service = ProactiveOodaService()

    digest = service.build_digest(
        principal_id="exec",
        signals=[
            {
                "source_ref": "observation:structured",
                "signal_type": "telegram_message",
                "channel": "telegram",
                "title": "Fallback title approval",
                "summary": "Fallback summary.",
                "counterparty": "Alice",
                "payload": {
                    "ooda_loop": {
                        "reviewed": True,
                        "observe": {
                            "summary": "Alice needs a budget answer today",
                            "channel": "telegram",
                        },
                        "orient": {
                            "summary": "The launch plan cannot move until this is decided",
                            "tags": ["launch", "budget"],
                        },
                        "decide": {
                            "summary": "Approve or reject the budget request",
                            "recommended_actions": ["Give a yes/no decision"],
                            "approval_required": True,
                            "ignored_consequence": "The launch budget stalls.",
                        },
                        "act": {
                            "summary": "Ask for the user's decision with the budget context",
                            "action_plan": ["Collect context", "Prepare a yes/no approval packet"],
                            "stage": {
                                "kind": "approval_packet",
                                "summary": "A budget decision packet ready for the user to approve.",
                                "artifacts": ["budget_context", "yes_no_prompt"],
                                "candidate_items": [{"label": "Approve", "risk": "Budget is committed."}],
                                "approval_url": "https://approval.example.test/decision/123",
                                "work_type": "draft",
                                "search_queries": ["budget context"],
                                "selection_criteria": ["least external risk"],
                                "approval_gate": "User must approve before any external send.",
                            },
                            "external_action_policy": "Do not send externally without approval.",
                        },
                    }
                },
            }
        ],
    )

    assert len(digest.items) == 1
    item = digest.items[0]
    assert item.observe == "Approve or reject the budget request"
    assert item.orient == "The launch plan cannot move until this is decided."
    assert item.decide == "Approve or reject the budget request."
    assert item.act == "Ask for the user's decision with the budget context."
    assert item.approval_required is True
    assert item.priority == "high"
    assert item.ignored_consequence == "The launch budget stalls."
    assert item.action_plan == ("Collect context", "Prepare a yes/no approval packet")
    assert item.stage_kind == "approval_packet"
    assert item.stage_summary == "A budget decision packet ready for the user to approve."
    assert item.stage_artifacts == ("budget_context", "yes_no_prompt")
    assert item.stage_payload is not None
    assert item.stage_payload["candidate_items"] == [{"label": "Approve", "risk": "Budget is committed."}]
    assert item.stage_payload["approval_url"] == "https://approval.example.test/decision/123"
    assert item.stage_payload["work_type"] == "draft"
    assert item.stage_payload["search_queries"] == ["budget context"]
    assert item.stage_payload["selection_criteria"] == ["least external risk"]
    assert item.approval_gate == "User must approve before any external send."
    assert item.external_action_policy == "Do not send externally without approval."
    assert "ooda:reviewed" in item.evidence
    assert "tag:launch" in item.evidence
    text = format_telegram_digest(digest)
    assert "Ready: A budget decision packet ready for the user to approve." in text
    assert "Guardrail: User must approve before any external send." in text
    assert "Artifacts:" not in text
    assert "tag:launch" not in text


def test_proactive_ooda_suppresses_internal_structured_stage_without_material() -> None:
    service = ProactiveOodaService()

    digest = service.build_digest(
        principal_id="exec",
        signals=[
            {
                "source_ref": "product:observation:commitment-review",
                "signal_type": "telegram_message",
                "channel": "product",
                "title": "Stage 1 commitment candidate.",
                "summary": "Stage 1 commitment candidate. No additional LTD lane is recommended.",
                "counterparty": "EA",
                "payload": {
                    "ooda_loop": {
                        "reviewed": True,
                        "observe": {
                            "summary": "Stage 1 commitment candidate. No additional LTD lane is recommended.",
                            "channel": "telegram",
                        },
                        "orient": {
                            "summary": "Signal was reviewed for commitments and promotion candidates.",
                        },
                        "decide": {
                            "summary": "Stage 1 commitment candidate. No additional LTD lane is recommended.",
                            "approval_required": True,
                        },
                        "act": {
                            "summary": "Staged 1 candidate and 0 reply drafts.",
                            "stage": {
                                "kind": "approval_packet",
                                "summary": "Staged 1 candidate and 0 reply drafts.",
                                "artifacts": [],
                                "deadline": "2026-06-30T09:23:51.409738+00:00",
                                "recipient_context": {"location": "1200 Wien", "country": "AT"},
                                "notes": [
                                    "1 commitment risks, 5 promotion candidates",
                                    "medium risk: Interruption budget for default is exhausted.",
                                ],
                            },
                        },
                    }
                },
            }
        ],
    )

    assert digest.items == ()


def test_proactive_ooda_suppresses_internal_structured_commitment_counter_without_stage_material() -> None:
    service = ProactiveOodaService()

    digest = service.build_digest(
        principal_id="exec",
        signals=[
            {
                "source_ref": "product:office-signal-ooda",
                "signal_type": "email_thread",
                "channel": "product",
                "title": "Stage 1 commitment candidate.",
                "summary": "Newsletter sale. Stage 1 commitment candidate. No additional LTD lane is recommended.",
                "counterparty": "Steam",
                "payload": {
                    "ooda_loop": {
                        "reviewed": True,
                        "observe": {
                            "summary": "Stage 1 commitment candidate. No additional LTD lane is recommended.",
                            "channel": "gmail",
                        },
                        "orient": {"summary": "Signal references property-search or tour work."},
                        "decide": {
                            "summary": "Stage 1 commitment candidate. No additional LTD lane is recommended.",
                            "approval_required": True,
                        },
                        "act": {
                            "summary": "Staged 1 candidate and 0 reply drafts.",
                            "executed_actions": ["commitment_candidates_staged"],
                            "automated_actions": [],
                            "staged_draft_count": 0,
                            "staged_candidate_count": 1,
                        },
                    }
                },
            }
        ],
    )

    assert digest.items == ()


def test_proactive_ooda_keeps_structured_stage_with_decision_ready_material() -> None:
    service = ProactiveOodaService()

    digest = service.build_digest(
        principal_id="exec",
        signals=[
            {
                "source_ref": "product:observation:rauchfangkehrer",
                "signal_type": "telegram_message",
                "channel": "product",
                "title": "Find a Rauchfangkehrer and draft an email.",
                "summary": "Suche einen Rauchfangkehrer und speichere einen Draft.",
                "counterparty": "Telegram",
                "payload": {
                    "ooda_loop": {
                        "reviewed": True,
                        "observe": {"summary": "Find a Rauchfangkehrer and draft an email.", "channel": "telegram"},
                        "orient": {"summary": "The request has a clear local context in 1200 Wien."},
                        "decide": {"summary": "Stage a local provider shortlist and Gmail draft.", "approval_required": True},
                        "act": {
                            "summary": "Research local providers and prepare one draft.",
                            "stage": {
                                "kind": "approval_packet",
                                "summary": "Local provider research and draft request are ready for safe work.",
                                "work_type": "draft",
                                "draft_mode": "research_backed_inquiry",
                                "request_text": (
                                    "Ask for an onsite appointment about using a Zimmerkamin as an AC exhaust path."
                                ),
                                "research_query": "Rauchfangkehrer Gutachten Zimmerkamin Abluftrohr 1200 Wien",
                                "recipient_context": {"location": "1200 Wien", "phone": "+43 664 7916419"},
                            },
                        },
                    }
                },
            }
        ],
    )

    assert len(digest.items) == 1
    assert digest.items[0].stage_payload is not None
    assert digest.items[0].stage_payload["request_text"].startswith("Ask for an onsite appointment")
    assert digest.items[0].stage_payload["research_query"] == "Rauchfangkehrer Gutachten Zimmerkamin Abluftrohr 1200 Wien"


def test_format_telegram_digest_is_minimal_but_decision_ready() -> None:
    service = ProactiveOodaService()
    digest = service.build_digest(
        principal_id="exec",
        signals=[
            {
                "source_ref": "gmail:contract",
                "signal_type": "email_thread",
                "channel": "gmail",
                "title": "Contract review due today",
                "summary": "Legal asks whether to sign.",
                "counterparty": "Legal",
            }
        ],
    )

    text = format_telegram_digest(digest)

    assert text.startswith("EA needs your decision")
    assert "Why now:" in text
    assert "Please decide:" in text
    assert "EA will:" in text
    assert "Guardrail:" in text
    assert "Receipts:" in text
    assert "Priority:" not in text
    assert "Evidence:" not in text
    assert "checks" not in text.lower()


def test_format_telegram_digest_can_embed_safe_work_preview() -> None:
    digest = ProactiveOodaService().build_digest(
        principal_id="exec",
        signals=[
            {
                "source_ref": "opportunity:vendor-approval",
                "signal_type": "opportunity",
                "channel": "assistant_opportunity",
                "title": "Prepare one vendor approval packet",
                "summary": "A reversible vendor choice is ready.",
                "payload": {
                    "ooda_loop": {
                        "reviewed": True,
                        "observe": {"summary": "Review the vendor shortlist."},
                        "orient": {"summary": "A reversible option can be staged before approval."},
                        "decide": {"summary": "Approve whether EA should proceed.", "approval_required": True},
                        "act": {
                            "summary": "Prepare the best approval link.",
                            "stage": {
                                "kind": "approval_packet",
                                "summary": "One vendor candidate ready for approval.",
                                "approval_url": "https://example.test/approve/vendor-a",
                                "candidate_items": [
                                    {"label": "Vendor A", "url": "https://example.test/vendor-a"},
                                    {"label": "Vendor B", "url": "https://example.test/vendor-b"},
                                ],
                            },
                            "external_action_policy": "Do not buy, book, send, cancel, post, or commit without explicit approval.",
                        },
                    }
                },
            }
        ],
    )
    result = build_safe_work_result(build_stage_packets(digest)[0])

    text = format_telegram_digest(digest, safe_work_results=(result,))

    assert "Ready: One vendor candidate ready for approval." in text
    assert "Recommendation: Vendor A - https://example.test/vendor-a" in text
    assert "Open: https://example.test/approve/vendor-a" in text
    assert "Options: Vendor A - https://example.test/vendor-a" in text
    assert "Please decide: Approve whether EA should proceed with this staged shortlist candidate." in text
    assert "Prepared:" not in text
    assert "Approve:" not in text


def test_format_telegram_digest_fail_closed_safe_work_does_not_ask_for_approval() -> None:
    digest = ProactiveOodaService().build_digest(
        principal_id="exec",
        signals=[
            {
                "source_ref": "opportunity:bad-provider",
                "signal_type": "opportunity",
                "channel": "assistant_opportunity",
                "title": "Prepare a vendor approval packet",
                "summary": "A vendor choice needs research before it can be reviewed.",
                "payload": {
                    "ooda_loop": {
                        "reviewed": True,
                        "observe": {"summary": "Review the vendor shortlist."},
                        "orient": {"summary": "The current search result is not decision-ready."},
                        "decide": {"summary": "Approve whether EA should proceed.", "approval_required": True},
                        "act": {
                            "summary": "Prepare the best approval link.",
                            "stage": {
                                "kind": "approval_packet",
                                "summary": "One vendor candidate ready for approval.",
                                "work_type": "compare_options",
                            },
                            "external_action_policy": "Do not buy, book, send, cancel, post, or commit without explicit approval.",
                        },
                    }
                },
            }
        ],
    )
    result = build_safe_work_result(build_stage_packets(digest)[0])

    text = format_telegram_digest(digest, safe_work_results=(result,))

    assert text.startswith("EA needs follow-up")
    assert "Blocked:" in text
    assert "Needs work: no_decision_ready_material" in text
    assert "Stop: quality_gate_failed" in text
    assert "Please decide:" not in text
    assert "Approve whether EA should research further" not in text
