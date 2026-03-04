from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
EA_DIR = ROOT / "ea"
for path in (str(ROOT), str(EA_DIR)):
    if path not in sys.path:
        sys.path.insert(0, path)


def _pass(name: str) -> None:
    print(f"[SMOKE][HOST][PASS] {name}")


def test_backlog_file_contract() -> None:
    p = ROOT / "BACKLOG.md"
    assert p.exists(), "BACKLOG.md missing"
    src = p.read_text(encoding="utf-8")
    assert "# EA Execution Backlog" in src
    assert "## Definition Of Done (DoD)" in src
    assert "## Current Milestone" in src
    assert "## Blocked" in src
    assert "- [DONE]" in src
    _pass("v1.19.4 backlog contract file presence")


if __name__ == "__main__":
    test_backlog_file_contract()
