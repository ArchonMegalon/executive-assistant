from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Mapping

SUPPORTED_TELEGRAM_BUSINESS_UPDATES = (
    "business_connection",
    "business_message",
    "edited_business_message",
    "deleted_business_messages",
)
CONTRACT_NAME = "ea.telegram_business_signal_candidate.v1"
CHANNEL = "telegram_business"
EVENT_TYPE_SIGNAL_CANDIDATE = "telegram_business.signal_candidate"
EVENT_TYPE_BLOCKED_UPDATE = "telegram_business.update_blocked"


@dataclass(frozen=True)
class TelegramBusinessCandidateResult:
    status: str
    update_type: str
    chat_scope: str
    candidate: dict[str, object]
    source_id: str
    external_id: str
    dedupe_key: str
    event_type: str


def allowed_updates() -> list[str]:
    return list(SUPPORTED_TELEGRAM_BUSINESS_UPDATES)


def env_allowed_chat_ids() -> set[str]:
    return _split_env_set("EA_TELEGRAM_BUSINESS_ALLOWED_CHAT_IDS")


def env_allowed_chat_hashes() -> set[str]:
    return _split_env_set("EA_TELEGRAM_BUSINESS_ALLOWED_CHAT_HASHES")


def env_allowed_chat_labels() -> set[str]:
    return _split_label_env_set("EA_TELEGRAM_BUSINESS_ALLOWED_CHAT_LABELS")


def normalize_telegram_business_update(
    update: Mapping[str, object],
    *,
    allowed_chat_ids: set[str] | None = None,
    allowed_chat_hashes: set[str] | None = None,
    allowed_chat_labels: set[str] | None = None,
    hash_salt: str = "",
    received_at: str = "",
    preview_chars: int | None = None,
) -> TelegramBusinessCandidateResult:
    payload = dict(update or {})
    update_type, update_body = _extract_supported_update(payload)
    observed_at = _normalize_received_at(received_at)
    if not update_type:
        return TelegramBusinessCandidateResult(
            status="ignored_unsupported_update",
            update_type="unsupported",
            chat_scope="unsupported",
            candidate={
                "contract_name": CONTRACT_NAME,
                "source": "telegram_business",
                "update_type": "unsupported",
                "received_at": observed_at,
                "signal_type": "ignored",
                "ignored_reason": "unsupported_update_type",
                "supported_update_types": allowed_updates(),
                "human_review_required": False,
                "memory_candidate_allowed": False,
                "reply_allowed": False,
                "raw_payload_exposed": False,
                "raw_chat_id_exposed": False,
                "raw_sender_id_exposed": False,
            },
            source_id="telegram_business",
            external_id=str(payload.get("update_id") or "").strip(),
            dedupe_key=_dedupe_key(update_id=str(payload.get("update_id") or ""), update_type="unsupported"),
            event_type=EVENT_TYPE_BLOCKED_UPDATE,
        )

    chat_id = _chat_id(update_type=update_type, body=update_body)
    chat_id_hash = _hash_identifier(chat_id, salt=hash_salt)
    chat_label_key = _chat_label_key(update_type=update_type, body=update_body)
    allowed_ids = set(allowed_chat_ids or set())
    allowed_hashes = set(allowed_chat_hashes or set())
    allowed_labels = {_normalize_label(item) for item in set(allowed_chat_labels or set()) if _normalize_label(item)}
    allowlisted = bool(chat_id) and (
        chat_id in allowed_ids or chat_id_hash in allowed_hashes or bool(chat_label_key and chat_label_key in allowed_labels)
    )
    update_id = str(payload.get("update_id") or "").strip()
    message_id = _message_id(update_type=update_type, body=update_body)
    external_id = message_id or update_id
    source_id = f"telegram_business:{chat_id_hash}" if chat_id_hash else "telegram_business"
    dedupe_key = _dedupe_key(
        update_id=update_id,
        update_type=update_type,
        chat_id_hash=chat_id_hash,
        message_id=message_id,
    )

    base: dict[str, object] = {
        "contract_name": CONTRACT_NAME,
        "source": "telegram_business",
        "update_type": update_type,
        "chat_scope": "allowlisted" if allowlisted else "blocked",
        "chat_id_hash": chat_id_hash,
        "message_id": message_id,
        "update_id": update_id,
        "received_at": observed_at,
        "attachment_refs": [],
        "signal_type": "candidate" if allowlisted else "ignored",
        "human_review_required": bool(allowlisted),
        "memory_candidate_allowed": False,
        "reply_allowed": False,
        "raw_payload_exposed": False,
        "raw_chat_id_exposed": False,
        "raw_sender_id_exposed": False,
        "retention_policy": "candidate_until_review",
        "allowed_review_outcomes": [
            "decision",
            "commitment",
            "draft",
            "evidence",
            "people_memory_candidate",
            "ignore",
            "mute_chat_or_contact",
        ],
    }
    if not allowlisted:
        base.update(
            {
                "ignored_reason": "chat_not_allowlisted",
                "text_preview": "",
                "sender_label": "redacted",
                "attachment_refs": [],
            }
        )
        return TelegramBusinessCandidateResult(
            status="ignored_not_allowlisted",
            update_type=update_type,
            chat_scope="blocked",
            candidate=base,
            source_id=source_id,
            external_id=external_id,
            dedupe_key=dedupe_key,
            event_type=EVENT_TYPE_BLOCKED_UPDATE,
        )

    sender_label, sender_hash = _sender_fields(update_body, salt=hash_salt)
    base.update(
        {
            "text_preview": _text_preview(update_type=update_type, body=update_body, limit=preview_chars),
            "sender_label": sender_label,
            "sender_ref_hash": sender_hash,
            "attachment_refs": _attachment_refs(update_body, salt=hash_salt),
            "business_connection_id_hash": _hash_identifier(
                str(update_body.get("business_connection_id") or ""), salt=hash_salt
            ),
            "review_state": "pending_human_review",
            "operator_policy": "read_only_first_no_reply_without_review",
        }
    )
    return TelegramBusinessCandidateResult(
        status="signal_candidate",
        update_type=update_type,
        chat_scope="allowlisted",
        candidate=base,
        source_id=source_id,
        external_id=external_id,
        dedupe_key=dedupe_key,
        event_type=EVENT_TYPE_SIGNAL_CANDIDATE,
    )


def _split_env_set(key: str) -> set[str]:
    raw = str(os.getenv(key) or "").strip()
    if not raw:
        return set()
    return {item.strip() for item in re.split(r"[\s,]+", raw) if item.strip()}


def _split_label_env_set(key: str) -> set[str]:
    raw = str(os.getenv(key) or "").strip()
    if not raw:
        return set()
    return {_normalize_label(item) for item in re.split(r"[,;\n]+", raw) if _normalize_label(item)}


def _extract_supported_update(update: Mapping[str, object]) -> tuple[str, dict[str, object]]:
    for key in SUPPORTED_TELEGRAM_BUSINESS_UPDATES:
        value = update.get(key)
        if isinstance(value, dict):
            return key, dict(value)
    return "", {}


def _chat_id(*, update_type: str, body: Mapping[str, object]) -> str:
    if update_type == "business_connection":
        user = body.get("user")
        return str(dict(user).get("id") or "").strip() if isinstance(user, dict) else ""
    if update_type == "deleted_business_messages":
        chat = body.get("chat")
        return str(dict(chat).get("id") or "").strip() if isinstance(chat, dict) else ""
    chat = body.get("chat")
    return str(dict(chat).get("id") or "").strip() if isinstance(chat, dict) else ""


def _message_id(*, update_type: str, body: Mapping[str, object]) -> str:
    if update_type == "deleted_business_messages":
        ids = [str(item or "").strip() for item in list(body.get("message_ids") or []) if str(item or "").strip()]
        return ",".join(ids[:20])
    return str(body.get("message_id") or body.get("id") or "").strip()


def _chat_label_key(*, update_type: str, body: Mapping[str, object]) -> str:
    if update_type == "business_connection":
        user = body.get("user")
        return _actor_label_key(dict(user)) if isinstance(user, dict) else ""
    chat = body.get("chat")
    if isinstance(chat, dict):
        label = _actor_label_key(dict(chat))
        if label:
            return label
    sender = body.get("from")
    return _actor_label_key(dict(sender)) if isinstance(sender, dict) else ""


def _actor_label_key(actor: Mapping[str, object]) -> str:
    title = str(actor.get("title") or "").strip()
    if title:
        return _normalize_label(title)
    username = str(actor.get("username") or "").strip()
    if username:
        return _normalize_label(username.removeprefix("@"))
    name = " ".join(
        item
        for item in (
            str(actor.get("first_name") or "").strip(),
            str(actor.get("last_name") or "").strip(),
        )
        if item
    ).strip()
    return _normalize_label(name)


def _normalize_label(value: str) -> str:
    return " ".join(str(value or "").strip().casefold().split())


def _sender_fields(body: Mapping[str, object], *, salt: str) -> tuple[str, str]:
    sender = body.get("from")
    if not isinstance(sender, dict):
        sender = body.get("user") if isinstance(body.get("user"), dict) else {}
    sender_dict = dict(sender or {})
    sender_id = str(sender_dict.get("id") or "").strip()
    name = " ".join(
        item
        for item in (
            str(sender_dict.get("first_name") or "").strip(),
            str(sender_dict.get("last_name") or "").strip(),
        )
        if item
    ).strip()
    username = str(sender_dict.get("username") or "").strip()
    sender_hash = _hash_identifier(sender_id or username or name, salt=salt)
    if name:
        return "known_contact_or_redacted", sender_hash
    if username or sender_id:
        return "known_contact_or_redacted", sender_hash
    return "redacted", ""


def _text_preview(*, update_type: str, body: Mapping[str, object], limit: int | None) -> str:
    if update_type == "deleted_business_messages":
        return ""
    text = str(body.get("text") or body.get("caption") or "").strip()
    max_chars = max(0, int(limit if limit is not None else _preview_chars()))
    if max_chars <= 0:
        return ""
    return " ".join(text.split())[:max_chars]


def _preview_chars() -> int:
    raw = str(os.getenv("EA_TELEGRAM_BUSINESS_TEXT_PREVIEW_CHARS") or "240").strip()
    try:
        return max(0, min(int(raw or "240"), 2000))
    except Exception:
        return 240


def _attachment_refs(body: Mapping[str, object], *, salt: str) -> list[dict[str, object]]:
    refs: list[dict[str, object]] = []
    for kind in ("photo", "document", "audio", "voice", "video", "sticker", "animation"):
        value = body.get(kind)
        if not value:
            continue
        if kind == "photo" and isinstance(value, list):
            file_ids = [
                str(dict(item).get("file_unique_id") or dict(item).get("file_id") or "").strip()
                for item in value
                if isinstance(item, dict)
            ]
            refs.append({"kind": kind, "count": len(file_ids), "file_ref_hashes": _hashed_nonempty(file_ids, salt=salt)[:3]})
            continue
        if isinstance(value, dict):
            file_ref = str(value.get("file_unique_id") or value.get("file_id") or "").strip()
            refs.append(
                {
                    "kind": kind,
                    "count": 1,
                    "file_ref_hashes": _hashed_nonempty([file_ref], salt=salt),
                    "file_name_present": bool(str(value.get("file_name") or "").strip()),
                    "mime_type": str(value.get("mime_type") or "").strip(),
                }
            )
    return refs


def _hashed_nonempty(values: list[str], *, salt: str) -> list[str]:
    return [_hash_identifier(value, salt=salt) for value in values if str(value or "").strip()]


def _hash_identifier(value: str, *, salt: str = "") -> str:
    normalized = str(value or "").strip()
    if not normalized:
        return ""
    prefix = str(salt or "").strip()
    material = f"{prefix}:{normalized}" if prefix else normalized
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _normalize_received_at(value: str) -> str:
    normalized = str(value or "").strip()
    return normalized or datetime.now(timezone.utc).isoformat()


def _dedupe_key(*, update_id: str, update_type: str, chat_id_hash: str = "", message_id: str = "") -> str:
    parts = ["telegram_business", str(update_type or "").strip()]
    for value in (str(update_id or "").strip(), str(chat_id_hash or "").strip(), str(message_id or "").strip()):
        if value:
            parts.append(value)
    return ":".join(parts)
