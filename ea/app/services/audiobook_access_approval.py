from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import shutil
import fcntl
import threading
import time
import urllib.request
import uuid
from contextlib import contextmanager, suppress
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Iterator

from app.services import audiobook_epub_pipeline


CONTRACT_NAME = "ea.audiobook_access_approval.v2"
START_CONTRACT_NAME = "ea.audiobook_access_approval_start.v1"
CALLBACK_PREFIX = "aa"
_SAFE_FILENAME_RE = re.compile(r"[^A-Za-z0-9._()\\[\\] -]+")
_APPROVAL_THREAD_LOCKS: dict[str, threading.RLock] = {}
_APPROVAL_THREAD_LOCKS_GUARD = threading.Lock()


def _now() -> datetime:
    return datetime.now(UTC)


def _now_iso() -> str:
    return _now().isoformat().replace("+00:00", "Z")


def _sha(value: object) -> str:
    return hashlib.sha256(str(value or "").encode("utf-8")).hexdigest()


def _canonical_sha256(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


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


def _approval_thread_lock(approval_id: str) -> threading.RLock:
    safe = re.sub(r"[^A-Za-z0-9._-]+", "", str(approval_id or "").strip())
    if not safe:
        raise RuntimeError("approval_id_missing")
    with _APPROVAL_THREAD_LOCKS_GUARD:
        return _APPROVAL_THREAD_LOCKS.setdefault(safe, threading.RLock())


@contextmanager
def _exclusive_approval_lock(approval_id: str) -> Iterator[None]:
    """Serialize one approval across threads and worker processes.

    The durable JSON state is always re-read after this lock is acquired.  The
    thread lock is required in addition to ``flock`` because multiple request
    handlers can race inside one process, while ``flock`` protects independent
    webhook and WhatsApp worker processes.
    """

    thread_lock = _approval_thread_lock(approval_id)
    with thread_lock:
        request_path = _request_path(approval_id)
        lock_path = request_path.with_suffix(".lock")
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        with lock_path.open("a+b") as handle:
            with suppress(OSError):
                lock_path.chmod(0o600)
            timeout_seconds = _env_int(
                "EA_AUDIOBOOK_ACCESS_APPROVAL_LOCK_TIMEOUT_SECONDS",
                30,
                minimum=1,
                maximum=600,
            )
            deadline = time.monotonic() + timeout_seconds
            while True:
                try:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if time.monotonic() >= deadline:
                        raise RuntimeError("approval_lock_timeout")
                    time.sleep(0.02)
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


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
    diagnostic_sha256: str = "",
    job_id: str = "",
    expected_statuses: tuple[str, ...] | None = None,
) -> dict[str, object]:
    normalized_status = str(status or "").strip().lower()
    if normalized_status not in {
        "pending",
        "approved",
        "denied",
        "starting",
        "started",
        "completed",
        "failed",
    }:
        raise RuntimeError("approval_status_invalid")
    normalized_expected = {
        str(item or "").strip().lower()
        for item in tuple(expected_statuses or ())
        if str(item or "").strip()
    }
    with _exclusive_approval_lock(approval_id):
        record = load_request(approval_id)
        if not record:
            raise RuntimeError("approval_request_not_found")
        current_status = str(record.get("status") or "").strip().lower()
        if normalized_expected and current_status not in normalized_expected:
            # Repeating the same terminal decision is harmless, but a competing
            # decision or a decision after work started must fail closed.
            if current_status == normalized_status:
                return record
            raise RuntimeError("approval_status_conflict")
        record["contract_name"] = CONTRACT_NAME
        record["status"] = normalized_status
        record["updated_at"] = _now_iso()
        if normalized_status in {"approved", "denied"}:
            record["decided_at"] = str(record.get("decided_at") or "").strip() or _now_iso()
            record["decided_by"] = str(record.get("decided_by") or decided_by or "").strip()
        if reason:
            record["decision_reason"] = str(reason or "").strip()
        normalized_diagnostic = str(diagnostic_sha256 or "").strip().lower()
        if normalized_diagnostic:
            if len(normalized_diagnostic) != 64 or any(
                char not in "0123456789abcdef" for char in normalized_diagnostic
            ):
                raise RuntimeError("approval_diagnostic_sha256_invalid")
            record["decision_diagnostic_sha256"] = normalized_diagnostic
        if job_id:
            record["job_id"] = str(job_id or "").strip()
        return _write_request(record)


def _approval_start_identity(record: dict[str, object]) -> tuple[str, str]:
    source = dict(record.get("source") or {})
    identity = {
        "contract_name": START_CONTRACT_NAME,
        "approval_id": str(record.get("approval_id") or "").strip(),
        "channel": str(record.get("channel") or "").strip().lower(),
        "principal_id_sha256": _sha(str(record.get("principal_id") or "").strip()),
        "source_filename_sha256": _sha(str(source.get("filename") or "").strip()),
        "source_sha256": str(source.get("source_sha256") or "").strip().lower(),
    }
    digest = _canonical_sha256(identity)
    return digest, f"approval-audiobook-{digest[:24]}"


def _load_idempotent_start_job(
    *,
    job_id: str,
    start_identity_sha256: str,
    source_sha256: str,
) -> dict[str, object]:
    normalized_job_id = str(job_id or "").strip()
    if not normalized_job_id or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", normalized_job_id):
        raise RuntimeError("approval_start_job_id_invalid")
    manifest_path = audiobook_epub_pipeline.audiobook_jobs_root() / normalized_job_id / "job.json"
    if not manifest_path.is_file():
        return {}
    try:
        loaded = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise RuntimeError("approval_start_job_manifest_invalid") from exc
    job = dict(loaded) if isinstance(loaded, dict) else {}
    source = dict(job.get("source") or {})
    if (
        str(job.get("job_id") or "").strip() != normalized_job_id
        or str(source.get("intake_idempotency_key_sha256") or "").strip().lower()
        != start_identity_sha256
        or str(source.get("source_sha256") or "").strip().lower()
        != str(source_sha256 or "").strip().lower()
    ):
        raise RuntimeError("approval_start_job_binding_invalid")
    return job


def run_approved_start_once(
    approval_id: str,
    *,
    starter: Callable[[dict[str, object], str, str], dict[str, object]],
    decided_by: str = "",
    approve_pending: bool = False,
) -> dict[str, object]:
    """Create or recover the one canonical job for an approved request.

    ``starting`` plus the deterministic job and input identity are written
    before ``starter`` may perform discovery, synthesis, or any other external
    work.  The approval lock remains held through the start call.  A process
    crash releases the OS lock but leaves enough durable state for the next
    caller to recover the same job.  Completed replays load that exact manifest
    and never call ``starter`` again.
    """

    with _exclusive_approval_lock(approval_id):
        record = load_request(approval_id)
        if not record:
            raise RuntimeError("approval_request_not_found")
        current_status = str(record.get("status") or "").strip().lower()
        if current_status == "pending" and approve_pending:
            record["contract_name"] = CONTRACT_NAME
            record["status"] = "approved"
            record["decided_at"] = str(record.get("decided_at") or "").strip() or _now_iso()
            record["decided_by"] = str(record.get("decided_by") or decided_by or "").strip()
            record["updated_at"] = _now_iso()
            _write_request(record)
            current_status = "approved"
        start_identity_sha256, deterministic_job_id = _approval_start_identity(record)
        approved_source_sha256 = str(
            dict(record.get("source") or {}).get("source_sha256") or ""
        ).strip().lower()
        start = dict(record.get("start") or {})
        persisted_identity = str(start.get("idempotency_key_sha256") or "").strip().lower()
        persisted_job_id = str(record.get("job_id") or start.get("job_id") or "").strip()
        if persisted_identity and persisted_identity != start_identity_sha256:
            raise RuntimeError("approval_start_identity_conflict")
        if persisted_job_id and persisted_job_id != deterministic_job_id:
            raise RuntimeError("approval_start_job_id_conflict")
        if current_status in {"started", "completed"}:
            existing_job = _load_idempotent_start_job(
                job_id=deterministic_job_id,
                start_identity_sha256=start_identity_sha256,
                source_sha256=approved_source_sha256,
            )
            if existing_job:
                return {
                    "record": record,
                    "job": existing_job,
                    "job_id": deterministic_job_id,
                    "start_identity_sha256": start_identity_sha256,
                    "started_now": False,
                    "replayed": True,
                }
            if current_status == "completed":
                raise RuntimeError("approval_completed_job_missing")
            # A legacy/crash-written started record without its bound manifest
            # is repaired through the same deterministic identity below.
        elif current_status not in {"approved", "starting", "failed"}:
            raise RuntimeError("approval_not_startable")
        if current_status == "failed" and (
            str(start.get("contract_name") or "").strip() != START_CONTRACT_NAME
            or not persisted_job_id
        ):
            raise RuntimeError("approval_not_startable")

        attempt_count = int(start.get("attempt_count") or 0) + 1
        start.update(
            {
                "contract_name": START_CONTRACT_NAME,
                "state": "starting",
                "job_id": deterministic_job_id,
                "idempotency_key_sha256": start_identity_sha256,
                "attempt_count": attempt_count,
                "started_at": str(start.get("started_at") or "").strip() or _now_iso(),
                "last_attempt_at": _now_iso(),
                "recovery_attempt": current_status in {"starting", "started", "failed"},
                "raw_source_path_exposed": False,
            }
        )
        record["contract_name"] = CONTRACT_NAME
        record["status"] = "starting"
        record["job_id"] = deterministic_job_id
        record["start"] = start
        record["updated_at"] = _now_iso()
        _write_request(record)

        try:
            approved_source_path = source_path(record)
            if (
                not approved_source_sha256
                or not approved_source_path.is_file()
                or audiobook_epub_pipeline._sha256_file(approved_source_path)  # type: ignore[attr-defined]
                != approved_source_sha256
            ):
                raise RuntimeError("approval_source_binding_mismatch")
            job = dict(starter(dict(record), deterministic_job_id, start_identity_sha256))
            if str(job.get("job_id") or "").strip() != deterministic_job_id:
                raise RuntimeError("approval_start_result_job_id_mismatch")
            job_source = dict(job.get("source") or {})
            if (
                str(job_source.get("intake_idempotency_key_sha256") or "").strip().lower()
                != start_identity_sha256
                or str(job_source.get("source_sha256") or "").strip().lower()
                != approved_source_sha256
            ):
                raise RuntimeError("approval_start_result_identity_mismatch")
        except Exception as exc:
            start["state"] = "failed"
            start["failed_at"] = _now_iso()
            start["failure_reason"] = "approved_audiobook_start_failed"
            start["failure_diagnostic_sha256"] = _sha(str(exc))
            record["status"] = "failed"
            record["decision_reason"] = "approved_audiobook_start_failed"
            record["decision_diagnostic_sha256"] = start["failure_diagnostic_sha256"]
            record["start"] = start
            record["updated_at"] = _now_iso()
            _write_request(record)
            raise

        start["state"] = "started"
        start["completed_at"] = _now_iso()
        start["job_manifest_sha256"] = _canonical_sha256(job)
        start["job_status"] = str(job.get("status") or "").strip()
        start.pop("failed_at", None)
        start.pop("failure_reason", None)
        start.pop("failure_diagnostic_sha256", None)
        record["status"] = "started"
        record["job_id"] = deterministic_job_id
        record["start"] = start
        record["updated_at"] = _now_iso()
        record.pop("decision_reason", None)
        record.pop("decision_diagnostic_sha256", None)
        persisted = _write_request(record)
        return {
            "record": persisted,
            "job": job,
            "job_id": deterministic_job_id,
            "start_identity_sha256": start_identity_sha256,
            "started_now": True,
            "replayed": current_status in {"starting", "started", "failed"},
        }


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
