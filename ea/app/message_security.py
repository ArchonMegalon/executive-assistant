from __future__ import annotations

import json
import os
from typing import Any

from app.config import get_tenant


def _value(obj: Any, key: str, default: Any = "") -> Any:
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def household_confidence_for_message(chat_id: int, msg: dict) -> float:
    try:
        override = (os.getenv("EA_HOUSEHOLD_CONFIDENCE_OVERRIDE", "") or "").strip()
        if override:
            return max(0.0, min(1.0, float(override)))
    except Exception:
        pass
    confidence = 0.99
    chat_type = str((msg.get("chat") or {}).get("type") or "").lower()
    if chat_type in ("group", "supergroup", "channel"):
        confidence = min(confidence, 0.70)
    if msg.get("forward_origin") or msg.get("forward_from") or msg.get("forward_from_chat"):
        confidence = min(confidence, 0.70)
    sender_id = str((msg.get("from") or {}).get("id") or "")
    if sender_id and sender_id != str(chat_id):
        confidence = min(confidence, 0.75)
    return confidence


def message_document_ref(chat_id: int, msg: dict, doc: dict | None, photo: list | None) -> tuple[str, str]:
    file_id = ""
    if doc and doc.get("file_id"):
        file_id = str(doc.get("file_unique_id") or doc.get("file_id") or "")
    elif photo and isinstance(photo, list):
        last = photo[-1] if photo else {}
        file_id = str(last.get("file_unique_id") or last.get("file_id") or "")
    message_id = str(msg.get("message_id") or "0")
    document_id = file_id or f"chat{chat_id}_msg{message_id}"
    raw_ref = f"telegram:chat:{chat_id}:message:{message_id}:file:{file_id or 'none'}"
    return document_id, raw_ref


async def check_security(chat_id: int) -> tuple[str | None, dict | None]:
    tenant = get_tenant(chat_id)
    if tenant:
        key = str(_value(tenant, "key", f"chat_{chat_id}"))
        return (key, tenant)
    try:
        if os.path.exists("/attachments/dynamic_users.json"):
            with open("/attachments/dynamic_users.json", "r", encoding="utf-8") as f:
                dt = json.load(f)
            if str(chat_id) in dt:
                u_info = dt[str(chat_id)]
                default_openclaw = os.environ.get("EA_DEFAULT_OPENCLAW_CONTAINER", "openclaw-gateway")
                return (
                    f"guest_{chat_id}",
                    {
                        "key": f"guest_{chat_id}",
                        "label": u_info.get("name", "Guest"),
                        "google_account": u_info.get("email", ""),
                        "openclaw_container": default_openclaw,
                        "is_admin": u_info.get("is_admin", False),
                    },
                )
    except Exception:
        pass
    return (None, None)
