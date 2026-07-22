from __future__ import annotations

import fcntl
import hashlib
import hmac
import json
import os
import re
import secrets
import stat
import tempfile
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from app.services.memorial_paths import (
    private_memorial_contribution_dir,
    public_memorial_contribution_dir,
)


PRIVATE_SCHEMA = "ea.memorial_family_contributions.private.v1"
PUBLIC_SCHEMA = "ea.memorial_family_contributions.public.v1"
TAKEDOWN_SCHEMA = "ea.memorial_family_contributions.takedowns.public.v1"
RECOVERY_RECEIPT_SCHEMA = "ea.memorial_family_contribution.recovery_receipt.v1"
PUBLIC_PROPOSAL_BINDING_SCHEMA = (
    "ea.memorial_family_contribution.public_proposal_binding.v1"
)
PUBLIC_PROPOSAL_DECISION_SCHEMA = (
    "ea.memorial_family_contribution.public_proposal_decision.v1"
)
HISTORY_COMPACTION_SCHEMA = (
    "ea.memorial_family_contribution.history_compaction.v1"
)
ERASURE_REQUEST_SCHEMA = "ea.memorial_family_contribution.erasure_request.v1"
PRIVATE_FILENAME = "family_contributions.json"
PUBLIC_FILENAME = "family_contributions.public.json"
TAKEDOWN_FILENAME = "family_contributions.takedowns.public.json"
MAX_CONTRIBUTIONS = 500
MAX_HISTORY_EVENTS = 64
MAX_TITLE_CHARS = 180
MAX_BODY_CHARS = 6000
MAX_SOURCE_LABEL_CHARS = 160
MAX_PERSON_CHARS = 160
MAX_RELATIONSHIP_CHARS = 160
MAX_NOTE_CHARS = 1000
_EMPTY_HISTORY_DIGEST = "0" * 64

_SLUG_RE = re.compile(r"^[A-Za-z0-9_-]{1,80}$")
_CONTRIBUTION_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_TAKEDOWN_STATUSES = {
    "correction_pending",
    "erasure_requested",
    "rejected",
    "unpublished",
    "withdrawn",
}
_ERASURE_REQUEST_SCOPE = (
    "contribution_private_record",
    "publication_state",
    "bounded_governance_history",
)
_STORE_LOCK = threading.RLock()


class MemorialContributionError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = str(code or "memorial_contribution_failed")
        super().__init__(self.code)


def _utc_now_iso() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _safe_slug(slug: str) -> str:
    normalized = str(slug or "").strip()
    if not _SLUG_RE.fullmatch(normalized):
        raise MemorialContributionError("memorial_not_found")
    return normalized


def _absolute_path(path: Path) -> Path:
    return Path(os.path.abspath(os.fspath(path.expanduser())))


def _reject_symlink_components(path: Path) -> None:
    absolute = _absolute_path(path)
    for candidate in [*reversed(absolute.parents), absolute]:
        try:
            mode = os.lstat(candidate).st_mode
        except FileNotFoundError:
            continue
        except OSError as exc:
            raise MemorialContributionError(
                "memorial_contribution_path_invalid"
            ) from exc
        if stat.S_ISLNK(mode):
            raise MemorialContributionError("memorial_contribution_path_invalid")


def _contribution_slug_dir(*, root: Path, slug: str) -> Path:
    absolute_root = _absolute_path(root)
    target = _absolute_path(absolute_root / _safe_slug(slug))
    if target == absolute_root or absolute_root not in target.parents:
        raise MemorialContributionError("memorial_contribution_path_invalid")
    _reject_symlink_components(target)
    return target


def _private_slug_dir(slug: str) -> Path:
    return _contribution_slug_dir(
        root=private_memorial_contribution_dir(),
        slug=slug,
    )


def _public_slug_dir(slug: str) -> Path:
    return _contribution_slug_dir(
        root=public_memorial_contribution_dir(),
        slug=slug,
    )


def private_contribution_path(slug: str) -> Path:
    return _private_slug_dir(slug) / PRIVATE_FILENAME


def public_contribution_path(slug: str) -> Path:
    return _public_slug_dir(slug) / PUBLIC_FILENAME


def public_takedown_path(slug: str) -> Path:
    return _public_slug_dir(slug) / TAKEDOWN_FILENAME


def _bounded_text(
    value: object,
    *,
    field: str,
    max_chars: int,
    required: bool = False,
) -> str:
    if value is None:
        text = ""
    elif isinstance(value, str):
        text = " ".join(value.replace("\x00", " ").split()).strip()
    else:
        raise MemorialContributionError(f"memorial_contribution_{field}_invalid")
    if required and not text:
        raise MemorialContributionError(f"memorial_contribution_{field}_required")
    if len(text) > max_chars:
        raise MemorialContributionError(f"memorial_contribution_{field}_too_long")
    return text


def _bounded_public_version(payload: dict[str, object]) -> dict[str, str]:
    return {
        "source_label": _bounded_text(
            payload.get("source_label"),
            field="source_label",
            max_chars=MAX_SOURCE_LABEL_CHARS,
        )
        or "Erinnerung aus der Familie",
        "title": _bounded_text(
            payload.get("title"),
            field="title",
            max_chars=MAX_TITLE_CHARS,
            required=True,
        ),
        "body": _bounded_text(
            payload.get("body"),
            field="body",
            max_chars=MAX_BODY_CHARS,
            required=True,
        ),
    }


def _public_proposal_sha256(
    *,
    slug: str,
    contribution_id: str,
    public_version: dict[str, str],
) -> str:
    binding_payload = {
        "schema": PUBLIC_PROPOSAL_BINDING_SCHEMA,
        "slug": _safe_slug(slug),
        "contribution_id": str(contribution_id or ""),
        "public_version": {
            "body": str(public_version.get("body") or ""),
            "source_label": str(public_version.get("source_label") or ""),
            "title": str(public_version.get("title") or ""),
        },
    }
    return hashlib.sha256(
        json.dumps(
            binding_payload,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()


def _stored_public_proposal(
    *,
    slug: str,
    record: dict[str, object],
    required: bool = False,
) -> tuple[dict[str, str], dict[str, str]]:
    raw_proposal = record.get("public_proposal")
    raw_binding = record.get("public_proposal_binding")
    if not raw_proposal and not raw_binding:
        if required:
            raise MemorialContributionError(
                "memorial_contribution_proposal_missing"
            )
        return {}, {}
    if not isinstance(raw_proposal, dict) or not isinstance(raw_binding, dict):
        raise MemorialContributionError("memorial_contribution_store_invalid")
    try:
        proposal = _bounded_public_version(dict(raw_proposal))
    except MemorialContributionError as exc:
        raise MemorialContributionError(
            "memorial_contribution_store_invalid"
        ) from exc
    if set(raw_proposal) != {"source_label", "title", "body"}:
        raise MemorialContributionError("memorial_contribution_store_invalid")
    if set(raw_binding) != {"schema", "sha256", "proposed_at"}:
        raise MemorialContributionError("memorial_contribution_store_invalid")
    proposal_sha256 = str(raw_binding.get("sha256") or "")
    proposed_at = str(raw_binding.get("proposed_at") or "")
    expected_sha256 = _public_proposal_sha256(
        slug=slug,
        contribution_id=str(record.get("contribution_id") or ""),
        public_version=proposal,
    )
    if (
        raw_binding.get("schema") != PUBLIC_PROPOSAL_BINDING_SCHEMA
        or _SHA256_RE.fullmatch(proposal_sha256) is None
        or not hmac.compare_digest(proposal_sha256, expected_sha256)
        or not proposed_at
        or len(proposed_at) > 80
    ):
        raise MemorialContributionError("memorial_contribution_store_invalid")
    return proposal, {
        "schema": PUBLIC_PROPOSAL_BINDING_SCHEMA,
        "sha256": proposal_sha256,
        "proposed_at": proposed_at,
    }


def _stored_proposal_decision(record: dict[str, object]) -> dict[str, str]:
    raw_decision = record.get("public_proposal_decision")
    if not raw_decision:
        return {}
    if not isinstance(raw_decision, dict) or set(raw_decision) != {
        "schema",
        "decision",
        "proposal_sha256",
        "decided_at",
        "contributor_note",
    }:
        raise MemorialContributionError("memorial_contribution_store_invalid")
    decision = str(raw_decision.get("decision") or "")
    proposal_sha256 = str(raw_decision.get("proposal_sha256") or "")
    decided_at = str(raw_decision.get("decided_at") or "")
    contributor_note = str(raw_decision.get("contributor_note") or "")
    if (
        raw_decision.get("schema") != PUBLIC_PROPOSAL_DECISION_SCHEMA
        or decision not in {"approved", "rejected"}
        or _SHA256_RE.fullmatch(proposal_sha256) is None
        or not decided_at
        or len(decided_at) > 80
        or len(contributor_note) > MAX_NOTE_CHARS
    ):
        raise MemorialContributionError("memorial_contribution_store_invalid")
    return {
        "schema": PUBLIC_PROPOSAL_DECISION_SCHEMA,
        "decision": decision,
        "proposal_sha256": proposal_sha256,
        "decided_at": decided_at,
        "contributor_note": contributor_note,
    }


def _stored_erasure_request(record: dict[str, object]) -> dict[str, object]:
    raw_request = record.get("erasure_request")
    if not raw_request:
        return {}
    if not isinstance(raw_request, dict) or set(raw_request) != {
        "schema",
        "state",
        "requested_at",
        "reason",
        "scope",
        "public_removed",
        "permanent_erasure_completed",
    }:
        raise MemorialContributionError("memorial_contribution_store_invalid")
    reason = str(raw_request.get("reason") or "")
    requested_at = str(raw_request.get("requested_at") or "")
    scope = raw_request.get("scope")
    if (
        raw_request.get("schema") != ERASURE_REQUEST_SCHEMA
        or raw_request.get("state") != "pending_operator_review"
        or not requested_at
        or len(requested_at) > 80
        or str(record.get("status") or "") != "erasure_requested"
        or str(record.get("visibility") or "") != "private"
        or str(record.get("erasure_requested_at") or "") != requested_at
        or len(reason) > MAX_NOTE_CHARS
        or scope != list(_ERASURE_REQUEST_SCOPE)
        or raw_request.get("public_removed") is not True
        or raw_request.get("permanent_erasure_completed") is not False
    ):
        raise MemorialContributionError("memorial_contribution_store_invalid")
    return {
        "schema": ERASURE_REQUEST_SCHEMA,
        "state": "pending_operator_review",
        "requested_at": requested_at,
        "reason": reason,
        "scope": list(_ERASURE_REQUEST_SCOPE),
        "public_removed": True,
        "permanent_erasure_completed": False,
    }


def _token_hash(token: str) -> str:
    return hashlib.sha256(str(token or "").encode("utf-8")).hexdigest()


def _write_json_atomic(path: Path, payload: dict[str, object], *, mode: int) -> None:
    _reject_symlink_components(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    _reject_symlink_components(path)
    try:
        path.parent.chmod(0o700 if mode == 0o600 else 0o755)
    except OSError:
        pass
    if path.is_symlink():
        raise MemorialContributionError("memorial_contribution_path_invalid")
    descriptor, temp_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent)
    )
    temp_path = Path(temp_name)
    try:
        os.fchmod(descriptor, mode)
        encoded = (
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        ).encode("utf-8")
        with os.fdopen(descriptor, "wb") as handle:
            descriptor = -1
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
        try:
            path.chmod(mode)
        except OSError:
            pass
        directory_descriptor = os.open(
            path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
        )
        try:
            os.fsync(directory_descriptor)
        finally:
            os.close(directory_descriptor)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        temp_path.unlink(missing_ok=True)


@contextmanager
def _contribution_lock(slug: str) -> Iterator[None]:
    directory = _private_slug_dir(slug)
    directory.mkdir(parents=True, exist_ok=True)
    _reject_symlink_components(directory)
    try:
        directory.chmod(0o700)
    except OSError:
        pass
    lock_path = directory / ".family_contributions.lock"
    flags = (
        os.O_RDWR
        | os.O_CREAT
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    with _STORE_LOCK:
        try:
            descriptor = os.open(lock_path, flags, 0o600)
        except OSError as exc:
            raise MemorialContributionError(
                "memorial_contribution_store_unavailable"
            ) from exc
        try:
            os.fchmod(descriptor, 0o600)
            fcntl.flock(descriptor, fcntl.LOCK_EX)
            yield
        finally:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
            finally:
                os.close(descriptor)


def _empty_ledger(slug: str) -> dict[str, object]:
    now = _utc_now_iso()
    return {
        "schema": PRIVATE_SCHEMA,
        "slug": _safe_slug(slug),
        "created_at": now,
        "updated_at": now,
        "contributions": [],
    }


def _load_private_ledger(slug: str) -> dict[str, object]:
    path = private_contribution_path(slug)
    if path.is_symlink():
        raise MemorialContributionError("memorial_contribution_store_invalid")
    if not path.is_file():
        return _empty_ledger(slug)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise MemorialContributionError("memorial_contribution_store_invalid") from exc
    if (
        not isinstance(payload, dict)
        or payload.get("schema") != PRIVATE_SCHEMA
        or not isinstance(payload.get("contributions"), list)
    ):
        raise MemorialContributionError("memorial_contribution_store_invalid")
    if str(payload.get("slug") or "") != _safe_slug(slug):
        raise MemorialContributionError("memorial_contribution_store_invalid")
    rows = payload.get("contributions")
    if len(rows) > MAX_CONTRIBUTIONS or any(not isinstance(row, dict) for row in rows):
        raise MemorialContributionError("memorial_contribution_store_invalid")
    return dict(payload)


def _save_private_ledger(slug: str, ledger: dict[str, object]) -> None:
    stored = dict(ledger)
    stored["schema"] = PRIVATE_SCHEMA
    stored["slug"] = _safe_slug(slug)
    stored["updated_at"] = _utc_now_iso()
    _write_json_atomic(private_contribution_path(slug), stored, mode=0o600)


def _empty_takedown_ledger(slug: str) -> dict[str, object]:
    return {
        "schema": TAKEDOWN_SCHEMA,
        "slug": _safe_slug(slug),
        "generated_at": _utc_now_iso(),
        "takedowns": [],
    }


def _load_takedown_ledger(slug: str) -> dict[str, object]:
    safe_slug = _safe_slug(slug)
    path = public_takedown_path(safe_slug)
    if path.is_symlink():
        raise MemorialContributionError("memorial_contribution_store_invalid")
    if not path.is_file():
        return _empty_takedown_ledger(safe_slug)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        rows = payload.get("takedowns") if isinstance(payload, dict) else None
        if (
            not isinstance(payload, dict)
            or payload.get("schema") != TAKEDOWN_SCHEMA
            or str(payload.get("slug") or "") != safe_slug
            or not isinstance(rows, list)
            or len(rows) > MAX_CONTRIBUTIONS
        ):
            raise ValueError("invalid_takedown_ledger")
        seen_ids: set[str] = set()
        normalized_rows: list[dict[str, object]] = []
        allowed_keys = {"contribution_id", "status", "recorded_at", "updated_at"}
        for row in rows:
            if not isinstance(row, dict) or set(row) != allowed_keys:
                raise ValueError("invalid_takedown_row")
            contribution_id = str(row.get("contribution_id") or "")
            status_value = str(row.get("status") or "")
            recorded_at = str(row.get("recorded_at") or "")
            updated_at = str(row.get("updated_at") or "")
            if (
                _CONTRIBUTION_ID_RE.fullmatch(contribution_id) is None
                or contribution_id in seen_ids
                or status_value not in _TAKEDOWN_STATUSES
                or not recorded_at
                or len(recorded_at) > 80
                or not updated_at
                or len(updated_at) > 80
            ):
                raise ValueError("invalid_takedown_row")
            seen_ids.add(contribution_id)
            normalized_rows.append(
                {
                    "contribution_id": contribution_id,
                    "status": status_value,
                    "recorded_at": recorded_at,
                    "updated_at": updated_at,
                }
            )
    except MemorialContributionError:
        raise
    except Exception as exc:
        raise MemorialContributionError("memorial_contribution_store_invalid") from exc
    return {
        "schema": TAKEDOWN_SCHEMA,
        "slug": safe_slug,
        "generated_at": str(payload.get("generated_at") or "")[:80],
        "takedowns": normalized_rows,
    }


def _save_takedown_ledger(slug: str, ledger: dict[str, object]) -> None:
    stored = {
        "schema": TAKEDOWN_SCHEMA,
        "slug": _safe_slug(slug),
        "generated_at": _utc_now_iso(),
        "takedowns": list(ledger.get("takedowns") or []),
    }
    _write_json_atomic(public_takedown_path(slug), stored, mode=0o644)


def _takedown_ids(slug: str) -> set[str]:
    return {
        str(row.get("contribution_id") or "")
        for row in list(_load_takedown_ledger(slug).get("takedowns") or [])
        if isinstance(row, dict) and str(row.get("contribution_id") or "")
    }


def _record_takedown(
    *, slug: str, contribution_id: str, status_value: str, recorded_at: str
) -> None:
    if status_value not in _TAKEDOWN_STATUSES:
        raise MemorialContributionError("memorial_contribution_store_invalid")
    safe_id = str(contribution_id or "")
    if _CONTRIBUTION_ID_RE.fullmatch(safe_id) is None:
        raise MemorialContributionError("memorial_contribution_store_invalid")
    ledger = _load_takedown_ledger(slug)
    rows = [dict(row) for row in list(ledger.get("takedowns") or []) if isinstance(row, dict)]
    prior = next(
        (
            row
            for row in rows
            if hmac.compare_digest(
                str(row.get("contribution_id") or ""), safe_id
            )
        ),
        None,
    )
    replacement = {
        "contribution_id": safe_id,
        "status": status_value,
        "recorded_at": str((prior or {}).get("recorded_at") or recorded_at),
        "updated_at": recorded_at,
    }
    rows = [row for row in rows if str(row.get("contribution_id") or "") != safe_id]
    rows.append(replacement)
    rows.sort(key=lambda row: str(row.get("contribution_id") or ""))
    ledger["takedowns"] = rows
    _save_takedown_ledger(slug, ledger)


def _clear_takedown(*, slug: str, contribution_id: str) -> None:
    ledger = _load_takedown_ledger(slug)
    rows = [dict(row) for row in list(ledger.get("takedowns") or []) if isinstance(row, dict)]
    remaining = [
        row
        for row in rows
        if not hmac.compare_digest(
            str(row.get("contribution_id") or ""), str(contribution_id or "")
        )
    ]
    if len(remaining) == len(rows):
        return
    ledger["takedowns"] = remaining
    _save_takedown_ledger(slug, ledger)


def _append_history_event(
    record: dict[str, object], event: dict[str, object]
) -> tuple[list[dict[str, object]], dict[str, object]]:
    raw_history = record.get("history")
    history = (
        [dict(item) for item in raw_history if isinstance(item, dict)]
        if isinstance(raw_history, list)
        else []
    )
    raw_compaction = record.get("history_compaction")
    if raw_compaction is None:
        evicted_count = 0
        evicted_digest = _EMPTY_HISTORY_DIGEST
    elif (
        isinstance(raw_compaction, dict)
        and set(raw_compaction)
        == {"schema", "evicted_count", "evicted_sha256"}
        and raw_compaction.get("schema") == HISTORY_COMPACTION_SCHEMA
        and isinstance(raw_compaction.get("evicted_count"), int)
        and not isinstance(raw_compaction.get("evicted_count"), bool)
        and 0 <= int(raw_compaction["evicted_count"]) <= 1_000_000_000
        and re.fullmatch(
            r"[0-9a-f]{64}", str(raw_compaction.get("evicted_sha256") or "")
        )
    ):
        evicted_count = int(raw_compaction["evicted_count"])
        evicted_digest = str(raw_compaction["evicted_sha256"])
    else:
        raise MemorialContributionError("memorial_contribution_store_invalid")

    overflow = max(0, len(history) + 1 - MAX_HISTORY_EVENTS)
    for evicted in history[:overflow]:
        canonical_event = json.dumps(
            evicted,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        evicted_digest = hashlib.sha256(
            bytes.fromhex(evicted_digest) + b"\x00" + canonical_event
        ).hexdigest()
        evicted_count += 1
    compacted_history = [*history[overflow:], dict(event)]
    return compacted_history, {
        "schema": HISTORY_COMPACTION_SCHEMA,
        "evicted_count": evicted_count,
        "evicted_sha256": evicted_digest,
    }


def _public_projection_rows(
    records: list[dict[str, object]],
    *,
    blocked_ids: set[str] | None = None,
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    published = sorted(
        records,
        key=lambda row: str(row.get("published_at") or row.get("updated_at") or ""),
        reverse=True,
    )
    for record in published:
        contribution_id = str(record.get("contribution_id") or "")
        if contribution_id and contribution_id in (blocked_ids or set()):
            continue
        if record.get("status") != "published" or record.get("visibility") != "public":
            continue
        memory = record.get("public_memory")
        if not isinstance(memory, dict):
            continue
        try:
            title = _bounded_text(
                memory.get("title"),
                field="title",
                max_chars=MAX_TITLE_CHARS,
                required=True,
            )
            body = _bounded_text(
                memory.get("body"),
                field="body",
                max_chars=MAX_BODY_CHARS,
                required=True,
            )
            source_label = (
                _bounded_text(
                    memory.get("source_label"),
                    field="source_label",
                    max_chars=MAX_SOURCE_LABEL_CHARS,
                )
                or "Erinnerung aus der Familie"
            )
        except MemorialContributionError:
            continue
        rows.append(
            {
                "contribution_id": str(record.get("contribution_id") or ""),
                "visibility": "public",
                "public": True,
                "source_label": source_label,
                "title": title,
                "body": body,
                "public_excerpt": body,
            }
        )
    return rows[:MAX_CONTRIBUTIONS]


def _write_public_projection(
    slug: str,
    records: list[dict[str, object]],
    *,
    allow_takedown_ids: set[str] | None = None,
) -> None:
    now = _utc_now_iso()
    blocked_ids = _takedown_ids(slug)
    blocked_ids.difference_update(allow_takedown_ids or set())
    payload: dict[str, object] = {
        "schema": PUBLIC_SCHEMA,
        "slug": _safe_slug(slug),
        "generated_at": now,
        "memory_cards": _public_projection_rows(records, blocked_ids=blocked_ids),
    }
    _write_json_atomic(public_contribution_path(slug), payload, mode=0o644)


def _records(ledger: dict[str, object]) -> list[dict[str, object]]:
    raw = ledger.get("contributions")
    return (
        [dict(row) for row in raw if isinstance(row, dict)]
        if isinstance(raw, list)
        else []
    )


def _find_record(
    records: list[dict[str, object]], contribution_id: str
) -> tuple[int, dict[str, object]]:
    wanted = str(contribution_id or "").strip()
    for index, row in enumerate(records):
        if hmac.compare_digest(str(row.get("contribution_id") or ""), wanted):
            return index, row
    raise MemorialContributionError("memorial_contribution_not_found")


def _private_operator_projection(record: dict[str, object]) -> dict[str, object]:
    return {
        key: value for key, value in record.items() if key not in {"manage_token_hash"}
    }


def build_family_contribution_recovery_receipt(
    *,
    slug: str,
    record: dict[str, object],
    manage_token: str | None = None,
) -> dict[str, object]:
    contribution_id = str(record.get("contribution_id") or "")
    receipt: dict[str, object] = {
        "schema_version": RECOVERY_RECEIPT_SCHEMA,
        "contribution_id": contribution_id,
        "status": str(record.get("status") or ""),
        "visibility": str(record.get("visibility") or "private"),
        "manage_token_header": "x-memorial-contribution-token",
        "status_path": f"/memorials/{_safe_slug(slug)}/contributions/{contribution_id}/status",
        "token_recoverable": False,
    }
    if manage_token is not None:
        receipt["manage_token"] = str(manage_token)
    return receipt


def _takedown_for_record(
    *, slug: str, record: dict[str, object]
) -> dict[str, object]:
    contribution_id = str(record.get("contribution_id") or "")
    return next(
        (
            dict(row)
            for row in list(_load_takedown_ledger(slug).get("takedowns") or [])
            if isinstance(row, dict)
            and hmac.compare_digest(
                str(row.get("contribution_id") or ""), contribution_id
            )
        ),
        {},
    )


def _safe_submission_for_management(record: dict[str, object]) -> dict[str, str]:
    raw_submission = record.get("submission")
    if not isinstance(raw_submission, dict):
        raise MemorialContributionError("memorial_contribution_store_invalid")
    try:
        return {
            "title": _bounded_text(
                raw_submission.get("title"),
                field="title",
                max_chars=MAX_TITLE_CHARS,
                required=True,
            ),
            "body": _bounded_text(
                raw_submission.get("body"),
                field="body",
                max_chars=MAX_BODY_CHARS,
                required=True,
            ),
            "source_label": _bounded_text(
                raw_submission.get("source_label"),
                field="source_label",
                max_chars=MAX_SOURCE_LABEL_CHARS,
            ),
            "contributor_name": _bounded_text(
                raw_submission.get("contributor_name"),
                field="contributor_name",
                max_chars=MAX_PERSON_CHARS,
            ),
            "relationship": _bounded_text(
                raw_submission.get("relationship"),
                field="relationship",
                max_chars=MAX_RELATIONSHIP_CHARS,
            ),
        }
    except MemorialContributionError as exc:
        raise MemorialContributionError(
            "memorial_contribution_store_invalid"
        ) from exc


def get_family_contribution_for_management(
    *, slug: str, contribution_id: str, manage_token: str
) -> dict[str, object]:
    safe_slug = _safe_slug(slug)
    with _contribution_lock(safe_slug):
        records = _records(_load_private_ledger(safe_slug))
        _index, record = _find_record(records, contribution_id)
        _verify_manage_token(record, manage_token)
        takedown = _takedown_for_record(slug=safe_slug, record=record)
        submission = _safe_submission_for_management(record)
        proposal, proposal_binding = _stored_public_proposal(
            slug=safe_slug,
            record=record,
        )
        proposal_decision = _stored_proposal_decision(record)
        erasure_request = _stored_erasure_request(record)
        if proposal_decision and (
            not proposal_binding
            or not hmac.compare_digest(
                str(proposal_decision.get("proposal_sha256") or ""),
                str(proposal_binding.get("sha256") or ""),
            )
        ):
            raise MemorialContributionError("memorial_contribution_store_invalid")

    status_value = str(takedown.get("status") or record.get("status") or "")
    effective_visibility = (
        "private" if takedown else str(record.get("visibility") or "private")
    )
    public_preview: dict[str, str] = {}
    if status_value == "published" and effective_visibility == "public":
        raw_public_memory = record.get("public_memory")
        if not isinstance(raw_public_memory, dict):
            raise MemorialContributionError("memorial_contribution_store_invalid")
        try:
            public_preview = _bounded_public_version(dict(raw_public_memory))
        except MemorialContributionError as exc:
            raise MemorialContributionError(
                "memorial_contribution_store_invalid"
            ) from exc

    proposal_payload: dict[str, object] = {}
    if proposal:
        proposal_payload = {
            **proposal,
            "sha256": str(proposal_binding.get("sha256") or ""),
            "proposed_at": str(proposal_binding.get("proposed_at") or ""),
            "decision": str(proposal_decision.get("decision") or "pending"),
            "decided_at": str(proposal_decision.get("decided_at") or ""),
        }

    timestamps = {
        key: str(record.get(key) or "")
        for key in (
            "submitted_at",
            "updated_at",
            "published_at",
            "withdrawn_at",
            "rejected_at",
            "unpublished_at",
            "erasure_requested_at",
        )
        if str(record.get(key) or "")
    }
    if takedown:
        timestamps["takedown_recorded_at"] = str(
            takedown.get("recorded_at") or ""
        )
        timestamps["takedown_updated_at"] = str(
            takedown.get("updated_at") or ""
        )
    if proposal_binding:
        timestamps["proposed_at"] = str(
            proposal_binding.get("proposed_at") or ""
        )
    if proposal_decision:
        timestamps["proposal_decided_at"] = str(
            proposal_decision.get("decided_at") or ""
        )

    has_current_proposal = bool(proposal and proposal_binding)
    can_manage = status_value not in {"withdrawn", "erasure_requested"}
    erasure_path = (
        f"/memorials/{safe_slug}/contributions/"
        f"{str(record.get('contribution_id') or '')}/erasure-request"
    )
    return {
        "contribution_id": str(record.get("contribution_id") or ""),
        "status": status_value,
        "visibility": effective_visibility,
        "publication_consent": record.get("publication_consent") is True,
        "submission": submission,
        "public_preview": public_preview,
        "public_proposal": proposal_payload,
        "erasure_request": dict(erasure_request),
        "timestamps": timestamps,
        "actions": {
            "can_correct": can_manage,
            "can_withdraw": can_manage,
            "can_approve_public_proposal": has_current_proposal
            and status_value
            in {"awaiting_contributor_approval", "proposal_rejected"},
            "can_reject_public_proposal": has_current_proposal
            and status_value
            in {"awaiting_contributor_approval", "approved_for_publication"},
            "can_request_permanent_erasure": not erasure_request,
        },
        "retention_notice": {
            "withdrawal_removes_public_copy": True,
            "private_record_retained_for_governance": True,
            "permanent_erasure_requires_separate_request": True,
            "permanent_erasure_self_service_available": True,
            "private_record_retained_until_governed_completion": True,
            "permanent_erasure_completed": False,
            "data_deletion_path": erasure_path,
        },
    }


def get_family_contribution_status(
    *, slug: str, contribution_id: str, manage_token: str
) -> dict[str, object]:
    safe_slug = _safe_slug(slug)
    with _contribution_lock(safe_slug):
        records = _records(_load_private_ledger(safe_slug))
        _index, record = _find_record(records, contribution_id)
        _verify_manage_token(record, manage_token)
        takedown = _takedown_for_record(slug=safe_slug, record=record)
        erasure_request = _stored_erasure_request(record)
    status_value = str(takedown.get("status") or record.get("status") or "")
    effective_visibility = "private" if takedown else str(record.get("visibility") or "private")
    timestamps = {
        key: str(record.get(key) or "")
        for key in (
            "submitted_at",
            "updated_at",
            "published_at",
            "withdrawn_at",
            "rejected_at",
            "unpublished_at",
            "erasure_requested_at",
        )
        if str(record.get(key) or "")
    }
    if takedown:
        timestamps["takedown_recorded_at"] = str(takedown.get("recorded_at") or "")
        timestamps["takedown_updated_at"] = str(takedown.get("updated_at") or "")
    receipt_record = {
        "contribution_id": str(record.get("contribution_id") or ""),
        "status": status_value,
        "visibility": effective_visibility,
    }
    return {
        "contribution_id": str(record.get("contribution_id") or ""),
        "status": status_value,
        "visibility": effective_visibility,
        "publication_consent": record.get("publication_consent") is True,
        "timestamps": timestamps,
        "actions": {
            "can_correct": status_value not in {"withdrawn", "erasure_requested"},
            "can_withdraw": status_value not in {"withdrawn", "erasure_requested"},
            "can_request_permanent_erasure": not erasure_request,
        },
        "erasure_request": {
            key: erasure_request[key]
            for key in (
                "state",
                "requested_at",
                "public_removed",
                "permanent_erasure_completed",
            )
            if key in erasure_request
        },
        "recovery_receipt": build_family_contribution_recovery_receipt(
            slug=safe_slug, record=receipt_record
        ),
    }


def _verify_manage_token(record: dict[str, object], manage_token: str) -> None:
    expected = str(record.get("manage_token_hash") or "")
    provided = _token_hash(manage_token) if str(manage_token or "").strip() else ""
    if not expected or not provided or not hmac.compare_digest(expected, provided):
        raise MemorialContributionError("memorial_contribution_unauthorized")


def submit_family_contribution(
    *, slug: str, payload: dict[str, object]
) -> tuple[dict[str, object], str]:
    safe_slug = _safe_slug(slug)
    submission = {
        "title": _bounded_text(
            payload.get("title"),
            field="title",
            max_chars=MAX_TITLE_CHARS,
            required=True,
        ),
        "body": _bounded_text(
            payload.get("body"), field="body", max_chars=MAX_BODY_CHARS, required=True
        ),
        "source_label": _bounded_text(
            payload.get("source_label"),
            field="source_label",
            max_chars=MAX_SOURCE_LABEL_CHARS,
        ),
        "contributor_name": _bounded_text(
            payload.get("contributor_name"),
            field="contributor_name",
            max_chars=MAX_PERSON_CHARS,
        ),
        "relationship": _bounded_text(
            payload.get("relationship"),
            field="relationship",
            max_chars=MAX_RELATIONSHIP_CHARS,
        ),
    }
    publication_consent = payload.get("publication_consent")
    if not isinstance(publication_consent, bool):
        raise MemorialContributionError(
            "memorial_contribution_publication_consent_invalid"
        )
    manage_token = secrets.token_urlsafe(32)
    now = _utc_now_iso()
    record: dict[str, object] = {
        "contribution_id": str(uuid.uuid4()),
        "status": "pending_review",
        "visibility": "private",
        "submission": submission,
        "publication_consent": publication_consent,
        "manage_token_hash": _token_hash(manage_token),
        "submitted_at": now,
        "updated_at": now,
        "published_at": "",
        "review": {},
        "public_memory": {},
        "erasure_request": {},
        "history": [],
    }
    with _contribution_lock(safe_slug):
        ledger = _load_private_ledger(safe_slug)
        records = _records(ledger)
        if len(records) >= MAX_CONTRIBUTIONS:
            raise MemorialContributionError("memorial_contribution_store_full")
        records.append(record)
        ledger["contributions"] = records
        _save_private_ledger(safe_slug, ledger)
    return _private_operator_projection(record), manage_token


def list_family_contributions_for_operator(*, slug: str) -> list[dict[str, object]]:
    safe_slug = _safe_slug(slug)
    with _contribution_lock(safe_slug):
        records = _records(_load_private_ledger(safe_slug))
    records.sort(
        key=lambda row: str(row.get("updated_at") or row.get("submitted_at") or ""),
        reverse=True,
    )
    return [_private_operator_projection(row) for row in records]


def _required_proposal_sha256(payload: dict[str, object]) -> str:
    proposal_sha256 = _bounded_text(
        payload.get("proposal_sha256"),
        field="proposal_sha256",
        max_chars=64,
        required=True,
    )
    if _SHA256_RE.fullmatch(proposal_sha256) is None:
        raise MemorialContributionError(
            "memorial_contribution_proposal_sha256_invalid"
        )
    return proposal_sha256


def propose_family_contribution_public_version(
    *,
    slug: str,
    contribution_id: str,
    payload: dict[str, object],
) -> dict[str, object]:
    safe_slug = _safe_slug(slug)
    public_proposal = _bounded_public_version(payload)
    reviewer = _bounded_text(
        payload.get("reviewer"),
        field="reviewer",
        max_chars=MAX_PERSON_CHARS,
        required=True,
    )
    review_note = _bounded_text(
        payload.get("review_note"),
        field="review_note",
        max_chars=MAX_NOTE_CHARS,
    )
    with _contribution_lock(safe_slug):
        ledger = _load_private_ledger(safe_slug)
        records = _records(ledger)
        index, current = _find_record(records, contribution_id)
        if current.get("publication_consent") is not True:
            raise MemorialContributionError(
                "memorial_contribution_publication_consent_required"
            )
        takedown_status = str(
            _takedown_for_record(slug=safe_slug, record=current).get("status")
            or ""
        )
        if takedown_status and takedown_status not in {
            "correction_pending",
            "unpublished",
        }:
            raise MemorialContributionError(
                "memorial_contribution_not_proposable"
            )
        if str(current.get("status") or "") not in {
            "pending_review",
            "correction_pending",
            "awaiting_contributor_approval",
            "approved_for_publication",
            "proposal_rejected",
            "unpublished",
        }:
            raise MemorialContributionError(
                "memorial_contribution_not_proposable"
            )
        _prior_proposal, prior_binding = _stored_public_proposal(
            slug=safe_slug,
            record=current,
        )
        now = _utc_now_iso()
        proposal_sha256 = _public_proposal_sha256(
            slug=safe_slug,
            contribution_id=str(current.get("contribution_id") or ""),
            public_version=public_proposal,
        )
        history, history_compaction = _append_history_event(
            current,
            {
                "action": "operator_proposed_public_version",
                "from_status": str(current.get("status") or ""),
                "to_status": "awaiting_contributor_approval",
                "reviewer": reviewer,
                "reason": review_note,
                "proposal_sha256": proposal_sha256,
                "prior_proposal_sha256": str(
                    prior_binding.get("sha256") or ""
                ),
                "recorded_at": now,
            },
        )
        updated = dict(current)
        updated.update(
            {
                "status": "awaiting_contributor_approval",
                "visibility": "private",
                "updated_at": now,
                "review": {},
                "public_memory": {},
                "public_proposal": public_proposal,
                "public_proposal_binding": {
                    "schema": PUBLIC_PROPOSAL_BINDING_SCHEMA,
                    "sha256": proposal_sha256,
                    "proposed_at": now,
                },
                "public_proposal_review": {
                    "reviewer": reviewer,
                    "review_note": review_note,
                    "proposed_at": now,
                },
                "public_proposal_decision": {},
                "history": history,
                "history_compaction": history_compaction,
            }
        )
        records[index] = updated
        ledger["contributions"] = records
        _save_private_ledger(safe_slug, ledger)
    return _private_operator_projection(updated)


def _decide_family_contribution_public_proposal(
    *,
    slug: str,
    contribution_id: str,
    manage_token: str,
    payload: dict[str, object],
    decision: str,
) -> dict[str, object]:
    safe_slug = _safe_slug(slug)
    proposal_sha256 = _required_proposal_sha256(payload)
    contributor_note = _bounded_text(
        payload.get("contributor_note"),
        field="contributor_note",
        max_chars=MAX_NOTE_CHARS,
    )
    if decision not in {"approved", "rejected"}:
        raise MemorialContributionError(
            "memorial_contribution_proposal_decision_invalid"
        )
    target_status = (
        "approved_for_publication" if decision == "approved" else "proposal_rejected"
    )
    with _contribution_lock(safe_slug):
        ledger = _load_private_ledger(safe_slug)
        records = _records(ledger)
        index, current = _find_record(records, contribution_id)
        _verify_manage_token(current, manage_token)
        if current.get("publication_consent") is not True:
            raise MemorialContributionError(
                "memorial_contribution_publication_consent_required"
            )
        takedown_status = str(
            _takedown_for_record(slug=safe_slug, record=current).get("status")
            or ""
        )
        if takedown_status and takedown_status not in {
            "correction_pending",
            "unpublished",
        }:
            raise MemorialContributionError(
                "memorial_contribution_proposal_not_decidable"
            )
        _proposal, binding = _stored_public_proposal(
            slug=safe_slug,
            record=current,
            required=True,
        )
        current_sha256 = str(binding.get("sha256") or "")
        if not hmac.compare_digest(proposal_sha256, current_sha256):
            raise MemorialContributionError(
                "memorial_contribution_proposal_stale"
            )
        existing_decision = _stored_proposal_decision(current)
        if (
            str(current.get("status") or "") == target_status
            and existing_decision.get("decision") == decision
            and hmac.compare_digest(
                str(existing_decision.get("proposal_sha256") or ""),
                current_sha256,
            )
        ):
            return _private_operator_projection(current)
        if str(current.get("status") or "") not in {
            "awaiting_contributor_approval",
            "approved_for_publication",
            "proposal_rejected",
        }:
            raise MemorialContributionError(
                "memorial_contribution_proposal_not_decidable"
            )
        now = _utc_now_iso()
        history, history_compaction = _append_history_event(
            current,
            {
                "action": f"contributor_{decision}_public_proposal",
                "from_status": str(current.get("status") or ""),
                "to_status": target_status,
                "proposal_sha256": current_sha256,
                "reason": contributor_note,
                "recorded_at": now,
            },
        )
        updated = dict(current)
        updated.update(
            {
                "status": target_status,
                "visibility": "private",
                "updated_at": now,
                "public_proposal_decision": {
                    "schema": PUBLIC_PROPOSAL_DECISION_SCHEMA,
                    "decision": decision,
                    "proposal_sha256": current_sha256,
                    "decided_at": now,
                    "contributor_note": contributor_note,
                },
                "history": history,
                "history_compaction": history_compaction,
            }
        )
        records[index] = updated
        ledger["contributions"] = records
        _save_private_ledger(safe_slug, ledger)
    return _private_operator_projection(updated)


def approve_family_contribution_public_proposal(
    *,
    slug: str,
    contribution_id: str,
    manage_token: str,
    payload: dict[str, object],
) -> dict[str, object]:
    return _decide_family_contribution_public_proposal(
        slug=slug,
        contribution_id=contribution_id,
        manage_token=manage_token,
        payload=payload,
        decision="approved",
    )


def reject_family_contribution_public_proposal(
    *,
    slug: str,
    contribution_id: str,
    manage_token: str,
    payload: dict[str, object],
) -> dict[str, object]:
    return _decide_family_contribution_public_proposal(
        slug=slug,
        contribution_id=contribution_id,
        manage_token=manage_token,
        payload=payload,
        decision="rejected",
    )


def approve_family_contribution(
    *,
    slug: str,
    contribution_id: str,
    payload: dict[str, object],
) -> dict[str, object]:
    safe_slug = _safe_slug(slug)
    requested_proposal_sha256 = _required_proposal_sha256(payload)
    reviewer = _bounded_text(
        payload.get("reviewer"),
        field="reviewer",
        max_chars=MAX_PERSON_CHARS,
        required=True,
    )
    review_note = _bounded_text(
        payload.get("review_note"), field="review_note", max_chars=MAX_NOTE_CHARS
    )
    with _contribution_lock(safe_slug):
        ledger = _load_private_ledger(safe_slug)
        records = _records(ledger)
        index, current = _find_record(records, contribution_id)
        if current.get("status") != "approved_for_publication":
            raise MemorialContributionError("memorial_contribution_not_reviewable")
        if current.get("publication_consent") is not True:
            raise MemorialContributionError(
                "memorial_contribution_publication_consent_required"
            )
        takedown_status = str(
            _takedown_for_record(slug=safe_slug, record=current).get("status")
            or ""
        )
        if takedown_status and takedown_status not in {
            "correction_pending",
            "unpublished",
        }:
            raise MemorialContributionError(
                "memorial_contribution_not_reviewable"
            )
        public_memory, proposal_binding = _stored_public_proposal(
            slug=safe_slug,
            record=current,
            required=True,
        )
        proposal_sha256 = str(proposal_binding.get("sha256") or "")
        if not hmac.compare_digest(
            requested_proposal_sha256, proposal_sha256
        ):
            raise MemorialContributionError(
                "memorial_contribution_proposal_stale"
            )
        proposal_decision = _stored_proposal_decision(current)
        if (
            proposal_decision.get("decision") != "approved"
            or not hmac.compare_digest(
                str(proposal_decision.get("proposal_sha256") or ""),
                proposal_sha256,
            )
        ):
            raise MemorialContributionError(
                "memorial_contribution_proposal_not_approved"
            )
        if {"source_label", "title", "body"}.intersection(payload):
            echoed_public_memory = _bounded_public_version(
                {
                    key: payload.get(key, public_memory[key])
                    for key in ("source_label", "title", "body")
                }
            )
            if echoed_public_memory != public_memory:
                raise MemorialContributionError(
                    "memorial_contribution_proposal_payload_mismatch"
                )
        now = _utc_now_iso()
        history, history_compaction = _append_history_event(
            current,
            {
                "action": "operator_published_approved_proposal",
                "from_status": str(current.get("status") or ""),
                "to_status": "published",
                "reviewer": reviewer,
                "reason": review_note,
                "proposal_sha256": proposal_sha256,
                "prior_review": dict(current.get("review") or {}),
                "prior_public_memory": dict(current.get("public_memory") or {}),
                "recorded_at": now,
            },
        )
        updated = dict(current)
        updated.update(
            {
                "status": "published",
                "visibility": "public",
                "updated_at": now,
                "published_at": now,
                "review": {
                    "reviewer": reviewer,
                    "review_note": review_note,
                    "approved_at": now,
                    "proposal_sha256": proposal_sha256,
                },
                "public_memory": public_memory,
                "history": history,
                "history_compaction": history_compaction,
            }
        )
        records[index] = updated
        ledger["contributions"] = records
        # Keep any existing tombstone active while the newly approved projection is
        # materialized. Clearing it is the final publication step.
        _save_private_ledger(safe_slug, ledger)
        _write_public_projection(
            safe_slug,
            records,
            allow_takedown_ids={str(updated.get("contribution_id") or "")},
        )
        _clear_takedown(
            slug=safe_slug,
            contribution_id=str(updated.get("contribution_id") or ""),
        )
    return _private_operator_projection(updated)


def correct_family_contribution(
    *,
    slug: str,
    contribution_id: str,
    manage_token: str,
    payload: dict[str, object],
) -> dict[str, object]:
    safe_slug = _safe_slug(slug)
    with _contribution_lock(safe_slug):
        ledger = _load_private_ledger(safe_slug)
        records = _records(ledger)
        index, current = _find_record(records, contribution_id)
        _verify_manage_token(current, manage_token)
        if _stored_erasure_request(current):
            raise MemorialContributionError(
                "memorial_contribution_erasure_pending"
            )
        if current.get("status") == "withdrawn":
            raise MemorialContributionError("memorial_contribution_withdrawn")
        _prior_proposal, prior_proposal_binding = _stored_public_proposal(
            slug=safe_slug,
            record=current,
        )
        submission = dict(current.get("submission") or {})
        changed = False
        for key, limit, required in (
            ("title", MAX_TITLE_CHARS, True),
            ("body", MAX_BODY_CHARS, True),
            ("source_label", MAX_SOURCE_LABEL_CHARS, False),
            ("contributor_name", MAX_PERSON_CHARS, False),
            ("relationship", MAX_RELATIONSHIP_CHARS, False),
        ):
            if key not in payload:
                continue
            replacement = _bounded_text(
                payload.get(key), field=key, max_chars=limit, required=required
            )
            changed = changed or replacement != submission.get(key)
            submission[key] = replacement
        publication_consent = current.get("publication_consent") is True
        if "publication_consent" in payload:
            if not isinstance(payload.get("publication_consent"), bool):
                raise MemorialContributionError(
                    "memorial_contribution_publication_consent_invalid"
                )
            changed = (
                changed or payload["publication_consent"] is not publication_consent
            )
            publication_consent = bool(payload["publication_consent"])
        correction_reason = _bounded_text(
            payload.get("correction_reason"),
            field="correction_reason",
            max_chars=MAX_NOTE_CHARS,
        )
        if not changed:
            raise MemorialContributionError("memorial_contribution_correction_required")
        now = _utc_now_iso()
        _record_takedown(
            slug=safe_slug,
            contribution_id=str(current.get("contribution_id") or ""),
            status_value="correction_pending",
            recorded_at=now,
        )
        history, history_compaction = _append_history_event(
            current,
            {
                "action": "contributor_corrected",
                "from_status": str(current.get("status") or ""),
                "to_status": "correction_pending",
                "reason": correction_reason,
                "prior_review": dict(current.get("review") or {}),
                "prior_public_memory": dict(current.get("public_memory") or {}),
                "prior_proposal_sha256": str(
                    prior_proposal_binding.get("sha256") or ""
                ),
                "recorded_at": now,
            },
        )
        updated = dict(current)
        updated.update(
            {
                "status": "correction_pending",
                "visibility": "private",
                "submission": submission,
                "publication_consent": publication_consent,
                "updated_at": now,
                "review": {},
                "public_memory": {},
                "public_proposal": {},
                "public_proposal_binding": {},
                "public_proposal_review": {},
                "public_proposal_decision": {},
                "correction_reason": correction_reason,
                "history": history,
                "history_compaction": history_compaction,
            }
        )
        records[index] = updated
        ledger["contributions"] = records
        # The independent public-safe tombstone is the durable first write. It is
        # consulted both by projection builds and by public reads.
        _write_public_projection(safe_slug, records)
        _save_private_ledger(safe_slug, ledger)
    return _private_operator_projection(updated)


def withdraw_family_contribution(
    *,
    slug: str,
    contribution_id: str,
    manage_token: str,
    reason: object = "",
) -> dict[str, object]:
    safe_slug = _safe_slug(slug)
    with _contribution_lock(safe_slug):
        ledger = _load_private_ledger(safe_slug)
        records = _records(ledger)
        index, current = _find_record(records, contribution_id)
        _verify_manage_token(current, manage_token)
        # A caller can lose the first response after the private withdrawal
        # commit.  Authenticate before recognizing that terminal state, then
        # return it without appending a second history event or rewriting any
        # ledger.  This lets the holder of this record's capability retry while
        # tokens for other records still fail closed.
        if current.get("status") == "withdrawn":
            return _private_operator_projection(current)
        if _stored_erasure_request(current):
            raise MemorialContributionError(
                "memorial_contribution_erasure_pending"
            )
        withdrawal_reason = _bounded_text(
            reason, field="withdrawal_reason", max_chars=MAX_NOTE_CHARS
        )
        now = _utc_now_iso()
        _record_takedown(
            slug=safe_slug,
            contribution_id=str(current.get("contribution_id") or ""),
            status_value="withdrawn",
            recorded_at=now,
        )
        history, history_compaction = _append_history_event(
            current,
            {
                "action": "contributor_withdrew",
                "from_status": str(current.get("status") or ""),
                "to_status": "withdrawn",
                "reason": withdrawal_reason,
                "prior_review": dict(current.get("review") or {}),
                "prior_public_memory": dict(current.get("public_memory") or {}),
                "recorded_at": now,
            },
        )
        updated = dict(current)
        updated.update(
            {
                "status": "withdrawn",
                "visibility": "private",
                "updated_at": now,
                "withdrawn_at": now,
                "withdrawal_reason": withdrawal_reason,
                "public_memory": {},
                "history": history,
                "history_compaction": history_compaction,
            }
        )
        records[index] = updated
        ledger["contributions"] = records
        _write_public_projection(safe_slug, records)
        _save_private_ledger(safe_slug, ledger)
    return _private_operator_projection(updated)


def request_family_contribution_erasure(
    *,
    slug: str,
    contribution_id: str,
    manage_token: str,
    confirmation: object,
    reason: object = "",
) -> dict[str, object]:
    safe_slug = _safe_slug(slug)
    with _contribution_lock(safe_slug):
        ledger = _load_private_ledger(safe_slug)
        records = _records(ledger)
        index, current = _find_record(records, contribution_id)
        _verify_manage_token(current, manage_token)
        if confirmation is not True:
            raise MemorialContributionError(
                "memorial_contribution_erasure_confirmation_required"
            )
        request_reason = _bounded_text(
            reason,
            field="erasure_reason",
            max_chars=MAX_NOTE_CHARS,
        )
        existing_request = _stored_erasure_request(current)
        if existing_request:
            _record_takedown(
                slug=safe_slug,
                contribution_id=str(current.get("contribution_id") or ""),
                status_value="erasure_requested",
                recorded_at=str(existing_request.get("requested_at") or ""),
            )
            _write_public_projection(safe_slug, records)
            return _private_operator_projection(current)

        now = _utc_now_iso()
        _record_takedown(
            slug=safe_slug,
            contribution_id=str(current.get("contribution_id") or ""),
            status_value="erasure_requested",
            recorded_at=now,
        )
        history, history_compaction = _append_history_event(
            current,
            {
                "action": "contributor_requested_permanent_erasure",
                "from_status": str(current.get("status") or ""),
                "to_status": "erasure_requested",
                "reason": request_reason,
                "prior_review": dict(current.get("review") or {}),
                "prior_public_memory": dict(current.get("public_memory") or {}),
                "recorded_at": now,
            },
        )
        erasure_request: dict[str, object] = {
            "schema": ERASURE_REQUEST_SCHEMA,
            "state": "pending_operator_review",
            "requested_at": now,
            "reason": request_reason,
            "scope": list(_ERASURE_REQUEST_SCOPE),
            "public_removed": True,
            "permanent_erasure_completed": False,
        }
        updated = dict(current)
        updated.update(
            {
                "status": "erasure_requested",
                "visibility": "private",
                "updated_at": now,
                "erasure_requested_at": now,
                "erasure_request": erasure_request,
                "review": {},
                "public_memory": {},
                "public_proposal": {},
                "public_proposal_binding": {},
                "public_proposal_review": {},
                "public_proposal_decision": {},
                "history": history,
                "history_compaction": history_compaction,
            }
        )
        records[index] = updated
        ledger["contributions"] = records
        # Public removal is durable before the private request state is saved.
        _write_public_projection(safe_slug, records)
        _save_private_ledger(safe_slug, ledger)
    return _private_operator_projection(updated)


def _operator_takedown_family_contribution(
    *,
    slug: str,
    contribution_id: str,
    payload: dict[str, object],
    expected_statuses: set[str],
    target_status: str,
    action: str,
    invalid_state_code: str,
) -> dict[str, object]:
    safe_slug = _safe_slug(slug)
    reviewer = _bounded_text(
        payload.get("reviewer"),
        field="reviewer",
        max_chars=MAX_PERSON_CHARS,
        required=True,
    )
    reason = _bounded_text(
        payload.get("reason"),
        field="reason",
        max_chars=MAX_NOTE_CHARS,
        required=True,
    )
    with _contribution_lock(safe_slug):
        ledger = _load_private_ledger(safe_slug)
        records = _records(ledger)
        index, current = _find_record(records, contribution_id)
        if str(current.get("status") or "") not in expected_statuses:
            raise MemorialContributionError(invalid_state_code)
        now = _utc_now_iso()
        _record_takedown(
            slug=safe_slug,
            contribution_id=str(current.get("contribution_id") or ""),
            status_value=target_status,
            recorded_at=now,
        )
        history, history_compaction = _append_history_event(
            current,
            {
                "action": action,
                "from_status": str(current.get("status") or ""),
                "to_status": target_status,
                "reviewer": reviewer,
                "reason": reason,
                "prior_review": dict(current.get("review") or {}),
                "prior_public_memory": dict(current.get("public_memory") or {}),
                "recorded_at": now,
            },
        )
        updated = dict(current)
        updated.update(
            {
                "status": target_status,
                "visibility": "private",
                "updated_at": now,
                f"{target_status}_at": now,
                "review": {
                    "reviewer": reviewer,
                    "review_note": reason,
                    f"{target_status}_at": now,
                },
                "public_memory": {},
                "history": history,
                "history_compaction": history_compaction,
            }
        )
        records[index] = updated
        ledger["contributions"] = records
        # This order makes removal durable across every individual write fault:
        # reads honor the tombstone even if projection or private-ledger writes fail.
        _write_public_projection(safe_slug, records)
        _save_private_ledger(safe_slug, ledger)
    return _private_operator_projection(updated)


def reject_family_contribution(
    *, slug: str, contribution_id: str, payload: dict[str, object]
) -> dict[str, object]:
    return _operator_takedown_family_contribution(
        slug=slug,
        contribution_id=contribution_id,
        payload=payload,
        expected_statuses={
            "pending_review",
            "correction_pending",
            "awaiting_contributor_approval",
            "approved_for_publication",
            "proposal_rejected",
        },
        target_status="rejected",
        action="operator_rejected",
        invalid_state_code="memorial_contribution_not_rejectable",
    )


def unpublish_family_contribution(
    *, slug: str, contribution_id: str, payload: dict[str, object]
) -> dict[str, object]:
    return _operator_takedown_family_contribution(
        slug=slug,
        contribution_id=contribution_id,
        payload=payload,
        expected_statuses={"published"},
        target_status="unpublished",
        action="operator_unpublished",
        invalid_state_code="memorial_contribution_not_unpublishable",
    )


def load_public_family_memory_cards(*, slug: str) -> list[dict[str, object]]:
    try:
        safe_slug = _safe_slug(slug)
        blocked_ids = _takedown_ids(safe_slug)
        path = public_contribution_path(safe_slug)
        if not path.is_file() or path.is_symlink():
            return []
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    if not isinstance(payload, dict) or payload.get("schema") != PUBLIC_SCHEMA:
        return []
    if str(payload.get("slug") or "") != safe_slug:
        return []
    raw_rows = payload.get("memory_cards")
    if not isinstance(raw_rows, list) or len(raw_rows) > MAX_CONTRIBUTIONS:
        return []
    safe_rows: list[dict[str, object]] = []
    for raw in raw_rows:
        contribution_id = str(raw.get("contribution_id") or "") if isinstance(raw, dict) else ""
        if (
            not isinstance(raw, dict)
            or (contribution_id and contribution_id in blocked_ids)
            or raw.get("visibility") != "public"
            or raw.get("public") is not True
        ):
            continue
        try:
            title = _bounded_text(
                raw.get("title"),
                field="title",
                max_chars=MAX_TITLE_CHARS,
                required=True,
            )
            body = _bounded_text(
                raw.get("body"), field="body", max_chars=MAX_BODY_CHARS, required=True
            )
            public_excerpt = _bounded_text(
                raw.get("public_excerpt"),
                field="body",
                max_chars=MAX_BODY_CHARS,
                required=True,
            )
            source_label = (
                _bounded_text(
                    raw.get("source_label"),
                    field="source_label",
                    max_chars=MAX_SOURCE_LABEL_CHARS,
                )
                or "Erinnerung aus der Familie"
            )
        except MemorialContributionError:
            continue
        # Only fields already accepted by the memorial public-memory projector leave this service.
        safe_rows.append(
            {
                "visibility": "public",
                "public": True,
                "source_label": source_label,
                "title": title,
                "body": body,
                "public_excerpt": public_excerpt,
            }
        )
    return safe_rows[:12]


def merge_public_family_contributions(
    *, slug: str, memorial: dict[str, object]
) -> dict[str, object]:
    payload = dict(memorial)
    contributions = load_public_family_memory_cards(slug=slug)
    existing = payload.get("memory_cards")
    existing_rows = list(existing) if isinstance(existing, list) else []
    payload["memory_cards"] = [*contributions, *existing_rows]
    return payload
