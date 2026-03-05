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


def test_step_executor_ledger_module_wiring() -> None:
    step_src = (ROOT / "ea/app/planner/step_executor.py").read_text(encoding="utf-8")
    runtime_src = (ROOT / "ea/app/intent_runtime.py").read_text(encoding="utf-8")
    assert "def list_queued_pre_execution_steps(" in step_src
    assert "def run_pre_execution_steps_from_ledger(" in step_src
    assert "run_pre_execution_steps_from_ledger(" in runtime_src
    _pass("v1.22 step-executor ledger module wiring")


def test_step_executor_ledger_selection_behavior() -> None:
    from app.planner.step_executor import list_queued_pre_execution_steps, run_pre_execution_steps_from_ledger

    def _fetch_steps(_session_id: str):
        return [
            {"step_order": 1, "step_key": "compile_intent", "step_kind": "compile", "preconditions_json": {}, "evidence_json": {}},
            {"step_order": 2, "step_key": "gather_project_context", "step_kind": "context", "preconditions_json": {}, "evidence_json": {}},
            {"step_order": 3, "step_key": "execute_intent", "preconditions_json": {}, "evidence_json": {}},
            {"step_order": 4, "step_key": "prepare_route_render_context", "step_kind": "context", "preconditions_json": {}, "evidence_json": {}},
        ]

    selected = list_queued_pre_execution_steps(session_id="sess-1", fetch_steps=_fetch_steps)
    keys = [str(row.get("step_key") or "") for row in selected]
    assert keys == ["compile_intent", "gather_project_context", "prepare_route_render_context"]

    calls: list[tuple[str, str, dict[str, object]]] = []
    events: list[str] = []

    def _mark_step(session_id: str, step_key: str, status: str, **kwargs) -> None:
        calls.append((str(step_key), str(status), dict(kwargs or {})))

    def _append_event(session_id: str, **kwargs) -> None:
        events.append(str(kwargs.get("event_type") or ""))

    executed = run_pre_execution_steps_from_ledger(
        session_id="sess-1",
        intent_spec={"domain": "project", "task_type": "strategy_pack", "objective": "Prepare project strategy memo"},
        mark_step=_mark_step,
        append_event=_append_event,
        fetch_steps=_fetch_steps,
    )
    assert executed == 3
    ordered = [(row[0], row[1]) for row in calls]
    assert ordered == [
        ("compile_intent", "running"),
        ("compile_intent", "completed"),
        ("gather_project_context", "running"),
        ("gather_project_context", "completed"),
        ("prepare_route_render_context", "running"),
        ("prepare_route_render_context", "completed"),
    ]
    completed_rows = [row for row in calls if row[1] == "completed"]
    assert completed_rows
    for row in completed_rows:
        kwargs = dict(row[2] or {})
        assert str(kwargs.get("provider_key") or "") == "deterministic_planner"
        output_refs = list(kwargs.get("output_refs") or [])
        assert output_refs and str(output_refs[0]).startswith("planner_context:")
    assert events.count("planner_context_step_completed") == 3
    _pass("v1.22 step-executor ledger selection behavior")


if __name__ == "__main__":
    test_step_executor_ledger_module_wiring()
    test_step_executor_ledger_selection_behavior()
