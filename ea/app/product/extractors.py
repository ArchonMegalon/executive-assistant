from __future__ import annotations

from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
import re

from app.product.models import CommitmentCandidate


_PROMISE_PATTERNS = (
    re.compile(r"\b(?:i will|i'll|we will|we'll|please|need to|must)\s+([a-z0-9 ,.'/:-]{4,120})", re.IGNORECASE),
    re.compile(r"\b(?:send|share|reply|confirm|schedule|reschedule|review|approve|prepare)\s+([a-z0-9 ,.'/:-]{3,120})", re.IGNORECASE),
)
_WEEKDAY_NAMES = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
_DAYPART_HOURS = {
    "morning": 9,
    "afternoon": 15,
    "evening": 18,
}
_CLOCK_PATTERN_TEXT = r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)"
_WEEKDAY_PATTERN = re.compile(
    r"\b(?:(next)\s+)?("
    + "|".join(_WEEKDAY_NAMES)
    + r")(?:\s+(morning|afternoon|evening)|\s+(?:at\s+)?"
    + _CLOCK_PATTERN_TEXT
    + r")?\b",
    re.IGNORECASE,
)
_TOMORROW_CLOCK_PATTERN = re.compile(r"\btomorrow\s+(?:at\s+)?" + _CLOCK_PATTERN_TEXT + r"\b", re.IGNORECASE)
_TODAY_CLOCK_PATTERN = re.compile(r"\b(?:today|later today)\s+(?:at\s+)?" + _CLOCK_PATTERN_TEXT + r"\b", re.IGNORECASE)
_TEMPORAL_SUFFIX = re.compile(
    r"(?:\b(?:today(?:\s+(?:at\s+)?" + _CLOCK_PATTERN_TEXT + r")?|later today(?:\s+(?:at\s+)?" + _CLOCK_PATTERN_TEXT + r")?|tomorrow(?: morning| afternoon| evening|\s+(?:at\s+)?" + _CLOCK_PATTERN_TEXT + r")?|tonight|this afternoon|this evening|this week|next week|before lunch|before dinner|by eod|by end of day|by cob|cob|close of business|by close of business|eow|end of week|by end of week|by end of this week|(?:next\s+)?(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)(?: morning| afternoon| evening|\s+(?:at\s+)?" + _CLOCK_PATTERN_TEXT + r")?|by (?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)(?: morning| afternoon| evening|\s+(?:at\s+)?" + _CLOCK_PATTERN_TEXT + r")?)\b)$",
    re.IGNORECASE,
)


def _parse_reference_datetime(value: str | None) -> datetime:
    normalized = str(value or "").strip()
    if normalized:
        for parser in (
            lambda raw: datetime.fromisoformat(raw.replace("Z", "+00:00")),
            parsedate_to_datetime,
        ):
            try:
                parsed = parser(normalized)
                if parsed.tzinfo is None:
                    return parsed.replace(tzinfo=timezone.utc)
                return parsed
            except Exception:
                continue
    return datetime.now(timezone.utc)


def _with_local_clock(base: datetime, *, hour: int, minute: int = 0) -> str:
    local_value = base.astimezone(base.tzinfo or timezone.utc).replace(hour=hour, minute=minute, second=0, microsecond=0)
    return local_value.isoformat()


def _clock_hour(hour_text: str, meridiem: str) -> int:
    normalized_hour = max(min(int(hour_text), 12), 1)
    normalized_meridiem = str(meridiem or "").strip().lower()
    if normalized_meridiem == "am":
        return 0 if normalized_hour == 12 else normalized_hour
    return 12 if normalized_hour == 12 else normalized_hour + 12


def _weekday_due_at(
    local_base: datetime,
    *,
    weekday_name: str,
    has_next_prefix: bool,
    daypart: str = "",
    explicit_hour: str = "",
    explicit_minute: str = "",
    meridiem: str = "",
) -> str:
    target_weekday = _WEEKDAY_NAMES.index(str(weekday_name or "").strip().lower())
    delta_days = (target_weekday - local_base.weekday()) % 7
    if delta_days == 0 and has_next_prefix:
        delta_days = 7
    if explicit_hour and meridiem:
        return _with_local_clock(
            local_base + timedelta(days=delta_days),
            hour=_clock_hour(explicit_hour, meridiem),
            minute=int(explicit_minute or 0),
        )
    hour = _DAYPART_HOURS.get(str(daypart or "").strip().lower(), 17)
    return _with_local_clock(local_base + timedelta(days=delta_days), hour=hour)


def _infer_relative_due_at(text: str, *, reference_at: str | None) -> str | None:
    normalized = " ".join(str(text or "").lower().split())
    if not normalized:
        return None
    base = _parse_reference_datetime(reference_at)
    local_base = base.astimezone(base.tzinfo or timezone.utc)
    weekday_match = _WEEKDAY_PATTERN.search(normalized)
    if weekday_match is not None:
        return _weekday_due_at(
            local_base,
            weekday_name=str(weekday_match.group(2) or ""),
            has_next_prefix=bool(weekday_match.group(1)),
            daypart=str(weekday_match.group(3) or ""),
            explicit_hour=str(weekday_match.group(4) or ""),
            explicit_minute=str(weekday_match.group(5) or ""),
            meridiem=str(weekday_match.group(6) or ""),
        )
    tomorrow_clock_match = _TOMORROW_CLOCK_PATTERN.search(normalized)
    if tomorrow_clock_match is not None:
        return _with_local_clock(
            local_base + timedelta(days=1),
            hour=_clock_hour(str(tomorrow_clock_match.group(1) or ""), str(tomorrow_clock_match.group(3) or "")),
            minute=int(str(tomorrow_clock_match.group(2) or 0)),
        )
    today_clock_match = _TODAY_CLOCK_PATTERN.search(normalized)
    if today_clock_match is not None:
        return _with_local_clock(
            local_base,
            hour=_clock_hour(str(today_clock_match.group(1) or ""), str(today_clock_match.group(3) or "")),
            minute=int(str(today_clock_match.group(2) or 0)),
        )
    if "tomorrow morning" in normalized:
        return _with_local_clock(local_base + timedelta(days=1), hour=9)
    if "tomorrow afternoon" in normalized:
        return _with_local_clock(local_base + timedelta(days=1), hour=15)
    if "tomorrow evening" in normalized or "tonight" in normalized:
        return _with_local_clock(local_base + timedelta(days=1 if "tomorrow evening" in normalized else 0), hour=18)
    if "tomorrow" in normalized:
        return _with_local_clock(local_base + timedelta(days=1), hour=17)
    if "before lunch" in normalized:
        return _with_local_clock(local_base, hour=12)
    if "this afternoon" in normalized:
        return _with_local_clock(local_base, hour=15)
    if "this evening" in normalized or "before dinner" in normalized:
        return _with_local_clock(local_base, hour=18)
    if any(token in normalized for token in ("by eod", "by end of day", "by cob", "cob", "close of business", "today")):
        return _with_local_clock(local_base, hour=17)
    if any(token in normalized for token in ("this week", "end of week", "by end of week", "by end of this week", "eow")):
        target = local_base + timedelta(days=max(4 - local_base.weekday(), 0))
        return _with_local_clock(target, hour=17)
    if "next week" in normalized:
        days_until_next_monday = (7 - local_base.weekday()) or 7
        target = local_base + timedelta(days=days_until_next_monday)
        return _with_local_clock(target, hour=9)
    return None


def _split_candidate_chunks(value: str) -> tuple[str, ...]:
    raw = [segment.strip(" .,:;") for segment in re.split(r"\b(?:and|then)\b|[;]+", value) if segment.strip(" .,:;")]
    rows: list[str] = []
    for item in raw:
        cleaned = _TEMPORAL_SUFFIX.sub("", item).strip(" .,:;")
        if len(cleaned) >= 4:
            rows.append(cleaned)
    return tuple(rows)


def extract_commitment_candidates(
    text: str,
    *,
    counterparty: str = "",
    due_at: str | None = None,
    reference_at: str | None = None,
) -> tuple[CommitmentCandidate, ...]:
    normalized = " ".join(str(text or "").split()).strip()
    if not normalized:
        return ()
    inferred_due_at = str(due_at or "").strip() or _infer_relative_due_at(normalized, reference_at=reference_at)
    seen: set[str] = set()
    rows: list[CommitmentCandidate] = []
    for pattern in _PROMISE_PATTERNS:
        for match in pattern.finditer(normalized):
            for candidate_text in _split_candidate_chunks(str(match.group(1) or "").strip(" .,:;")):
                title = candidate_text[:1].upper() + candidate_text[1:]
                key = title.lower()
                if key in seen:
                    continue
                seen.add(key)
                rows.append(
                    CommitmentCandidate(
                        candidate_id="",
                        title=title,
                        details=f"Extracted from source text: {normalized[:180]}",
                        source_text=normalized,
                        confidence=0.82 if pattern is _PROMISE_PATTERNS[0] else 0.68,
                        suggested_due_at=inferred_due_at or None,
                        counterparty=counterparty,
                        status="pending",
                    )
                )
    if rows:
        return tuple(rows[:5])
    return (
        CommitmentCandidate(
            candidate_id="",
            title=normalized[:80],
            details=f"Candidate extracted from source text: {normalized[:180]}",
            source_text=normalized,
            confidence=0.35,
            suggested_due_at=inferred_due_at or None,
            counterparty=counterparty,
            status="pending",
        ),
    )
