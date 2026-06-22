from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import shutil
import time
import urllib.request
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from app.services import audiobook_epub_pipeline


CONTRACT_NAME = "ea.audiobook_access_approval.v1"
CALLBACK_PREFIX = "aa"
_SAFE_FILENAME_RE = re.compile(r"[^A-Za-z0-9._()\\[\\] -]+")


def _now() -> datetime:
    return datetime.now(UTC)


def _now_iso() -> str:
    return _now().isoformat().replace("+00:00", "Z")


def _sha(value: object) -> str:
    return hashlib.sha256(str(value or "").encode("utf-8")).hexdigest()


def _env_bool(name: str, default: bool) -> bool:
    raw = str(os.getenv(name) or "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int, *, minimum: int = 1, maximum: int = 3650 * 86400) -> int:
    raw = str(os.getenv(name) or "").strip()
    try:
        value = int(float(raw or str(default)))
    except Exception:
        value = default
    return max(min(value, maximum), minimum)


def _split_env_values(raw: str) -> tuple[str, ...]:
    values: list[str] = []
    for item in re.split(r"[,\n\r\t ]+", str(raw or "")):
        normalized = item.strip()
        if normalized and normalized not in values:
            values.append(normalized)
    return tuple(values)


def _env_values(*names: str) -> tuple[str, ...]:
    values: list[str] = []
    for name in names:
        for item in _split_env_values(str(os.getenv(name) or "")):
            if item not in values:
                values.append(item)
        file_path = str(os.getenv(f"{name}_FILE") or "").strip()
        if file_path:
            try:
                content = Path(file_path).expanduser().read_text(encoding="utf-8")
            except OSError:
                content = ""
            for item in _split_env_values(content):
                if item not in values:
                    values.append(item)
    return tuple(values)


def _split_env_records(raw: str) -> tuple[str, ...]:
    values: list[str] = []
    for item in re.split(r"[,\n\r\t]+", str(raw or "")):
        normalized = " ".join(item.strip().split())
        if normalized and normalized not in values:
            values.append(normalized)
    return tuple(values)


def _env_records(*names: str) -> tuple[str, ...]:
    values: list[str] = []
    for name in names:
        for item in _split_env_records(str(os.getenv(name) or "")):
            if item not in values:
                values.append(item)
        file_path = str(os.getenv(f"{name}_FILE") or "").strip()
        if file_path:
            try:
                content = Path(file_path).expanduser().read_text(encoding="utf-8")
            except OSError:
                content = ""
            for item in _split_env_records(content):
                if item not in values:
                    values.append(item)
    return tuple(values)


def _env_secret(name: str) -> str:
    value = str(os.getenv(name) or "").strip()
    if value:
        return value
    file_path = str(os.getenv(f"{name}_FILE") or "").strip()
    if not file_path:
        return ""
    try:
        return Path(file_path).expanduser().read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def normalize_phone_number(value: object) -> str:
    normalized = str(value or "").strip()
    if normalized.startswith("wa:"):
        normalized = normalized[3:]
    return "".join(ch for ch in normalized if ch.isdigit())


def normalize_sender_ref(value: object) -> str:
    normalized = " ".join(str(value or "").strip().split())
    if not normalized:
        return ""
    lowered = normalized.lower()
    if lowered.startswith("whatsapp:"):
        digits = normalize_phone_number(normalized.split(":", 1)[1])
        return f"whatsapp:{digits}" if digits else ""
    if lowered.startswith("telegram:"):
        ref = normalized.split(":", 1)[1].strip()
        return f"telegram:{ref}" if ref else ""
    digits = normalize_phone_number(normalized)
    return digits or normalized


def approval_gate_enabled() -> bool:
    return _env_bool("EA_AUDIOBOOK_ACCESS_APPROVAL_ENABLED", True)


def _phone_whitelist() -> set[str]:
    values: set[str] = set()
    for raw in _env_records("EA_AUDIOBOOK_INSTANT_PHONE_WHITELIST"):
        if str(raw or "").strip() == "*":
            values.add("*")
            continue
        normalized = normalize_phone_number(raw)
        if normalized:
            values.add(normalized)
    return values


def _sender_whitelist() -> set[str]:
    values: set[str] = set()
    for raw in _env_records("EA_AUDIOBOOK_INSTANT_SENDER_WHITELIST"):
        normalized = normalize_sender_ref(raw)
        if normalized:
            values.add(normalized)
    return values


def is_instant_sender(
    *,
    phone_number: object = "",
    sender_ref: object = "",
    channel: str = "",
) -> bool:
    if not approval_gate_enabled():
        return True
    phone = normalize_phone_number(phone_number)
    sender = normalize_sender_ref(sender_ref)
    phone_whitelist = _phone_whitelist()
    sender_whitelist = _sender_whitelist()
    if "*" in phone_whitelist or "*" in sender_whitelist:
        return True
    if phone and phone in phone_whitelist:
        return True
    if sender and sender in sender_whitelist:
        return True
    normalized_channel = str(channel or "").strip().lower()
    if normalized_channel and phone and f"{normalized_channel}:{phone}" in sender_whitelist:
        return True
    return False


def approval_required(
    *,
    phone_number: object = "",
    sender_ref: object = "",
    channel: str = "",
) -> bool:
    return approval_gate_enabled() and not is_instant_sender(
        phone_number=phone_number,
        sender_ref=sender_ref,
        channel=channel,
    )


def approvals_root() -> Path:
    root = audiobook_epub_pipeline.audiobook_jobs_root() / "_access_approvals"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _safe_filename(value: object, *, fallback: str = "book", suffix: str = "") -> str:
    normalized = " ".join(str(value or "").replace("/", " ").replace("\\", " ").split()).strip()
    normalized = _SAFE_FILENAME_RE.sub("", normalized).strip(" .")
    if not normalized:
        normalized = fallback
    if len(normalized) > 96:
        normalized = normalized[:96].rstrip(" .")
    if suffix and not normalized.lower().endswith(suffix.lower()):
        normalized = f"{normalized}{suffix}"
    return normalized


def _request_path(approval_id: str) -> Path:
    safe = re.sub(r"[^A-Za-z0-9._-]+", "", str(approval_id or "").strip())
    if not safe:
        raise RuntimeError("approval_id_missing")
    return approvals_root() / f"{safe}.json"


def load_request(approval_id: str) -> dict[str, object]:
    path = _request_path(approval_id)
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except Exception:
        return {}
    return dict(loaded) if isinstance(loaded, dict) else {}


def _write_request(record: dict[str, object]) -> dict[str, object]:
    approval_id = str(record.get("approval_id") or "").strip()
    if not approval_id:
        raise RuntimeError("approval_id_missing")
    path = _request_path(approval_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(".json.tmp")
    tmp_path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp_path.replace(path)
    return record


def _copy_source_file(*, source_path: Path, approval_id: str, filename: str) -> Path:
    suffix = Path(str(filename or source_path.name)).suffix or source_path.suffix or ".epub"
    target_dir = approvals_root() / "_sources" / approval_id
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / _safe_filename(filename or source_path.name, fallback="book", suffix=suffix)
    if source_path.resolve() != target.resolve():
        shutil.copy2(source_path, target)
    return target


def create_pending_request(
    *,
    channel: str,
    principal_id: str,
    filename: str,
    source_path: Path,
    phone_number: object = "",
    sender_ref: object = "",
    chat_id: str = "",
    session_ref: str = "",
    chat_ref: str = "",
    message_id: str = "",
    file_size: int | None = None,
    mime_type: str = "",
    caption: str = "",
    requester_label: str = "",
) -> dict[str, object]:
    normalized_channel = str(channel or "").strip().lower()
    if normalized_channel not in {"telegram", "whatsapp"}:
        raise RuntimeError("approval_channel_invalid")
    if not source_path.is_file():
        raise RuntimeError("approval_source_file_missing")
    approval_id = f"apr{_now().strftime('%Y%m%dT%H%M%SZ')}{uuid.uuid4().hex[:10]}"
    staged_source = _copy_source_file(source_path=source_path, approval_id=approval_id, filename=filename)
    phone = normalize_phone_number(phone_number)
    sender = normalize_sender_ref(sender_ref or (f"{normalized_channel}:{phone}" if phone else ""))
    expires_at = _now() + timedelta(seconds=_env_int("EA_AUDIOBOOK_ACCESS_APPROVAL_TTL_SECONDS", 7 * 86400, minimum=300))
    record: dict[str, object] = {
        "contract_name": CONTRACT_NAME,
        "approval_id": approval_id,
        "status": "pending",
        "created_at": _now_iso(),
        "updated_at": _now_iso(),
        "expires_at": expires_at.isoformat().replace("+00:00", "Z"),
        "reason": "sender_not_whitelisted",
        "channel": normalized_channel,
        "principal_id": str(principal_id or "").strip(),
        "requester_label": str(requester_label or "").strip(),
        "phone_number": phone,
        "phone_number_sha256": _sha(phone) if phone else "",
        "sender_ref": sender,
        "sender_ref_sha256": _sha(sender) if sender else "",
        "source": {
            "filename": str(filename or "").strip() or staged_source.name,
            "file_size": int(file_size or staged_source.stat().st_size),
            "mime_type": str(mime_type or "").strip(),
            "source_path": str(staged_source),
            "source_sha256": audiobook_epub_pipeline._sha256_file(staged_source),  # type: ignore[attr-defined]
            "caption_sha256": _sha(caption) if str(caption or "").strip() else "",
        },
        "telegram": {
            "chat_id": str(chat_id or "").strip() if normalized_channel == "telegram" else "",
            "message_id": str(message_id or "").strip() if normalized_channel == "telegram" else "",
        },
        "whatsapp": {
            "session_ref": str(session_ref or "").strip() if normalized_channel == "whatsapp" else "",
            "chat_ref": str(chat_ref or "").strip() if normalized_channel == "whatsapp" else "",
            "message_id": str(message_id or "").strip() if normalized_channel == "whatsapp" else "",
        },
        "raw_paths_exposed_in_receipt": False,
    }
    return _write_request(record)


def find_request_for_source(
    *,
    channel: str,
    message_id: str = "",
    session_ref: str = "",
    sender_ref: object = "",
) -> dict[str, object]:
    normalized_channel = str(channel or "").strip().lower()
    normalized_message_id = str(message_id or "").strip()
    normalized_session = str(session_ref or "").strip()
    normalized_sender = normalize_sender_ref(sender_ref)
    if not normalized_channel or not normalized_message_id:
        return {}
    for path in sorted(approvals_root().glob("*.json"), key=lambda item: item.stat().st_mtime if item.exists() else 0, reverse=True):
        record = load_request(path.stem)
        if str(record.get("channel") or "").strip() != normalized_channel:
            continue
        if normalized_sender and str(record.get("sender_ref") or "").strip() != normalized_sender:
            continue
        if normalized_channel == "whatsapp":
            whatsapp = dict(record.get("whatsapp") or {})
            if str(whatsapp.get("message_id") or "").strip() != normalized_message_id:
                continue
            if normalized_session and str(whatsapp.get("session_ref") or "").strip() != normalized_session:
                continue
        else:
            telegram = dict(record.get("telegram") or {})
            if str(telegram.get("message_id") or "").strip() != normalized_message_id:
                continue
        return record
    return {}


def update_status(
    approval_id: str,
    *,
    status: str,
    decided_by: str = "",
    reason: str = "",
    job_id: str = "",
) -> dict[str, object]:
    normalized_status = str(status or "").strip().lower()
    if normalized_status not in {"pending", "approved", "denied", "started", "completed", "failed"}:
        raise RuntimeError("approval_status_invalid")
    record = load_request(approval_id)
    if not record:
        raise RuntimeError("approval_request_not_found")
    record["status"] = normalized_status
    record["updated_at"] = _now_iso()
    if normalized_status in {"approved", "denied"}:
        record["decided_at"] = _now_iso()
        record["decided_by"] = str(decided_by or "").strip()
    if reason:
        record["decision_reason"] = str(reason or "").strip()
    if job_id:
        record["job_id"] = str(job_id or "").strip()
    return _write_request(record)


def _callback_secret(*, bot_token: str = "") -> str:
    return (
        _env_secret("EA_AUDIOBOOK_ACCESS_APPROVAL_CALLBACK_SECRET")
        or _env_secret("EA_TELEGRAM_CALLBACK_SECRET")
        or str(bot_token or "").strip()
        or _env_secret("EA_TELEGRAM_BOT_TOKEN")
    )


def _base36_encode(value: int) -> str:
    alphabet = "0123456789abcdefghijklmnopqrstuvwxyz"
    normalized = max(int(value), 0)
    if normalized == 0:
        return "0"
    chars: list[str] = []
    while normalized:
        normalized, remainder = divmod(normalized, 36)
        chars.append(alphabet[remainder])
    return "".join(reversed(chars))


def _base36_decode(value: str) -> int:
    return int(str(value or "0").strip().lower(), 36)


def _approval_signature(*, secret: str, action: str, approval_id: str, approver_chat_id: str, expires_at: int) -> str:
    payload = "|".join(
        (
            CALLBACK_PREFIX,
            str(action or "").strip().lower(),
            str(approval_id or "").strip(),
            str(approver_chat_id or "").strip(),
            str(int(expires_at)),
        )
    )
    return hmac.new(str(secret or "").encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()[:10]


def encode_telegram_approval_callback(
    *,
    action: str,
    approval_id: str,
    approver_chat_id: str,
    bot_token: str = "",
    expires_at: int | None = None,
) -> str:
    normalized_action = str(action or "").strip().lower()[:1]
    normalized_id = str(approval_id or "").strip()
    normalized_chat = str(approver_chat_id or "").strip()
    secret = _callback_secret(bot_token=bot_token)
    if normalized_action not in {"a", "d"} or not normalized_id or not normalized_chat or not secret:
        return ""
    expiry = int(expires_at or (time.time() + _env_int("EA_AUDIOBOOK_ACCESS_APPROVAL_CALLBACK_TTL_SECONDS", 7 * 86400, minimum=300)))
    signature = _approval_signature(
        secret=secret,
        action=normalized_action,
        approval_id=normalized_id,
        approver_chat_id=normalized_chat,
        expires_at=expiry,
    )
    return f"{CALLBACK_PREFIX}|{normalized_action}|{normalized_id}|{_base36_encode(expiry)}|{signature}"


def decode_telegram_approval_callback(*, callback_data: str, approver_chat_id: str, bot_token: str = "") -> dict[str, object]:
    parts = str(callback_data or "").strip().split("|")
    if len(parts) != 5 or parts[0] != CALLBACK_PREFIX:
        return {"ok": False, "reason": "invalid_format"}
    _prefix, action, approval_id, expires_raw, signature = parts
    normalized_action = str(action or "").strip().lower()
    if normalized_action not in {"a", "d"}:
        return {"ok": False, "reason": "invalid_action"}
    try:
        expires_at = _base36_decode(expires_raw)
    except Exception:
        return {"ok": False, "reason": "invalid_expiry"}
    if expires_at < int(time.time()):
        return {"ok": False, "reason": "expired"}
    secret = _callback_secret(bot_token=bot_token)
    if not secret:
        return {"ok": False, "reason": "missing_secret"}
    expected = _approval_signature(
        secret=secret,
        action=normalized_action,
        approval_id=str(approval_id or "").strip(),
        approver_chat_id=str(approver_chat_id or "").strip(),
        expires_at=expires_at,
    )
    if not hmac.compare_digest(str(signature or "").strip(), expected):
        return {"ok": False, "reason": "invalid_signature"}
    return {
        "ok": True,
        "action": "approve" if normalized_action == "a" else "deny",
        "approval_id": str(approval_id or "").strip(),
        "expires_at": expires_at,
    }


def approver_telegram_chat_id() -> str:
    for name in (
        "EA_AUDIOBOOK_APPROVER_TELEGRAM_CHAT_ID",
        "EA_TELEGRAM_AUDIOBOOK_APPROVER_CHAT_ID",
        "EA_TELEGRAM_OPERATOR_CHAT_ID",
        "EA_TELEGRAM_OWNER_CHAT_ID",
        "EA_TELEGRAM_DEFAULT_CHAT_ID",
    ):
        value = str(os.getenv(name) or "").strip()
        if value:
            return value
    return ""


def approval_request_text(record: dict[str, object]) -> str:
    source = dict(record.get("source") or {})
    channel = str(record.get("channel") or "").strip() or "unknown"
    filename = str(source.get("filename") or "ebook").strip()
    requester = str(record.get("requester_label") or record.get("sender_ref") or record.get("phone_number") or "unknown sender").strip()
    phone = normalize_phone_number(record.get("phone_number") or "")
    phone_line = f"\nPhone: +{phone}" if phone else ""
    return (
        "Audiobook approval needed.\n"
        f"Source: {channel}\n"
        f"Requester: {requester}{phone_line}\n"
        f"Book file: {filename}\n"
        f"Approval id: {record.get('approval_id')}"
    )


def record_telegram_approval_delivery(
    *,
    approval_id: str,
    status: str,
    approver_chat_id: str = "",
    message_id: object = "",
    reason: str = "",
) -> dict[str, object]:
    record = load_request(approval_id)
    if not record:
        return {}
    record["approval_delivery"] = {
        "channel": "telegram",
        "status": str(status or "").strip(),
        "approver_chat_id_sha256": _sha(approver_chat_id) if str(approver_chat_id or "").strip() else "",
        "message_id_sha256": _sha(message_id) if str(message_id or "").strip() else "",
        "reason": str(reason or "").strip(),
        "delivered_at": _now_iso(),
    }
    record["updated_at"] = _now_iso()
    return _write_request(record)


def send_telegram_approval_request(
    *,
    record: dict[str, object],
    bot_token: str = "",
    approver_chat_id_value: str = "",
) -> dict[str, object]:
    token = str(bot_token or os.getenv("EA_TELEGRAM_BOT_TOKEN") or "").strip()
    chat_id = str(approver_chat_id_value or approver_telegram_chat_id()).strip()
    approval_id = str(record.get("approval_id") or "").strip()
    approve = encode_telegram_approval_callback(
        action="a",
        approval_id=approval_id,
        approver_chat_id=chat_id,
        bot_token=token,
    )
    deny = encode_telegram_approval_callback(
        action="d",
        approval_id=approval_id,
        approver_chat_id=chat_id,
        bot_token=token,
    )
    if not token or not chat_id:
        record_telegram_approval_delivery(
            approval_id=approval_id,
            status="failed",
            approver_chat_id=chat_id,
            reason="telegram_approver_not_configured",
        )
        return {"status": "failed", "reason": "telegram_approver_not_configured"}
    if not approve or not deny:
        record_telegram_approval_delivery(
            approval_id=approval_id,
            status="failed",
            approver_chat_id=chat_id,
            reason="approval_callback_encoding_failed",
        )
        return {"status": "failed", "reason": "approval_callback_encoding_failed"}
    payload = {
        "chat_id": chat_id,
        "text": approval_request_text(record),
        "reply_markup": {
            "inline_keyboard": [
                [
                    {"text": "Approve audiobook", "callback_data": approve},
                    {"text": "Deny", "callback_data": deny},
                ]
            ]
        },
    }
    request = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=_env_int("EA_AUDIOBOOK_ACCESS_APPROVAL_TELEGRAM_TIMEOUT_SECONDS", 15, minimum=3)) as response:
            body = json.loads(response.read().decode("utf-8") or "{}")
    except Exception as exc:
        reason = type(exc).__name__
        record_telegram_approval_delivery(
            approval_id=approval_id,
            status="failed",
            approver_chat_id=chat_id,
            reason=reason,
        )
        return {"status": "failed", "reason": reason}
    message_id = dict(body.get("result") or {}).get("message_id") if isinstance(body, dict) else ""
    ok = bool(dict(body).get("ok")) if isinstance(body, dict) else False
    status = "sent" if ok else "failed"
    record_telegram_approval_delivery(
        approval_id=approval_id,
        status=status,
        approver_chat_id=chat_id,
        message_id=message_id,
        reason="" if ok else "telegram_send_failed",
    )
    return {"status": status, "message_id": message_id, "reason": "" if ok else "telegram_send_failed"}


def source_path(record: dict[str, object]) -> Path:
    return Path(str(dict(record.get("source") or {}).get("source_path") or ""))
