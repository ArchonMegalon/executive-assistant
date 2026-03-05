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


def test_v121_doc_alignment() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    guide = (ROOT / "docs/EA_OS_Change_Guide_for_Dev_v1_21_Task_Contracts.md").read_text(encoding="utf-8")
    assert "EA_OS_Change_Guide_for_Dev_v1_21_Task_Contracts.md" in readme
    assert "task_registry.py" in guide
    assert "TaskContract" in guide
    assert "smoke_v1_21_task_contract_registry.py" in guide
    assert "smoke_v1_21_intent_spec_v2_shape.py" in guide
    assert "smoke_v1_21_provider_broker.py" in guide
    assert "smoke_v1_21_provider_registry.py" in guide
    assert "smoke_v1_21_approval_gate_store.py" in guide
    assert "smoke_v1_21_step_executor_path.py" in guide
    assert "smoke_v1_21_generic_skill_execution.py" in guide
    assert "smoke_v1_21_plan_builder.py" in guide
    assert "smoke_v1_21_gate_alias.py" in guide
    assert "smoke_python_compile_tree.py" in guide
    assert "approval_class" in guide
    assert "provider_broker.py" in guide
    assert "provider_registry.py" in guide
    assert "runtime_execution_ops" in guide
    assert "capability_router.py" in guide
    assert "intent_compiler.py" in guide
    assert "step_executor.py" in guide
    assert "plan_builder.py" in guide
    assert "poll_listener.py" in guide
    assert "send_budgets" in guide
    assert "smoke_v1_18.py" in guide
    assert "run_v121_smoke.sh" in guide
    assert "approval_gates" in guide
    assert "20260305_v1_21_approval_gates.sql" in guide
    assert "run_v121_smoke.sh" in readme
    _pass("v1.21 doc/code alignment")


if __name__ == "__main__":
    test_v121_doc_alignment()
