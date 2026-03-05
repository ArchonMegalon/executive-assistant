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


def test_pre_step_parity_between_plan_templates_and_step_executor() -> None:
    from app.planner.plan_builder import build_task_plan_steps
    from app.planner.task_registry import TASK_REGISTRY
    from app.planner.step_executor import _PLANNER_PRE_EXEC_STEPS

    non_pre = {"compile_intent", "safety_gate", "execute_intent", "render_reply"}
    template_pre_steps: set[str] = set()

    for task_key in sorted(TASK_REGISTRY.keys()):
        spec = {
            "task_type": task_key,
            "domain": "travel" if "trip" in task_key or "travel" in task_key else "general",
            "autonomy_level": "approval_required" if task_key in {"typed_safe_action", "approval_router"} else "assistive",
            "objective": f"test objective for {task_key}",
            "has_url": False,
        }
        steps = build_task_plan_steps(intent_spec=spec)
        for row in steps:
            step_key = str((row or {}).get("step_key") or "")
            if step_key and step_key not in non_pre:
                template_pre_steps.add(step_key)

    missing = sorted(template_pre_steps - set(_PLANNER_PRE_EXEC_STEPS))
    assert not missing, f"missing_pre_step_keys:{','.join(missing)}"
    _pass("v1.22 pre-step parity between templates and step executor")


if __name__ == "__main__":
    test_pre_step_parity_between_plan_templates_and_step_executor()
