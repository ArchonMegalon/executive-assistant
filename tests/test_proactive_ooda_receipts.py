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
    assert payload["telegram_message_ids"] == ("42",)
    assert payload["privacy"]["raw_principal_id_stored"] is False
    assert "cf-email:user@example.test" not in serialized
    assert "telegram:raw-source" not in serialized
    assert "Approve renewal today" not in serialized


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
