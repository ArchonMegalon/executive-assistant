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


def test_step_executor_module_and_intent_runtime_wiring() -> None:
    step_src = (ROOT / "ea/app/planner/step_executor.py").read_text(encoding="utf-8")
    runtime_src = (ROOT / "ea/app/intent_runtime.py").read_text(encoding="utf-8")
    assert "def run_reasoning_step(" in step_src
    assert "def run_pre_execution_steps(" in step_src
    assert "def execute_planned_reasoning_step(" in step_src
    assert "from app.planner.step_executor import (" in runtime_src
    assert "execute_planned_reasoning_step(" in runtime_src
    assert "reasoning_runner=gog_scout" in runtime_src
    _pass("v1.21 step executor module + runtime wiring")


def test_step_executor_runner_behavior() -> None:
    from app.planner.step_executor import run_reasoning_step

    captured: dict[str, str] = {}

    async def _fake_runner(container, prompt, google_account, ui_updater, task_name=""):
        captured["container"] = str(container)
        captured["prompt"] = str(prompt)
        captured["account"] = str(google_account)
        captured["task_name"] = str(task_name)
        await ui_updater("running")
        return "ok:done"

    async def _fake_ui(msg: str) -> None:
        captured["ui"] = str(msg)

    async def _run() -> str:
        return await run_reasoning_step(
            container="openclaw-gateway",
            prompt="EXECUTE",
            google_account="user@example.com",
            ui_updater=_fake_ui,
            task_name="Intent Test",
            timeout_sec=2.0,
            runner=_fake_runner,
        )

    out = asyncio.run(_run())
    assert out == "ok:done"
    assert captured.get("container") == "openclaw-gateway"
    assert captured.get("task_name") == "Intent Test"
    assert captured.get("ui") == "running"
    _pass("v1.21 step executor behavior")


if __name__ == "__main__":
    test_step_executor_module_and_intent_runtime_wiring()
    test_step_executor_runner_behavior()
