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


def test_planner_runtime_contract_wiring() -> None:
    runtime_src = (ROOT / "ea/app/intent_runtime.py").read_text(encoding="utf-8")
    step_src = (ROOT / "ea/app/planner/step_executor.py").read_text(encoding="utf-8")

    assert "run_pre_execution_steps_from_ledger(" in runtime_src
    assert "executed = run_pre_execution_steps_from_ledger(" in runtime_src
    assert "if executed > 0:" in runtime_src
    assert "resolve_execute_step_metadata" in step_src
    assert "_execute_step_metadata(session_id=session_id" in step_src
    _pass("v1.22 planner runtime contract wiring")


if __name__ == "__main__":
    test_planner_runtime_contract_wiring()
