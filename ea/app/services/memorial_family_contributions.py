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
PRIVATE_FILENAME = "family_contributions.json"
PUBLIC_FILENAME = "family_contributions.public.json"
MAX_CONTRIBUTIONS = 500
MAX_TITLE_CHARS = 180
MAX_BODY_CHARS = 6000
MAX_SOURCE_LABEL_CHARS = 160
MAX_PERSON_CHARS = 160
MAX_RELATIONSHIP_CHARS = 160
MAX_NOTE_CHARS = 1000

_SLUG_RE = re.compile(r"^[A-Za-z0-9_-]{1,80}$")
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


def _public_projection_rows(
    records: list[dict[str, object]],
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    published = sorted(
        records,
        key=lambda row: str(row.get("published_at") or row.get("updated_at") or ""),
        reverse=True,
    )
    for record in published:
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


def _write_public_projection(slug: str, records: list[dict[str, object]]) -> None:
    now = _utc_now_iso()
    payload: dict[str, object] = {
        "schema": PUBLIC_SCHEMA,
        "slug": _safe_slug(slug),
        "generated_at": now,
        "memory_cards": _public_projection_rows(records),
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


def approve_family_contribution(
    *,
    slug: str,
    contribution_id: str,
    payload: dict[str, object],
) -> dict[str, object]:
    safe_slug = _safe_slug(slug)
    public_memory = {
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
            payload.get("body"), field="body", max_chars=MAX_BODY_CHARS, required=True
        ),
    }
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
        if current.get("status") not in {
            "pending_review",
            "correction_pending",
            "published",
        }:
            raise MemorialContributionError("memorial_contribution_not_reviewable")
        if current.get("publication_consent") is not True:
            raise MemorialContributionError(
                "memorial_contribution_publication_consent_required"
            )
        now = _utc_now_iso()
        history = (
            list(current.get("history") or [])
            if isinstance(current.get("history"), list)
            else []
        )
        if current.get("review") or current.get("public_memory"):
            history.append(
                {
                    "status": str(current.get("status") or ""),
                    "review": dict(current.get("review") or {}),
                    "public_memory": dict(current.get("public_memory") or {}),
                    "recorded_at": now,
                }
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
                },
                "public_memory": public_memory,
                "history": history[-10:],
            }
        )
        records[index] = updated
        ledger["contributions"] = records
        # Private state is authoritative; a failed projection remains fail-closed and can be retried idempotently.
        _save_private_ledger(safe_slug, ledger)
        _write_public_projection(safe_slug, records)
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
        if current.get("status") == "withdrawn":
            raise MemorialContributionError("memorial_contribution_withdrawn")
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
        history = (
            list(current.get("history") or [])
            if isinstance(current.get("history"), list)
            else []
        )
        history.append(
            {
                "status": str(current.get("status") or ""),
                "review": dict(current.get("review") or {}),
                "public_memory": dict(current.get("public_memory") or {}),
                "recorded_at": now,
            }
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
                "correction_reason": correction_reason,
                "history": history[-10:],
            }
        )
        records[index] = updated
        ledger["contributions"] = records
        # Removal is written first so a partial failure cannot leave corrected raw content public.
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
    withdrawal_reason = _bounded_text(
        reason, field="withdrawal_reason", max_chars=MAX_NOTE_CHARS
    )
    with _contribution_lock(safe_slug):
        ledger = _load_private_ledger(safe_slug)
        records = _records(ledger)
        index, current = _find_record(records, contribution_id)
        _verify_manage_token(current, manage_token)
        now = _utc_now_iso()
        updated = dict(current)
        updated.update(
            {
                "status": "withdrawn",
                "visibility": "private",
                "updated_at": now,
                "withdrawn_at": now,
                "withdrawal_reason": withdrawal_reason,
                "public_memory": {},
            }
        )
        records[index] = updated
        ledger["contributions"] = records
        # Withdrawal is fail-closed: remove the public projection before recording completion privately.
        _write_public_projection(safe_slug, records)
        _save_private_ledger(safe_slug, ledger)
    return _private_operator_projection(updated)


def load_public_family_memory_cards(*, slug: str) -> list[dict[str, object]]:
    try:
        safe_slug = _safe_slug(slug)
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
        if (
            not isinstance(raw, dict)
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
