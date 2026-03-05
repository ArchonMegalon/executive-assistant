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
    assert "smoke_v1_21_provider_outcomes.py" in guide
    assert "smoke_v1_21_provider_registry.py" in guide
    assert "smoke_v1_21_approval_gate_store.py" in guide
    assert "smoke_v1_21_typed_action_reference_enforcement.py" in guide
    assert "smoke_v1_21_step_executor_path.py" in guide
    assert "smoke_v1_21_intent_runtime_planner_steps.py" in guide
    assert "smoke_v1_21_generic_skill_execution.py" in guide
    assert "smoke_v1_21_plan_builder.py" in guide
    assert "smoke_v1_21_gate_alias.py" in guide
    assert "smoke_v1_22_world_model_seed.py" in guide
    assert "smoke_v1_22_memory_candidates.py" in guide
    assert "smoke_v1_22_memory_promotion_pipeline.py" in guide
    assert "smoke_v1_22_sim_user_harness.py" in guide
    assert "smoke_v1_20_execution_sessions.py" in guide
    assert "smoke_v1_20_slash_command_sessions.py" in guide
    assert "smoke_v1_20_slash_command_behavior.py" in guide
    assert "smoke_python_compile_tree.py" in guide
    assert "approval_class" in guide
    assert "provider_broker.py" in guide
    assert "provider_outcomes.py" in guide
    assert "EA_PROVIDER_HISTORY_SCORE_JSON" in guide
    assert "provider_registry.py" in guide
    assert "runtime_execution_ops" in guide
    assert "capability_router.py" in guide
    assert "intent_compiler.py" in guide
    assert "step_executor.py" in guide
    assert "execute_planned_reasoning_step" in guide
    assert "_run_planner_pre_execution_steps" in guide
    assert "create_action(...)" in guide
    assert "skill_commands.py" in guide
    assert "plan_builder.py" in guide
    assert "poll_listener.py" in guide
    assert "send_budgets" in guide
    assert "smoke_v1_18.py" in guide
    assert "run_v121_smoke.sh" in guide
    assert "approval_gates" in guide
    assert "20260305_v1_21_approval_gates.sql" in guide
    assert "provider_outcomes" in guide
    assert "20260305_v1_21_provider_outcomes.sql" in guide
    assert "world_model.py" in guide
    assert "20260305_v1_22_commitment_runtime_seed.sql" in guide
    assert "memory_candidates.py" in guide
    assert "list_memory_candidates_for_sync" in guide
    assert "20260305_v1_22_memory_candidates.sql" in guide
    assert "session_store.py" in guide
    assert "sync_worker.py" in guide
    assert "ea-sim-user" in guide
    assert "run_sim_user_eval.sh" in guide
    assert "run_v121_smoke.sh" in readme
    _pass("v1.21 doc/code alignment")


if __name__ == "__main__":
    test_v121_doc_alignment()
