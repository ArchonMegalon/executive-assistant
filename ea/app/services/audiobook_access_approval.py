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
DELIVERY_CONTRACT_NAME = "ea.audiobook_access_approval_delivery.v1"
DELIVERY_OUTCOME_CONTRACT_NAME = "ea.audiobook_access_approval_delivery_outcome.v1"
DELIVERY_RECONCILIATION_CONTRACT_NAME = "ea.audiobook_access_approval_delivery_reconciliation.v1"
IMMUTABLE_START_SNAPSHOT_CONTRACT_NAME = "ea.audiobook_immutable_start_snapshot.v1"
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


def approved_channel_target(record: dict[str, object]) -> dict[str, str]:
    """Return the canonical, record-owned routing target for an approval."""

    channel = str(record.get("channel") or "").strip().lower()
    if channel not in {"telegram", "whatsapp"}:
        raise RuntimeError("approval_channel_target_invalid")
    target = {
        "channel": channel,
        "phone_number": normalize_phone_number(record.get("phone_number")),
        "sender_ref": normalize_sender_ref(record.get("sender_ref")),
    }
    if channel == "telegram":
        telegram = dict(record.get("telegram") or {})
        target.update(
            {
                "chat_id": str(telegram.get("chat_id") or "").strip(),
                "message_id": str(telegram.get("message_id") or "").strip(),
            }
        )
    else:
        whatsapp = dict(record.get("whatsapp") or {})
        target.update(
            {
                "session_ref": str(whatsapp.get("session_ref") or "").strip(),
                "chat_ref": str(whatsapp.get("chat_ref") or "").strip(),
                "message_id": str(whatsapp.get("message_id") or "").strip(),
            }
        )
    return target


def _approved_channel_target_snapshot(record: dict[str, object]) -> dict[str, str]:
    target = approved_channel_target(record)
    return {
        "channel": target["channel"],
        **{
            f"{key}_sha256": _sha(value) if value else ""
            for key, value in target.items()
            if key != "channel"
        },
    }


def validate_approved_channel_target_completeness(
    record: dict[str, object],
) -> dict[str, str]:
    """Require the minimum immutable route needed for eventual delivery."""

    target = approved_channel_target(record)
    if target["channel"] == "telegram":
        complete = bool(target.get("chat_id") and target.get("message_id"))
    else:
        phone = str(target.get("phone_number") or "").strip()
        sender = str(target.get("sender_ref") or "").strip()
        complete = bool(
            phone
            and sender
            and normalize_phone_number(sender) == phone
            and target.get("session_ref")
            and target.get("message_id")
        )
    if not complete:
        raise RuntimeError("approval_channel_target_incomplete")
    return target


def validate_approved_channel_target(
    record: dict[str, object],
    *,
    channel: str,
    phone_number: object = "",
    sender_ref: object = "",
    chat_id: object = "",
    session_ref: object = "",
    chat_ref: object = "",
    message_id: object = "",
) -> dict[str, str]:
    """Reject rehydrating an approval with a different inbound route."""

    normalized_channel = str(channel or "").strip().lower()
    expected = validate_approved_channel_target_completeness(record)
    if normalized_channel != expected["channel"]:
        raise RuntimeError("approval_channel_target_mismatch")
    current: dict[str, object] = {
        "channel": normalized_channel,
        "phone_number": normalize_phone_number(phone_number),
        "sender_ref": normalize_sender_ref(sender_ref),
    }
    if normalized_channel == "telegram":
        current.update(
            chat_id=str(chat_id or "").strip(),
            message_id=str(message_id or "").strip(),
        )
    else:
        current.update(
            session_ref=str(session_ref or "").strip(),
            chat_ref=str(chat_ref or "").strip(),
            message_id=str(message_id or "").strip(),
        )
    current_record: dict[str, object] = {
        "channel": normalized_channel,
        "phone_number": current["phone_number"],
        "sender_ref": current["sender_ref"],
        normalized_channel: {
            key: value
            for key, value in current.items()
            if key not in {"channel", "phone_number", "sender_ref"}
        },
    }
    if not hmac.compare_digest(
        _canonical_sha256(_approved_channel_target_snapshot(record)),
        _canonical_sha256(_approved_channel_target_snapshot(current_record)),
    ):
        raise RuntimeError("approval_channel_target_mismatch")
    return expected


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
    validate_approved_channel_target_completeness(record)
    source = dict(record.get("source") or {})
    identity = {
        "contract_name": START_CONTRACT_NAME,
        "approval_id": str(record.get("approval_id") or "").strip(),
        "channel": str(record.get("channel") or "").strip().lower(),
        "principal_id_sha256": _sha(str(record.get("principal_id") or "").strip()),
        "source_filename_sha256": _sha(str(source.get("filename") or "").strip()),
        "source_sha256": str(source.get("source_sha256") or "").strip().lower(),
        "approved_target": _approved_channel_target_snapshot(record),
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


def _immutable_start_job_snapshot(
    job: dict[str, object],
    *,
    original_status: str,
    record: dict[str, object],
) -> dict[str, object]:
    source = dict(job.get("source") or {})
    metadata = dict(job.get("metadata") or {})
    provider = dict(job.get("provider") or {})
    voice_selection = dict(provider.get("voice_selection") or {})
    return {
        "contract_name": IMMUTABLE_START_SNAPSHOT_CONTRACT_NAME,
        "job_contract_name": str(job.get("contract_name") or "").strip(),
        "job_id": str(job.get("job_id") or "").strip(),
        "principal_id_sha256": _sha(str(job.get("principal_id") or "").strip()),
        "original_status": str(original_status or "").strip(),
        "approved_target": _approved_channel_target_snapshot(record),
        "source": {
            key: source.get(key)
            for key in (
                "kind",
                "runner_id",
                "source_filename",
                "source_sha256",
                "intake_idempotency_key_sha256",
                "rights_basis",
            )
        },
        "metadata": {
            key: metadata.get(key)
            for key in (
                "title",
                "author",
                "language",
                "source_filename",
                "source_sha256",
            )
        },
        "chapters": [
            {
                key: dict(row).get(key)
                for key in (
                    "index",
                    "title",
                    "source_href",
                    "audio_filename",
                    "char_count",
                    "sha256",
                    "structure_path",
                )
            }
            for row in list(job.get("chapters") or [])
            if isinstance(row, dict)
        ],
        "totals": dict(job.get("totals") or {}),
        "provider_plan": {
            "preferred": provider.get("preferred"),
            "external_tts_enabled": provider.get("external_tts_enabled"),
            "unmixr_auto_render_enabled": provider.get("unmixr_auto_render_enabled"),
            "raw_book_text_leaves_ea": provider.get("raw_book_text_leaves_ea"),
            "voice_selection": {
                key: voice_selection.get(key)
                for key in (
                    "contract_name",
                    "strategy",
                    "selection_policy",
                    "book_profile",
                    "source_provenance_sha256",
                    "catalog_sha256",
                    "catalog_source_provenance_sha256",
                    "candidate_count",
                    "required_candidate_count",
                    "target_catalog_count",
                )
            },
        },
    }


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
        validate_approved_channel_target_completeness(record)
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
            original_job_status = str(job.get("status") or "").strip()
            immutable_snapshot = _immutable_start_job_snapshot(
                job,
                original_status=original_job_status,
                record=record,
            )
            immutable_snapshot_sha256 = _canonical_sha256(immutable_snapshot)
            job_manifest_sha256 = _canonical_sha256(job)
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
        start["job_manifest_sha256"] = job_manifest_sha256
        start["job_status"] = original_job_status
        start["original_job_status"] = original_job_status
        start["immutable_snapshot_contract_name"] = (
            IMMUTABLE_START_SNAPSHOT_CONTRACT_NAME
        )
        start["immutable_snapshot"] = immutable_snapshot
        start["immutable_snapshot_sha256"] = immutable_snapshot_sha256
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


def _approval_delivery_binding(
    *,
    record: dict[str, object],
    channel: str,
    job: dict[str, object],
) -> tuple[str, dict[str, object]]:
    normalized_channel = str(channel or "").strip().lower()
    if normalized_channel not in {"telegram", "whatsapp"}:
        raise RuntimeError("approval_delivery_channel_invalid")
    if str(record.get("channel") or "").strip().lower() != normalized_channel:
        raise RuntimeError("approval_delivery_channel_mismatch")
    validate_approved_channel_target_completeness(record)
    if str(record.get("status") or "").strip().lower() not in {"started", "completed"}:
        raise RuntimeError("approval_delivery_start_incomplete")
    start = dict(record.get("start") or {})
    source = dict(record.get("source") or {})
    job_source = dict(job.get("source") or {})
    job_id = str(record.get("job_id") or start.get("job_id") or "").strip()
    start_identity = str(start.get("idempotency_key_sha256") or "").strip().lower()
    source_sha256 = str(source.get("source_sha256") or "").strip().lower()
    if (
        str(start.get("contract_name") or "").strip() != START_CONTRACT_NAME
        or str(start.get("state") or "").strip() != "started"
        or not job_id
        or str(job.get("job_id") or "").strip() != job_id
        or not start_identity
        or str(job_source.get("intake_idempotency_key_sha256") or "").strip().lower()
        != start_identity
        or not source_sha256
        or str(job_source.get("source_sha256") or "").strip().lower()
        != source_sha256
    ):
        raise RuntimeError("approval_delivery_start_binding_invalid")
    persisted_snapshot = dict(start.get("immutable_snapshot") or {})
    persisted_snapshot_sha256 = str(
        start.get("immutable_snapshot_sha256") or ""
    ).strip().lower()
    if (
        str(start.get("immutable_snapshot_contract_name") or "").strip()
        != IMMUTABLE_START_SNAPSHOT_CONTRACT_NAME
        or str(persisted_snapshot.get("contract_name") or "").strip()
        != IMMUTABLE_START_SNAPSHOT_CONTRACT_NAME
        or str(persisted_snapshot.get("original_status") or "").strip()
        != str(start.get("original_job_status") or "").strip()
        or str(start.get("job_status") or "").strip()
        != str(start.get("original_job_status") or "").strip()
        or not persisted_snapshot_sha256
        or _canonical_sha256(persisted_snapshot) != persisted_snapshot_sha256
    ):
        raise RuntimeError("approval_delivery_immutable_snapshot_invalid")
    current_snapshot = _immutable_start_job_snapshot(
        job,
        original_status=str(start.get("original_job_status") or "").strip(),
        record=record,
    )
    if _canonical_sha256(current_snapshot) != persisted_snapshot_sha256:
        raise RuntimeError("approval_delivery_immutable_snapshot_mismatch")
    binding = {
        "contract_name": DELIVERY_CONTRACT_NAME,
        "approval_id": str(record.get("approval_id") or "").strip(),
        "channel": normalized_channel,
        "job_id": job_id,
        "source_sha256": source_sha256,
        "start_identity_sha256": start_identity,
        "start_job_manifest_sha256": str(start.get("job_manifest_sha256") or "").strip().lower(),
        "immutable_snapshot_sha256": persisted_snapshot_sha256,
    }
    return _canonical_sha256(binding), binding


def _delivery_result_sha256(result: object) -> str:
    try:
        return _canonical_sha256(result)
    except (TypeError, ValueError):
        return _sha(repr(result))


def build_approved_delivery_outcome(
    *,
    channel: str,
    result: Any,
    expected_effect_count: int,
    confirmed_effect_count: int,
    known_no_effect_count: int,
    ambiguous_effect_count: int,
    reason: str = "",
) -> dict[str, object]:
    """Build the explicit result contract for one external delivery attempt.

    A caller may only claim a completed delivery when every intended external
    effect has a positive transport receipt.  A fully observed zero-effect
    attempt is safe to retry.  Any mixture of confirmed and failed effects, or
    any transport ambiguity, requires operator reconciliation before another
    send may be attempted.
    """

    normalized_channel = str(channel or "").strip().lower()
    if normalized_channel not in {"telegram", "whatsapp"}:
        raise RuntimeError("approval_delivery_outcome_channel_invalid")
    counts = {
        "expected_effect_count": int(expected_effect_count),
        "confirmed_effect_count": int(confirmed_effect_count),
        "known_no_effect_count": int(known_no_effect_count),
        "ambiguous_effect_count": int(ambiguous_effect_count),
    }
    if any(value < 0 for value in counts.values()):
        raise RuntimeError("approval_delivery_outcome_count_invalid")
    if (
        counts["confirmed_effect_count"]
        + counts["known_no_effect_count"]
        + counts["ambiguous_effect_count"]
        != counts["expected_effect_count"]
    ):
        raise RuntimeError("approval_delivery_outcome_count_mismatch")
    if (
        counts["expected_effect_count"] > 0
        and counts["confirmed_effect_count"]
        == counts["expected_effect_count"]
    ):
        classification = "proven_success"
    elif (
        counts["confirmed_effect_count"] == 0
        and counts["ambiguous_effect_count"] == 0
    ):
        classification = "failed_before_effect"
    else:
        classification = "outcome_unknown"
    return {
        "contract_name": DELIVERY_OUTCOME_CONTRACT_NAME,
        "channel": normalized_channel,
        "classification": classification,
        **counts,
        "reason": " ".join(str(reason or "").strip().split())[:160],
        "result": result,
    }


def _validated_delivery_outcome(
    value: object,
    *,
    channel: str,
) -> dict[str, object]:
    if not isinstance(value, dict):
        raise RuntimeError("approval_delivery_outcome_contract_missing")
    outcome = dict(value)
    if str(outcome.get("contract_name") or "").strip() != DELIVERY_OUTCOME_CONTRACT_NAME:
        raise RuntimeError("approval_delivery_outcome_contract_invalid")
    normalized_channel = str(channel or "").strip().lower()
    if str(outcome.get("channel") or "").strip().lower() != normalized_channel:
        raise RuntimeError("approval_delivery_outcome_channel_mismatch")
    try:
        validated = build_approved_delivery_outcome(
            channel=normalized_channel,
            result=outcome.get("result"),
            expected_effect_count=int(outcome.get("expected_effect_count")),
            confirmed_effect_count=int(outcome.get("confirmed_effect_count")),
            known_no_effect_count=int(outcome.get("known_no_effect_count")),
            ambiguous_effect_count=int(outcome.get("ambiguous_effect_count")),
            reason=str(outcome.get("reason") or ""),
        )
    except (TypeError, ValueError) as exc:
        raise RuntimeError("approval_delivery_outcome_count_invalid") from exc
    if str(outcome.get("classification") or "").strip() != str(
        validated["classification"]
    ):
        raise RuntimeError("approval_delivery_outcome_classification_invalid")
    return validated


def run_approved_delivery_once(
    approval_id: str,
    *,
    channel: str,
    job: dict[str, object],
    deliverer: Callable[[], Any],
) -> dict[str, object]:
    """Run the first requester delivery once for an already-started job.

    A missing delivery record is recoverable after a crash between canonical
    start and delivery.  The durable ``delivering`` claim is written before the
    callback and the approval lock remains held through it, so concurrent
    workers cannot emit duplicate samples.  If a process dies after claiming,
    the outcome is intentionally treated as ambiguous and replay fails closed
    rather than risking a duplicate external send.
    """

    with _exclusive_approval_lock(approval_id):
        record = load_request(approval_id)
        if not record:
            raise RuntimeError("approval_request_not_found")
        binding_sha256, binding = _approval_delivery_binding(
            record=record,
            channel=channel,
            job=job,
        )
        delivery = dict(record.get("first_delivery") or {})
        if delivery:
            if (
                str(delivery.get("contract_name") or "").strip()
                != DELIVERY_CONTRACT_NAME
                or str(delivery.get("binding_sha256") or "").strip().lower()
                != binding_sha256
                or str(delivery.get("channel") or "").strip().lower()
                != str(channel or "").strip().lower()
            ):
                raise RuntimeError("approval_delivery_binding_conflict")
            delivery_state = str(delivery.get("state") or "").strip().lower()
            if delivery_state == "delivering":
                # A concurrent caller cannot observe this state because the
                # approval lock is held through the callback.  Seeing it after
                # acquiring the lock therefore means the prior worker exited
                # without recording an outcome; preserve at-most-once safety.
                delivery_state = "outcome_unknown"
                delivery["state"] = delivery_state
                delivery["outcome_unknown_at"] = _now_iso()
                delivery["outcome_unknown_reason"] = (
                    "prior_delivery_attempt_outcome_unknown"
                )
                delivery["retryable"] = False
                delivery["reconciliation_required"] = True
                record["first_delivery"] = delivery
                record["updated_at"] = _now_iso()
                record = _write_request(record)
            if delivery_state in {"completed", "outcome_unknown"}:
                return {
                    "record": record,
                    "result": None,
                    "delivery_now": False,
                    "replayed": True,
                    "delivery_status": delivery_state,
                    "binding_sha256": binding_sha256,
                }
            if delivery_state != "failed_before_effect":
                raise RuntimeError("approval_delivery_state_invalid")

        prior_reconciliation = dict(delivery.get("reconciliation") or {})
        attempt_count = int(delivery.get("attempt_count") or 0) + 1
        claimed_at = _now_iso()
        delivery = {
            "contract_name": DELIVERY_CONTRACT_NAME,
            "channel": str(channel or "").strip().lower(),
            "state": "delivering",
            "binding_sha256": binding_sha256,
            "attempt_id_sha256": _canonical_sha256(
                {
                    "binding_sha256": binding_sha256,
                    "attempt_count": attempt_count,
                }
            ),
            "attempt_count": attempt_count,
            "claimed_at": claimed_at,
            "job_id_sha256": _sha(binding["job_id"]),
            "source_sha256": str(binding["source_sha256"]),
            "start_identity_sha256": str(binding["start_identity_sha256"]),
            "start_job_manifest_sha256": str(binding["start_job_manifest_sha256"]),
            "immutable_snapshot_sha256": str(
                binding["immutable_snapshot_sha256"]
            ),
            "raw_job_id_exposed": False,
            "raw_source_path_exposed": False,
            "raw_transport_identifier_exposed": False,
        }
        if prior_reconciliation:
            delivery["reconciliation"] = prior_reconciliation
        record["first_delivery"] = delivery
        record["updated_at"] = claimed_at
        _write_request(record)

        try:
            outcome = _validated_delivery_outcome(
                deliverer(),
                channel=channel,
            )
        except Exception as exc:
            delivery["state"] = "outcome_unknown"
            delivery["failed_at"] = _now_iso()
            delivery["failure_diagnostic_sha256"] = _sha(str(exc))
            delivery["retryable"] = False
            delivery["reconciliation_required"] = True
            record["first_delivery"] = delivery
            record["updated_at"] = _now_iso()
            _write_request(record)
            raise

        result = outcome.get("result")
        classification = str(outcome["classification"])
        delivery_state = {
            "proven_success": "completed",
            "failed_before_effect": "failed_before_effect",
            "outcome_unknown": "outcome_unknown",
        }[classification]
        delivery["state"] = delivery_state
        delivery["outcome_contract_name"] = DELIVERY_OUTCOME_CONTRACT_NAME
        delivery["outcome_classification"] = classification
        delivery["expected_effect_count"] = int(
            outcome["expected_effect_count"]
        )
        delivery["confirmed_effect_count"] = int(
            outcome["confirmed_effect_count"]
        )
        delivery["known_no_effect_count"] = int(
            outcome["known_no_effect_count"]
        )
        delivery["ambiguous_effect_count"] = int(
            outcome["ambiguous_effect_count"]
        )
        delivery["outcome_reason"] = str(outcome.get("reason") or "")
        delivery["outcome_recorded_at"] = _now_iso()
        delivery["result_sha256"] = _delivery_result_sha256(result)
        delivery["result_kind"] = type(result).__name__
        delivery["retryable"] = delivery_state == "failed_before_effect"
        delivery["reconciliation_required"] = delivery_state == "outcome_unknown"
        if delivery_state == "completed":
            delivery["completed_at"] = _now_iso()
        else:
            delivery.pop("completed_at", None)
        delivery.pop("failed_at", None)
        delivery.pop("failure_diagnostic_sha256", None)
        record["first_delivery"] = delivery
        record["updated_at"] = _now_iso()
        persisted = _write_request(record)
        return {
            "record": persisted,
            "result": result,
            "delivery_now": True,
            "replayed": False,
            "delivery_status": delivery_state,
            "delivery_succeeded": delivery_state == "completed",
            "binding_sha256": binding_sha256,
        }


def reconcile_approved_delivery(
    approval_id: str,
    *,
    action: str,
    binding_sha256: str,
    reconciled_by: str,
    authorization: str,
) -> dict[str, object]:
    """Resolve one ambiguous first delivery without silently resending it."""

    normalized_action = str(action or "").strip().lower()
    if normalized_action not in {"verified_completed", "verified_no_effect_retry"}:
        raise RuntimeError("approval_delivery_reconciliation_action_invalid")
    secret = _env_secret("EA_AUDIOBOOK_DELIVERY_RECONCILIATION_SECRET")
    if not secret:
        raise RuntimeError("approval_delivery_reconciliation_secret_missing")
    if not hmac.compare_digest(
        str(authorization or "").encode("utf-8"),
        secret.encode("utf-8"),
    ):
        raise RuntimeError("approval_delivery_reconciliation_unauthorized")
    normalized_binding = str(binding_sha256 or "").strip().lower()
    normalized_operator = " ".join(str(reconciled_by or "").strip().split())
    if not normalized_binding or not normalized_operator:
        raise RuntimeError("approval_delivery_reconciliation_identity_missing")

    with _exclusive_approval_lock(approval_id):
        record = load_request(approval_id)
        if not record:
            raise RuntimeError("approval_request_not_found")
        delivery = dict(record.get("first_delivery") or {})
        if (
            str(delivery.get("contract_name") or "").strip()
            != DELIVERY_CONTRACT_NAME
            or str(delivery.get("binding_sha256") or "").strip().lower()
            != normalized_binding
        ):
            raise RuntimeError("approval_delivery_reconciliation_binding_mismatch")
        if str(delivery.get("state") or "").strip().lower() != "outcome_unknown":
            raise RuntimeError("approval_delivery_reconciliation_state_invalid")
        reconciled_at = _now_iso()
        reconciliation = {
            "contract_name": DELIVERY_RECONCILIATION_CONTRACT_NAME,
            "action": normalized_action,
            "binding_sha256": normalized_binding,
            "reconciled_by_sha256": _sha(normalized_operator),
            "reconciled_at": reconciled_at,
            "authorization_exposed": False,
        }
        delivery["reconciliation"] = reconciliation
        delivery["reconciliation_required"] = False
        delivery["reconciled_at"] = reconciled_at
        if normalized_action == "verified_completed":
            delivery["state"] = "completed"
            delivery["completed_at"] = reconciled_at
            delivery["retryable"] = False
            delivery["verified_outcome"] = "completed"
        else:
            delivery["state"] = "failed_before_effect"
            delivery["retryable"] = True
            delivery["verified_outcome"] = "no_effect"
            delivery.pop("completed_at", None)
        record["first_delivery"] = delivery
        record["updated_at"] = reconciled_at
        persisted = _write_request(record)
        return {
            "record": persisted,
            "delivery_status": str(delivery["state"]),
            "binding_sha256": normalized_binding,
            "action": normalized_action,
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
    with _exclusive_approval_lock(approval_id):
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
