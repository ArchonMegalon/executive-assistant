from __future__ import annotations

import json

from app.services.proactive_ooda_receipts import (
    RECEIPT_EVENT_TYPE,
    build_proactive_ooda_receipt_observation,
    proactive_ooda_receipt_payload,
)
from app.services.proactive_ooda_service import ProactiveOodaService, build_run_receipt


def _digest_and_receipt():
    digest = ProactiveOodaService().build_digest(
        principal_id="cf-email:user@example.test",
        signals=[
            {
                "source_ref": "telegram:raw-source",
                "signal_type": "operator_signal",
                "channel": "telegram",
                "title": "Action required: approve renewal",
                "summary": "Approve renewal today.",
            }
        ],
    )
    receipt = build_run_receipt(digest=digest, dry_run=False, notification_result={"message_id": 42})
    return digest, receipt


def test_receipt_payload_is_redacted_and_keeps_delivery_facts() -> None:
    digest, receipt = _digest_and_receipt()

    payload = proactive_ooda_receipt_payload(digest=digest, receipt=receipt)
    serialized = json.dumps(payload, sort_keys=True)

    assert payload["event_type"] == RECEIPT_EVENT_TYPE
    assert payload["notification_status"] == "sent"
    assert payload["delivery_channel"] == "telegram"
    assert payload["delivery_message_ids"] == ("42",)
    assert payload["delivery_message_count"] == 1
    assert payload["telegram_message_ids"] == ("42",)
    assert payload["privacy"]["raw_principal_id_stored"] is False
    assert "cf-email:user@example.test" not in serialized
    assert "telegram:raw-source" not in serialized
    assert "Approve renewal today" not in serialized


def test_receipt_payload_keeps_redacted_stage_telemetry() -> None:
    digest = ProactiveOodaService().build_digest(
        principal_id="cf-email:user@example.test",
        signals=[
            {
                "source_ref": "opportunity:private-source",
                "signal_type": "opportunity",
                "channel": "assistant_opportunity",
                "title": "Private household opportunity",
                "summary": "Private summary.",
                "payload": {
                    "ooda_loop": {
                        "reviewed": True,
                        "observe": {"summary": "Private observation"},
                        "orient": {"summary": "Private orientation"},
                        "decide": {
                            "summary": "Approve staged private purchase candidate",
                            "approval_required": True,
                        },
                        "act": {
                            "summary": "Prepare private cart candidate.",
                            "action_plan": ["Private comparison"],
                            "stage": {
                                "kind": "cart_draft",
                                "summary": "Private cart with one selected item.",
                                "artifacts": ["private-cart-link", "private-approval-prompt"],
                                "approval_gate": "User must approve the private purchase.",
                            },
                            "external_action_policy": "Do not buy the private item without approval.",
                        },
                    }
                },
            }
        ],
    )
    receipt = build_run_receipt(
        digest=digest,
        dry_run=False,
        notification_result={"message_id": 42},
        stage_packet_refs=("stage_packet:private-cart-packet",),
        safe_work_result_refs=("safe_work_result:private-cart-result",),
    )

    payload = proactive_ooda_receipt_payload(digest=digest, receipt=receipt)
    item = payload["item_summaries"][0]
    serialized = json.dumps(payload, sort_keys=True)

    assert item["has_stage"] is True
    assert item["stage_kind"] == "cart_draft"
    assert len(item["stage_kind_hash"]) == 64
    assert item["stage_summary_present"] is True
    assert item["stage_artifact_count"] == 2
    assert item["action_plan_count"] == 1
    assert len(item["approval_gate_hash"]) == 64
    assert len(item["external_action_policy_hash"]) == 64
    assert payload["stage_packet_count"] == 1
    assert len(payload["stage_packet_ref_hashes"][0]) == 64
    assert payload["safe_work_result_count"] == 1
    assert len(payload["safe_work_result_ref_hashes"][0]) == 64
    assert "Private cart with one selected item" not in serialized
    assert "private-cart-link" not in serialized
    assert "private-cart-packet" not in serialized
    assert "private-cart-result" not in serialized
    assert "User must approve the private purchase" not in serialized


def test_receipt_payload_keeps_stage_packet_error_count() -> None:
    digest, _receipt = _digest_and_receipt()
    receipt = build_run_receipt(
        digest=digest,
        dry_run=False,
        notification_result={"message_id": 42},
        stage_packet_error_count=2,
    )

    payload = proactive_ooda_receipt_payload(digest=digest, receipt=receipt)

    assert payload["stage_packet_count"] == 0
    assert payload["stage_packet_error_count"] == 2


def test_receipt_payload_keeps_safe_work_result_error_count() -> None:
    digest, _receipt = _digest_and_receipt()
    receipt = build_run_receipt(
        digest=digest,
        dry_run=False,
        notification_result={"message_id": 42},
        safe_work_result_error_count=2,
    )

    payload = proactive_ooda_receipt_payload(digest=digest, receipt=receipt)

    assert payload["safe_work_result_count"] == 0
    assert payload["safe_work_result_error_count"] == 2


def test_receipt_payload_keeps_safe_deferred_reason() -> None:
    digest = ProactiveOodaService().build_digest(
        principal_id="cf-email:user@example.test",
        signals=[
            {
                "source_ref": "opportunity:private-source",
                "signal_type": "opportunity",
                "channel": "assistant_opportunity",
                "title": "Review vendor options",
                "summary": "Private vendor context.",
            }
        ],
    )
    receipt = build_run_receipt(digest=digest, dry_run=False, error_code="deferred_by_interruption_budget")

    payload = proactive_ooda_receipt_payload(digest=digest, receipt=receipt)
    serialized = json.dumps(payload, sort_keys=True)

    assert payload["notification_status"] == "deferred"
    assert payload["deferred_reason"] == "deferred_by_interruption_budget"
    assert "Private vendor context" not in serialized


def test_receipt_observation_record_matches_observation_schema() -> None:
    digest, receipt = _digest_and_receipt()

    record = build_proactive_ooda_receipt_observation(
        principal_id="cf-email:user@example.test",
        digest=digest,
        receipt=receipt,
    )

    assert record["channel"] == "system"
    assert record["event_type"] == RECEIPT_EVENT_TYPE
    assert record["principal_id"] == "cf-email:user@example.test"
    assert record["source_id"] == "ea-proactive-ooda"
    assert record["dedupe_key"].startswith("proactive-ooda-receipt:")
    assert json.loads(record["payload_json"])["notification_status"] == "sent"
