from __future__ import annotations

from typing import Any


DEBUG_TOKENS = (
    "OODA Diagnostic",
    "MarkupGo API HTTP 400",
    "statusCode",
    "FST_ERR_VALIDATION",
    "Traceback (most recent call last)",
    '"code":',
)


def _len_words(text: str) -> int:
    return len([w for w in (text or "").strip().split() if w])


def validate_issue(issue: dict[str, Any]) -> list[str]:
    errs: list[str] = []
    if not isinstance(issue, dict):
        return ["issue is not a dict"]
    for k in ("issue_id", "title", "issue_date", "sections"):
        if not issue.get(k):
            errs.append(f"missing field: {k}")
    sections = issue.get("sections") or {}
    for req in ("must_know", "worth_knowing", "agenda", "watchlist"):
        if req not in sections:
            errs.append(f"missing section: {req}")

    stories = []
    for sec in ("must_know", "worth_knowing", "watchlist"):
        stories.extend(sections.get(sec) or [])
    if not stories:
        errs.append("no editorial stories")

    has_cover = False
    image_count = 0
    for s in stories:
        if str(s.get("layout_role") or "") == "cover_lead":
            has_cover = True
        img = (s.get("image") or {}).get("url") or ""
        if img:
            image_count += 1
        if not img:
            errs.append(f"story without image: {s.get('headline')}")
        if _len_words(str(s.get("summary") or "")) > 220:
            errs.append(f"summary too long: {s.get('headline')}")
        blob = " ".join(
            [
                str(s.get("headline") or ""),
                str(s.get("dek") or ""),
                str(s.get("summary") or ""),
                str(s.get("why_it_matters") or ""),
            ]
        )
        for token in DEBUG_TOKENS:
            if token in blob:
                errs.append(f"debug token in story: {token}")
                break

    if not has_cover:
        errs.append("missing cover_lead story")
    if image_count < 3:
        errs.append(f"insufficient image count: {image_count}")
    return errs
