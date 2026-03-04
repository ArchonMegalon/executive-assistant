from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "ea"))

from app.newspaper.validate import validate_issue  # noqa: E402
from app.newspaper.render import render_issue_html  # noqa: E402


def _fake_story(i: int) -> dict:
    return {
        "id": f"s-{i}",
        "section": "must_know",
        "layout_role": "cover_lead" if i == 1 else "feature",
        "headline": f"Headline {i}",
        "dek": f"Dek {i}",
        "summary": "word " * 100,
        "why_it_matters": "Today this matters.",
        "source_label": "Source",
        "source_url": "https://example.com",
        "published_at": "2026-03-03T08:00:00Z",
        "image": {"kind": "hero", "url": "data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg'/>", "caption": "c"},
        "pull_quote": "",
        "facts": [],
    }


def main() -> int:
    issue = {
        "issue_id": "i1",
        "title": "Tibor Daily",
        "issue_date": "2026-03-03",
        "edition_no": 42,
        "timezone": "Europe/Vienna",
        "preferences": {"prioritize": ["ai"], "avoid": ["promo"]},
        "sections": {
            "must_know": [_fake_story(1), _fake_story(2), _fake_story(3)],
            "worth_knowing": [_fake_story(4), _fake_story(5)],
            "agenda": [{"time": "08:30", "title": "Physio", "location": ""}],
            "watchlist": [_fake_story(6)],
            "signals": ["router active"],
        },
        "footer_note": "x",
    }
    errs = validate_issue(issue)
    assert not errs, f"validation failed: {errs}"
    html = render_issue_html(issue)
    assert "Tibor Daily" in html
    assert "page-break" in html
    assert "Interesting" not in html  # old renderer path should be retired in new template.
    print("PASS: newspaper issue pipeline smoke")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
