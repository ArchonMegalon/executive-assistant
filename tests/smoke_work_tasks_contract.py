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


def test_work_tasks_file_contract() -> None:
    path = ROOT / "WORK_TASKS.md"
    assert path.exists(), "missing WORK_TASKS.md queue file"
    text = path.read_text(encoding="utf-8")
    required_markers = [
        "# EA Work Tasks",
        "## Operating Rule",
        "## Active Queue",
        "Validation Command",
        "PENDING",
    ]
    for marker in required_markers:
        assert marker in text, f"missing marker in WORK_TASKS.md: {marker}"
    _pass("work-task queue file contract")


if __name__ == "__main__":
    test_work_tasks_file_contract()
