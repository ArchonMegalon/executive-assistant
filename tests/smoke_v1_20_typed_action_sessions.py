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


def test_typed_action_execution_session_wiring() -> None:
    src = (ROOT / "ea/app/callback_commands.py").read_text(encoding="utf-8")
    assert "source=\"typed_action_callback\"" in src
    assert "compile_intent_spec(" in src
    assert "build_plan_steps(" in src
    assert "create_execution_session(" in src
    assert "mark_execution_step_status(" in src
    assert "finalize_execution_session(" in src
    _pass("v1.20 typed-action session wiring")


if __name__ == "__main__":
    test_typed_action_execution_session_wiring()
