from __future__ import annotations

from .intent_compiler import compile_intent_spec_v2
from .plan_builder import build_task_plan_steps
from .provider_registry import list_provider_contracts, provider_or_raise, providers_for_task
from .provider_broker import rank_task_capabilities
from .step_executor import run_reasoning_step
from .task_registry import TaskContract, list_task_contracts, task_or_none, task_or_raise

__all__ = [
    "ProactivePlanner",
    "TaskContract",
    "compile_intent_spec_v2",
    "build_task_plan_steps",
    "run_reasoning_step",
    "list_provider_contracts",
    "provider_or_raise",
    "providers_for_task",
    "rank_task_capabilities",
    "task_or_none",
    "task_or_raise",
    "list_task_contracts",
]


def __getattr__(name: str):
    if name == "ProactivePlanner":
        from .proactive import ProactivePlanner

        return ProactivePlanner
    raise AttributeError(f"module 'app.planner' has no attribute {name!r}")
