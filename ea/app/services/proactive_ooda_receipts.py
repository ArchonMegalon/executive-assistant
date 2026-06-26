from __future__ import annotations

import hashlib
import os
import uuid
from dataclasses import asdict
from typing import Any, Mapping

from app.services.proactive_ooda_service import ProactiveOodaDigest, ProactiveOodaRunReceipt


RECEIPT_EVENT_TYPE = "proactive_ooda.run_receipt"
SAFE_STAGE_KIND_LABELS = {
    "approval_link",
    "approval_packet",
    "booking_candidate",
    "cart_draft",
    "draft_reply",
    "research_packet",
    "shortlist",
    "source_health",
}


def persist_proactive_ooda_receipt(
    *,
    principal_id: str,
    digest: ProactiveOodaDigest,
    receipt: ProactiveOodaRunReceipt,
    database_url: str | None = None,
) -> str:
    url = str(database_url or os.getenv("DATABASE_URL") or "").strip()
    if not url:
        return ""
    try:
        import psycopg
    except Exception:
        return ""
    record = build_proactive_ooda_receipt_observation(principal_id=principal_id, digest=digest, receipt=receipt)
    try:
        with psycopg.connect(url, connect_timeout=5) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    insert into observation_events (
                        observation_id,
                        principal_id,
                        channel,
                        event_type,
                        payload_json,
                        created_at,
                        source_id,
                        external_id,
                        dedupe_key,
                        auth_context_json,
                        raw_payload_uri
                    )
                    values (%s, %s, %s, %s, %s::jsonb, %s, %s, %s, %s, %s::jsonb, %s)
                    on conflict (observation_id) do nothing
                    """,
                    (
                        record["observation_id"],
                        record["principal_id"],
                        record["channel"],
                        record["event_type"],
                        record["payload_json"],
                        record["created_at"],
                        record["source_id"],
                        record["external_id"],
                        record["dedupe_key"],
                        record["auth_context_json"],
                        record["raw_payload_uri"],
                    ),
                )
        return str(record["observation_id"])
    except Exception:
        return ""


def build_proactive_ooda_receipt_observation(
    *,
    principal_id: str,
    digest: ProactiveOodaDigest,
    receipt: ProactiveOodaRunReceipt,
) -> dict[str, str]:
    payload = proactive_ooda_receipt_payload(digest=digest, receipt=receipt)
    dedupe_key = _receipt_dedupe_key(receipt)
    return {
        "observation_id": f"proactive-ooda-receipt-{uuid.uuid4().hex}",
        "principal_id": principal_id,
        "channel": "system",
        "event_type": RECEIPT_EVENT_TYPE,
        "payload_json": _json_dumps(payload),
        "created_at": receipt.generated_at,
        "source_id": "ea-proactive-ooda",
        "external_id": dedupe_key,
        "dedupe_key": dedupe_key,
        "auth_context_json": "{}",
        "raw_payload_uri": "",
    }


def proactive_ooda_receipt_payload(
    *,
    digest: ProactiveOodaDigest,
    receipt: ProactiveOodaRunReceipt,
) -> dict[str, Any]:
    payload = asdict(receipt)
    payload["event_type"] = RECEIPT_EVENT_TYPE
    payload["digest_item_count"] = len(digest.items)
    payload["notification_status"] = receipt.notification_status
    payload["deferred_reason"] = receipt.error_code if receipt.notification_status == "deferred" else ""
    payload["privacy"] = {
        "raw_principal_id_stored": False,
        "raw_chat_id_stored": False,
        "raw_message_text_stored": False,
        "raw_signal_ref_stored": False,
    }
    payload["item_summaries"] = [
        {
            "priority": item.priority,
            "approval_required": item.approval_required,
            "signal_ref_hash": _hash_value(item.signal_ref),
            "action_plan_count": len(item.action_plan),
            "has_stage": bool(item.stage_kind or item.stage_summary or item.stage_artifacts),
            "stage_kind": _safe_stage_kind(item.stage_kind),
            "stage_kind_hash": _hash_value(item.stage_kind) if item.stage_kind else "",
            "stage_summary_present": bool(item.stage_summary),
            "stage_artifact_count": len(item.stage_artifacts),
            "approval_gate_hash": _hash_value(item.approval_gate) if item.approval_gate else "",
            "external_action_policy_hash": _hash_value(item.external_action_policy) if item.external_action_policy else "",
        }
        for item in digest.items
    ]
    return payload


def _receipt_dedupe_key(receipt: ProactiveOodaRunReceipt) -> str:
    material = "|".join(
        (
            receipt.generated_at,
            receipt.notification_status,
            receipt.principal_id_hash,
            ",".join(receipt.notified_ref_hashes),
            ",".join(receipt.telegram_message_ids),
        )
    )
    return f"proactive-ooda-receipt:{_hash_value(material)}"


def _hash_value(value: str) -> str:
    return hashlib.sha256(str(value or "").encode("utf-8")).hexdigest()


def _safe_stage_kind(value: str) -> str:
    normalized = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    if not normalized:
        return ""
    return normalized if normalized in SAFE_STAGE_KIND_LABELS else "custom"


def _json_dumps(payload: Mapping[str, Any]) -> str:
    import json

    return json.dumps(payload, sort_keys=True)
