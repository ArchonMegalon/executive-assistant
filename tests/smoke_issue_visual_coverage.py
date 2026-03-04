from __future__ import annotations

import json
import sys
from pathlib import Path


def assert_every_story_has_visual(issue: dict) -> None:
    stories = issue.get("stories") or []
    assert isinstance(stories, list), "issue.stories must be a list"
    for story in stories:
        sid = story.get("id", "<unknown>")
        assert (
            story.get("hero_image_url")
            or story.get("peekshot_image_url")
            or story.get("browseract_screenshot_url")
            or story.get("placeholder_key")
        ), f"No visual fallback for story {sid}"


def main() -> int:
    if len(sys.argv) == 1:
        issue = {
            "stories": [
                {"id": "sample-1", "placeholder_key": "generic_world"},
                {"id": "sample-2", "hero_image_url": "https://example.invalid/hero.jpg"},
            ]
        }
        assert_every_story_has_visual(issue)
        print("PASS: issue visual coverage (self-sample)")
        return 0
    if len(sys.argv) != 2:
        print("Usage: python3 tests/smoke_issue_visual_coverage.py <issue_json_path>")
        return 2

    p = Path(sys.argv[1])
    if not p.exists():
        print(f"FAIL: file not found: {p}")
        return 2
    issue = json.loads(p.read_text(encoding="utf-8"))
    assert_every_story_has_visual(issue)
    print("PASS: issue visual coverage")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
