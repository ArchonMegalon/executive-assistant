from __future__ import annotations

import asyncio
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
EA_DIR = ROOT / "ea"
for path in (str(ROOT), str(EA_DIR)):
    if path not in sys.path:
        sys.path.insert(0, path)


def _pass(name: str) -> None:
    print(f"[SMOKE][HOST][PASS] {name}")


def test_planner_execute_records_provider_outcome() -> None:
    import app.planner.step_executor as se

    calls: list[dict[str, object]] = []
    original_record = se.record_provider_outcome
    try:
        se.record_provider_outcome = lambda **kwargs: calls.append(dict(kwargs or {}))

        async def _fake_reasoning(**kwargs) -> str:
            return "ok-report"

        async def _ui(_msg: str) -> None:
            return None

        marks: list[tuple[str, str, dict[str, object]]] = []
        events: list[dict[str, object]] = []

        result = asyncio.run(
            se.execute_planned_reasoning_step(
                session_id="sess-outcome-1",
                plan_steps=[
                    {
                        "step_key": "execute_intent",
                        "task_type": "trip_context_pack",
                        "provider_candidates": ["avomap"],
                        "output_artifact_type": "trip_context_pack",
                    }
                ],
                intent_spec={"task_type": "trip_context_pack", "tenant_key": "chat_100284"},
                prompt="EXECUTE",
                container="openclaw",
                google_account="user@example.com",
                ui_updater=_ui,
                task_name="Intent: Free Text",
                mark_step=lambda session_id, step_key, status, **kwargs: marks.append(
                    (str(step_key), str(status), dict(kwargs or {}))
                ),
                append_event=lambda session_id, **kwargs: events.append(dict(kwargs or {})),
                run_reasoning_step_func=_fake_reasoning,
                reasoning_runner=None,
                timeout_sec=2.0,
            )
        )
    finally:
        se.record_provider_outcome = original_record

    assert str(result.get("task_type") or "") == "trip_context_pack"
    assert str(result.get("report") or "") == "ok-report"
    assert calls, "expected provider outcome call"
    row = calls[-1]
    assert str(row.get("provider_key") or "") == "avomap"
    assert str(row.get("task_type") or "") == "trip_context_pack"
    assert str(row.get("outcome_status") or "") == "success"
    assert str(row.get("source") or "") == "planner_execution"
    assert int(row.get("score_delta") if row.get("score_delta") is not None else -999) == 1
    _pass("v1.22 planner execute records provider outcome")


if __name__ == "__main__":
    test_planner_execute_records_provider_outcome()
