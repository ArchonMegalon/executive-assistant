from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from app.services import whatsapp_delivery_router


def _parse_isoish_datetime(value: object) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except Exception:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _safe_int(value: object, default: int = 0) -> int:
    try:
        parsed = int(value or default)
    except Exception:
        return default
    return max(0, parsed)


def _lookup_binding(tool_runtime: Any, binding_id: str) -> Any | None:
    if not binding_id or tool_runtime is None or not hasattr(tool_runtime, "get_connector_binding"):
        return None
    try:
        return tool_runtime.get_connector_binding(binding_id)
    except Exception:
        return None


def drain_whatsapp_delivery_outbox(
    *,
    container,
    observed_at: datetime | None = None,
    limit: int = 400,
    min_age_seconds: float = 2.0,
    max_attempts: int = 3,
    retry_backoff_seconds: float = 1.0,
) -> dict[str, object]:
    drained = 0
    pending = 0
    skipped = 0
    errors = 0
    dead_lettered = 0
    now = (observed_at or datetime.now(timezone.utc)).astimezone(timezone.utc)
    channel_runtime = container.channel_runtime
    tool_runtime = getattr(container, "tool_runtime", None)

    for row in channel_runtime.list_pending_delivery(limit=limit):
        if str(getattr(row, "channel", "") or "").strip() != "whatsapp":
            continue

        principal_id = str(getattr(row, "principal_id", "") or "").strip()
        recipient = str(getattr(row, "recipient", "") or "").strip()
        content = str(getattr(row, "content", "") or "")
        if not principal_id or not recipient or not content:
            skipped += 1
            continue

        created_at = _parse_isoish_datetime(getattr(row, "created_at", "") or "")
        if created_at is None:
            skipped += 1
            continue
        if max((now - created_at).total_seconds(), 0.0) < max(float(min_age_seconds), 0.0):
            pending += 1
            continue

        metadata = dict(getattr(row, "metadata", {}) or {})
        binding_id = str(metadata.get("binding_id") or "").strip()
        buttons = metadata.get("buttons") or metadata.get("inline_buttons")
        heyy_ai_key = str(metadata.get("heyy_ai_key") or metadata.get("ai_key") or metadata.get("persona_key") or "").strip()
        heyy_ai_name = str(metadata.get("heyy_ai_name") or metadata.get("ai_name") or metadata.get("persona_name") or "").strip()
        binding = _lookup_binding(tool_runtime, binding_id)
        attempt_count = _safe_int(getattr(row, "attempt_count", 0), default=0)

        try:
            receipt = whatsapp_delivery_router.send_whatsapp_delivery_text(
                tool_runtime=tool_runtime,
                principal_id=principal_id,
                recipient=recipient,
                text=content,
                binding_id=binding_id,
                binding=binding,
                buttons=buttons,
                heyy_ai_key=heyy_ai_key,
                heyy_ai_name=heyy_ai_name,
            )
            channel_runtime.mark_delivery_sent(
                str(row.delivery_id),
                principal_id=principal_id,
                receipt_json={
                    "channel": "whatsapp",
                    "binding_id": receipt.binding_id,
                    "connector_name": receipt.connector_name,
                    "delivery_transport": receipt.delivery_transport,
                    "external_account_ref": receipt.external_account_ref,
                    "recipient": receipt.recipient,
                    "message_ids": list(receipt.message_ids),
                    "request_url": receipt.request_url,
                    "binding_status": receipt.binding_status,
                },
            )
            drained += 1
        except Exception:
            exhausted = attempt_count + 1 >= max(1, int(max_attempts))
            if exhausted:
                channel_runtime.mark_delivery_failed(
                    str(row.delivery_id),
                    principal_id=principal_id,
                    error="whatsapp_delivery_retry_limit_reached",
                    dead_letter=True,
                )
                dead_lettered += 1
                continue

            delay_seconds = max(float(retry_backoff_seconds), 0.0) * (2.0 ** max(0, attempt_count))
            channel_runtime.mark_delivery_failed(
                str(row.delivery_id),
                principal_id=principal_id,
                error="whatsapp_send_failed",
                next_attempt_at=(now + timedelta(seconds=max(1.0, delay_seconds))).isoformat(),
                dead_letter=False,
            )
            errors += 1

    return {
        "ran": True,
        "drained": drained,
        "pending": pending,
        "skipped": skipped,
        "errors": errors,
        "dead_lettered": dead_lettered,
    }
