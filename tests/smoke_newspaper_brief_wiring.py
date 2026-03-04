from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
POLL = ROOT / "ea/app/poll_listener.py"


def main() -> int:
    src = POLL.read_text(encoding="utf-8")
    assert "build_issue_for_brief" in src, "newspaper pipeline not wired"
    assert "render_issue_html" in src, "newspaper renderer not wired"
    assert "validate_issue" in src, "issue validator not wired"
    assert "safe_task('Articles PDF'" not in src, "legacy extra articles PDF still wired in /brief flow"
    print("PASS: newspaper /brief wiring smoke")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
