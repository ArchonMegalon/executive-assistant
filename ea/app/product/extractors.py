from __future__ import annotations

import re

from app.product.models import CommitmentCandidate


_PROMISE_PATTERNS = (
    re.compile(r"\b(?:i will|i'll|we will|we'll|please|need to|must)\s+([a-z0-9 ,.'/-]{4,120})", re.IGNORECASE),
    re.compile(r"\b(?:send|share|reply|confirm|schedule|reschedule|review|approve|prepare)\s+([a-z0-9 ,.'/-]{3,120})", re.IGNORECASE),
)
_TEMPORAL_SUFFIX = re.compile(
    r"(?:\b(?:today|tomorrow|tonight|this afternoon|this evening|this week|next week|before lunch|before dinner|by eod|by end of day)\b)$",
    re.IGNORECASE,
)


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
) -> tuple[CommitmentCandidate, ...]:
    normalized = " ".join(str(text or "").split()).strip()
    if not normalized:
        return ()
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
                        suggested_due_at=due_at,
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
            suggested_due_at=due_at,
            counterparty=counterparty,
            status="pending",
        ),
    )
