from __future__ import annotations

import pathlib
import py_compile

ROOT = pathlib.Path(__file__).resolve().parents[1]
TARGET_DIRS = (ROOT / "ea" / "app", ROOT / "tests")


def _pass(name: str) -> None:
    print(f"[SMOKE][HOST][PASS] {name}")


def test_python_tree_compiles() -> None:
    count = 0
    for base in TARGET_DIRS:
        if not base.exists():
            continue
        for py_path in base.rglob("*.py"):
            if "__pycache__" in py_path.parts:
                continue
            py_compile.compile(str(py_path), doraise=True)
            count += 1
    assert count > 0
    _pass(f"python compile tree ({count} files)")


if __name__ == "__main__":
    test_python_tree_compiles()
