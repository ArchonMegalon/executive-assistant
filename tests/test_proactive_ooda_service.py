from __future__ import annotations

import json

from app.services.proactive_ooda_service import (
    JsonOodaStateStore,
    ProactiveOodaService,
    build_run_receipt,
    format_telegram_digest,
)


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
    assert "If ignored:" in sent[0][1]
    assert "Evidence:" in sent[0][1]


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
    assert item.external_action_policy == "Do not send externally without approval."
    assert "ooda:reviewed" in item.evidence
    assert "tag:launch" in item.evidence


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

    assert text.startswith("EA OODA")
    assert "Why:" in text
    assert "Decision:" in text
    assert "Action:" in text
    assert "Guardrail:" in text
    assert "Evidence:" in text
    assert "checks" not in text.lower()
