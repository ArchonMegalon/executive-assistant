from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import tempfile
import time
from typing import Any, Iterator, Mapping
from uuid import uuid4

try:
    import fcntl
except Exception:  # pragma: no cover - non-POSIX fallback
    fcntl = None


_AUTH_KINDS = frozenset(
    {
        "ea_registration_verification",
        "ea_workspace_access_session",
        "ea_workspace_invitation",
        "ea_google_connect_link",
    }
)
_PROACTIVE_KINDS = frozenset(
    {
        "ea_channel_digest_delivery",
        "ea_plaintext_digest_delivery",
        "ea_property_market_ready_delivery",
        "ea_property_match_delivery",
        "ea_property_search_results_ready_delivery",
        "ea_property_tour_delivery",
    }
)


@dataclass(frozen=True)
class OutboundEmailPolicy:
    category: str
    cooldown_seconds: int
    window_seconds: int
    max_per_window: int


class OutboundEmailRateLimitedError(RuntimeError):
    def __init__(
        self,
        *,
        retry_after_seconds: int,
        reason: str,
        detail: str = "",
    ) -> None:
        self.retry_after_seconds = max(int(retry_after_seconds or 0), 0)
        self.reason = str(reason or "").strip() or "rate_limited"
        self.detail = str(detail or "").strip()
        super().__init__(f"outbound_email_rate_limited:{self.reason}:retry_after={self.retry_after_seconds}")


def _env_bool(name: str, default: bool) -> bool:
    raw = str(os.environ.get(name) or "").strip().lower()
    if not raw:
        return default
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    return default


def _env_int(name: str, default: int) -> int:
    raw = str(os.environ.get(name) or "").strip()
    try:
        return int(raw) if raw else default
    except Exception:
        return default


def outbound_email_bounds_enabled() -> bool:
    return _env_bool("EA_OUTBOUND_EMAIL_BOUNDS_ENABLED", True)


def _guard_max_keys() -> int:
    return max(1, _env_int("EA_OUTBOUND_EMAIL_GUARD_MAX_KEYS", 2048))


def _failed_attempt_cooldown_seconds(policy: OutboundEmailPolicy) -> int:
    configured = max(1, _env_int("EA_OUTBOUND_EMAIL_FAILURE_COOLDOWN_SECONDS", 60))
    return min(configured, policy.cooldown_seconds)


def _attempt_cooldown_seconds(
    attempt: Mapping[str, object],
    *,
    policy: OutboundEmailPolicy,
) -> int:
    status = str(attempt.get("status") or "").strip().lower()
    if status == "failed":
        try:
            provider_retry_after = max(int(attempt.get("retry_after_seconds") or 0), 0)
        except (TypeError, ValueError):
            provider_retry_after = 0
        return min(
            policy.window_seconds,
            max(_failed_attempt_cooldown_seconds(policy), provider_retry_after),
        )
    return policy.cooldown_seconds


def outbound_email_policy(kind: str) -> OutboundEmailPolicy:
    normalized = str(kind or "").strip().lower()
    if normalized in _AUTH_KINDS:
        return OutboundEmailPolicy(
            category="auth",
            cooldown_seconds=max(1, _env_int("EA_OUTBOUND_EMAIL_AUTH_COOLDOWN_SECONDS", 600)),
            window_seconds=max(60, _env_int("EA_OUTBOUND_EMAIL_AUTH_WINDOW_SECONDS", 86400)),
            max_per_window=max(1, _env_int("EA_OUTBOUND_EMAIL_AUTH_MAX_PER_WINDOW", 6)),
        )
    if normalized in _PROACTIVE_KINDS:
        return OutboundEmailPolicy(
            category="proactive",
            cooldown_seconds=max(1, _env_int("EA_OUTBOUND_EMAIL_PROACTIVE_COOLDOWN_SECONDS", 1800)),
            window_seconds=max(60, _env_int("EA_OUTBOUND_EMAIL_PROACTIVE_WINDOW_SECONDS", 86400)),
            max_per_window=max(1, _env_int("EA_OUTBOUND_EMAIL_PROACTIVE_MAX_PER_WINDOW", 4)),
        )
    return OutboundEmailPolicy(
        category="generic",
        cooldown_seconds=max(1, _env_int("EA_OUTBOUND_EMAIL_GENERIC_COOLDOWN_SECONDS", 600)),
        window_seconds=max(60, _env_int("EA_OUTBOUND_EMAIL_GENERIC_WINDOW_SECONDS", 86400)),
        max_per_window=max(1, _env_int("EA_OUTBOUND_EMAIL_GENERIC_MAX_PER_WINDOW", 6)),
    )


def outbound_email_guard_state_path() -> Path:
    configured = str(os.environ.get("EA_OUTBOUND_EMAIL_GUARD_STATE_PATH") or "").strip()
    if configured:
        return Path(configured).expanduser()
    preferred_roots = (
        Path("/var/lib/ea"),
        Path(tempfile.gettempdir()),
        Path.cwd() / ".runtime",
    )
    for root in preferred_roots:
        try:
            root.mkdir(parents=True, exist_ok=True)
        except Exception:
            continue
        return root / "outbound_email_guard.json"
    return Path(tempfile.gettempdir()) / "ea_outbound_email_guard.json"


def _kind_from_entry_key(entry_key: str) -> str:
    return str(str(entry_key or "").split("|", 1)[0] or "").strip().lower()


def _attempt_timestamp(value: Mapping[str, object] | None) -> float:
    row = dict(value or {})
    for key in ("completed_at", "attempted_at"):
        try:
            timestamp = float(row.get(key) or 0.0)
        except Exception:
            timestamp = 0.0
        if timestamp > 0.0:
            return timestamp
    return 0.0


def _entry_last_activity(attempts: list[dict[str, object]]) -> float:
    return max((_attempt_timestamp(item) for item in attempts if isinstance(item, dict)), default=0.0)


def _prune_entries(entries: object, *, now: float) -> dict[str, list[dict[str, object]]]:
    if not isinstance(entries, dict):
        return {}
    normalized: dict[str, list[dict[str, object]]] = {}
    for raw_key, raw_attempts in entries.items():
        entry_key = str(raw_key or "").strip()
        kind = _kind_from_entry_key(entry_key)
        if not entry_key or not kind:
            continue
        attempts = raw_attempts if isinstance(raw_attempts, list) else []
        policy = outbound_email_policy(kind)
        kept = _prune_attempts(attempts, now=now, window_seconds=policy.window_seconds)
        retained = [dict(item) for item in kept if isinstance(item, dict)]
        if not retained:
            continue
        normalized[entry_key] = retained[-max(policy.max_per_window * 2, 16) :]
    max_keys = _guard_max_keys()
    if len(normalized) <= max_keys:
        return normalized
    ranked = sorted(
        normalized.items(),
        key=lambda item: (_entry_last_activity(item[1]), item[0]),
    )
    kept_items = ranked[-max_keys:]
    return {key: value for key, value in kept_items}


def _prune_state_payload(payload: dict[str, object], *, now: float | None = None) -> None:
    effective_now = float(now if now is not None else time.time())
    payload.setdefault("version", 1)
    payload["entries"] = _prune_entries(payload.get("entries"), now=effective_now)


def _iso8601_utc(timestamp: float) -> str:
    if timestamp <= 0.0:
        return ""
    return (
        datetime.fromtimestamp(timestamp, tz=timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


@contextmanager
def _locked_state(path: Path) -> Iterator[dict[str, object]]:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+", encoding="utf-8") as handle:
        if fcntl is not None:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            handle.seek(0)
            raw = handle.read().strip()
            payload = json.loads(raw) if raw else {}
            if not isinstance(payload, dict):
                payload = {}
            payload.setdefault("version", 1)
            payload.setdefault("entries", {})
            _prune_state_payload(payload)
            yield payload
            _prune_state_payload(payload)
            handle.seek(0)
            handle.truncate(0)
            json.dump(payload, handle, sort_keys=True, separators=(",", ":"))
            handle.flush()
            os.fsync(handle.fileno())
        finally:
            if fcntl is not None:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _entry_key(kind: str, recipient_email: str) -> str:
    return f"{str(kind or '').strip().lower()}|{str(recipient_email or '').strip().lower()}"


def _prune_attempts(
    attempts: list[dict[str, object]],
    *,
    now: float,
    window_seconds: int,
) -> list[dict[str, object]]:
    lower_bound = now - max(int(window_seconds or 0), 0)
    return [
        item
        for item in attempts
        if isinstance(item, dict) and float(item.get("attempted_at") or 0.0) >= lower_bound
    ]


def _reserve_attempt(
    *,
    kind: str,
    recipient_email: str,
    subject: str,
    provider: str,
) -> dict[str, object]:
    if not outbound_email_bounds_enabled():
        return {}
    normalized_kind = str(kind or "").strip().lower()
    normalized_email = str(recipient_email or "").strip().lower()
    if not normalized_kind or not normalized_email:
        return {}
    policy = outbound_email_policy(normalized_kind)
    now = time.time()
    state_path = outbound_email_guard_state_path()
    entry_key = _entry_key(normalized_kind, normalized_email)
    attempt_id = uuid4().hex[:16]
    with _locked_state(state_path) as payload:
        entries = payload.setdefault("entries", {})
        if not isinstance(entries, dict):
            entries = {}
            payload["entries"] = entries
        raw_attempts = entries.get(entry_key)
        attempts = raw_attempts if isinstance(raw_attempts, list) else []
        attempts = _prune_attempts(attempts, now=now, window_seconds=policy.window_seconds)
        recent_attempt = attempts[-1] if attempts else None
        if recent_attempt is not None:
            cooldown_seconds = _attempt_cooldown_seconds(recent_attempt, policy=policy)
            retry_after = int(
                max(
                    float(recent_attempt.get("attempted_at") or 0.0) + float(cooldown_seconds) - now,
                    0.0,
                )
            )
            if retry_after > 0:
                raise OutboundEmailRateLimitedError(
                    retry_after_seconds=retry_after,
                    reason="cooldown",
                    detail=(
                        f"kind={normalized_kind} category={policy.category} recipient={normalized_email} "
                        f"cooldown_seconds={cooldown_seconds}"
                    ),
                )
        if len(attempts) >= policy.max_per_window:
            retry_after = int(
                max(
                    float(attempts[0].get("attempted_at") or 0.0) + float(policy.window_seconds) - now,
                    1.0,
                )
            )
            raise OutboundEmailRateLimitedError(
                retry_after_seconds=retry_after,
                reason="window_budget",
                detail=(
                    f"kind={normalized_kind} category={policy.category} recipient={normalized_email} "
                    f"window_seconds={policy.window_seconds} max_per_window={policy.max_per_window}"
                ),
            )
        attempts.append(
            {
                "attempt_id": attempt_id,
                "attempted_at": now,
                "status": "started",
                "kind": normalized_kind,
                "recipient_email": normalized_email,
                "subject": str(subject or "").strip()[:240],
                "provider": str(provider or "").strip()[:80],
            }
        )
        entries[entry_key] = attempts[-max(policy.max_per_window * 2, 16) :]
    return {
        "attempt_id": attempt_id,
        "entry_key": entry_key,
        "state_path": str(state_path),
    }


def _finish_attempt(
    context: dict[str, object],
    *,
    status: str,
    error: str = "",
    retry_after_seconds: int = 0,
) -> None:
    if not context:
        return
    attempt_id = str(context.get("attempt_id") or "").strip()
    entry_key = str(context.get("entry_key") or "").strip()
    state_path_text = str(context.get("state_path") or "").strip()
    if not attempt_id or not entry_key or not state_path_text:
        return
    state_path = Path(state_path_text)
    with _locked_state(state_path) as payload:
        entries = payload.setdefault("entries", {})
        if not isinstance(entries, dict):
            return
        raw_attempts = entries.get(entry_key)
        if not isinstance(raw_attempts, list):
            return
        for item in reversed(raw_attempts):
            if not isinstance(item, dict):
                continue
            if str(item.get("attempt_id") or "").strip() != attempt_id:
                continue
            item["status"] = str(status or "").strip() or "sent"
            item["completed_at"] = time.time()
            if error:
                item["error"] = str(error or "").strip()[:240]
            if retry_after_seconds > 0:
                item["retry_after_seconds"] = int(retry_after_seconds)
            break


def outbound_email_guard_summary(
    *,
    state_path: Path | None = None,
    now: float | None = None,
) -> dict[str, Any]:
    enabled = outbound_email_bounds_enabled()
    path = state_path or outbound_email_guard_state_path()
    effective_now = float(now if now is not None else time.time())
    try:
        with _locked_state(path) as payload:
            entries = dict(payload.get("entries") or {})
    except Exception as exc:
        return {
            "enabled": enabled,
            "status": "guard_unavailable",
            "state_path": str(path),
            "entry_count": 0,
            "attempt_count": 0,
            "active_cooldown_count": 0,
            "active_window_budget_count": 0,
            "most_recent_attempt_at": "",
            "categories": {},
            "guard_file_bytes": 0,
            "guard_error": type(exc).__name__,
            "privacy": {
                "raw_recipient_exposed": False,
                "raw_subject_exposed": False,
            },
        }

    categories: dict[str, dict[str, Any]] = {}
    attempt_count = 0
    active_cooldown_count = 0
    active_window_budget_count = 0
    most_recent_attempt = 0.0

    for entry_key, attempts in entries.items():
        normalized_attempts = attempts if isinstance(attempts, list) else []
        if not normalized_attempts:
            continue
        kind = _kind_from_entry_key(entry_key)
        policy = outbound_email_policy(kind)
        category = policy.category
        latest_attempt = _entry_last_activity(normalized_attempts)
        most_recent_attempt = max(most_recent_attempt, latest_attempt)
        attempt_count += len(normalized_attempts)

        category_row = categories.setdefault(
            category,
            {
                "entry_count": 0,
                "attempt_count": 0,
                "active_cooldown_count": 0,
                "active_window_budget_count": 0,
                "most_recent_attempt_at": "",
            },
        )
        category_row["entry_count"] += 1
        category_row["attempt_count"] += len(normalized_attempts)

        latest_attempt_row = normalized_attempts[-1]
        cooldown_seconds = _attempt_cooldown_seconds(latest_attempt_row, policy=policy)
        cooldown_active = bool(latest_attempt > 0.0 and latest_attempt + float(cooldown_seconds) > effective_now)
        if cooldown_active:
            active_cooldown_count += 1
            category_row["active_cooldown_count"] += 1

        at_window_budget = len(normalized_attempts) >= policy.max_per_window
        if at_window_budget:
            active_window_budget_count += 1
            category_row["active_window_budget_count"] += 1

        if latest_attempt > 0.0:
            category_row["most_recent_attempt_at"] = _iso8601_utc(latest_attempt)

    if not enabled:
        status = "disabled"
    elif active_cooldown_count > 0 or active_window_budget_count > 0:
        status = "bounded"
    else:
        status = "clear"

    try:
        guard_file_bytes = int(path.stat().st_size)
    except OSError:
        guard_file_bytes = 0

    return {
        "enabled": enabled,
        "status": status,
        "state_path": str(path),
        "entry_count": len(entries),
        "attempt_count": attempt_count,
        "active_cooldown_count": active_cooldown_count,
        "active_window_budget_count": active_window_budget_count,
        "most_recent_attempt_at": _iso8601_utc(most_recent_attempt),
        "categories": categories,
        "guard_file_bytes": guard_file_bytes,
        "guard_error": "",
        "privacy": {
            "raw_recipient_exposed": False,
            "raw_subject_exposed": False,
        },
    }


@contextmanager
def bounded_outbound_email(
    *,
    kind: str,
    recipient_email: str,
    subject: str = "",
    provider: str = "",
) -> Iterator[None]:
    context = _reserve_attempt(
        kind=kind,
        recipient_email=recipient_email,
        subject=subject,
        provider=provider,
    )
    try:
        yield
    except Exception as exc:
        try:
            retry_after_seconds = max(int(getattr(exc, "retry_after_seconds", 0) or 0), 0)
        except (TypeError, ValueError):
            retry_after_seconds = 0
        _finish_attempt(
            context,
            status="failed",
            error=str(exc),
            retry_after_seconds=retry_after_seconds,
        )
        raise
    else:
        _finish_attempt(context, status="sent")
