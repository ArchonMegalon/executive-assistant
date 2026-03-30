from __future__ import annotations

from datetime import datetime, timezone

TERMINAL_STATUSES = {"done", "closed", "completed", "resolved", "cancelled", "canceled", "dropped", "rejected", "decided", "elapsed", "expired"}
PRIORITY_WEIGHTS = {
    "critical": 100,
    "urgent": 90,
    "high": 80,
    "medium": 60,
    "normal": 50,
    "low": 30,
}


def parse_when(value: str | None) -> datetime | None:
    normalized = str(value or "").strip()
    if not normalized:
        return None
    try:
        return datetime.fromisoformat(normalized.replace("Z", "+00:00"))
    except ValueError:
        return None


def priority_weight(value: str | None) -> int:
    normalized = str(value or "").strip().lower()
    return PRIORITY_WEIGHTS.get(normalized, 40)


def due_bonus(value: str | None) -> int:
    when = parse_when(value)
    if when is None:
        return 0
    delta = when - datetime.now(timezone.utc)
    hours = delta.total_seconds() / 3600
    if hours <= 0:
        return 35
    if hours <= 12:
        return 28
    if hours <= 48:
        return 18
    if hours <= 168:
        return 8
    return 0


def status_open(value: str | None) -> bool:
    normalized = str(value or "").strip().lower()
    if not normalized:
        return True
    return normalized not in TERMINAL_STATUSES


def compact_text(value: str | None, *, fallback: str, limit: int = 160) -> str:
    normalized = " ".join(str(value or "").split()).strip()
    if not normalized:
        return fallback
    if len(normalized) <= limit:
        return normalized
    return f"{normalized[: max(limit - 3, 0)]}..."


def product_commitment_status(value: str | None) -> str:
    normalized = str(value or "").strip().lower()
    if normalized == "cancelled":
        return "dropped"
    return normalized or "open"


def contains_token(text: str | None, token: str) -> bool:
    haystack = str(text or "").strip().lower()
    needle = str(token or "").strip().lower()
    return bool(haystack and needle and needle in haystack)
