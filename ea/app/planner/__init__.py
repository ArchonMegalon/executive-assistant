from __future__ import annotations

from .intent_compiler import compile_intent_spec_v2
from .plan_builder import build_task_plan_steps
from .provider_registry import list_provider_contracts, provider_or_raise, providers_for_task
from .provider_broker import rank_task_capabilities
from .provider_outcomes import record_provider_outcome, recent_provider_adjustments
from .memory_candidates import (
    emit_memory_candidate,
    list_memory_candidates,
    list_memory_candidates_for_sync,
    mark_memory_candidate_review,
)
from .plan_store import fetch_session_plan_steps, resolve_execute_step_metadata
from .step_executor import list_queued_pre_execution_steps, run_pre_execution_steps_from_ledger, run_reasoning_step
from .task_matcher import detect_high_risk_action, infer_domain, match_task_type
from .task_registry import TaskContract, list_task_contracts, task_or_none, task_or_raise
from .world_model import create_artifact, create_decision_window, create_followup, upsert_commitment

__all__ = [
    "ProactivePlanner",
    "TaskContract",
    "compile_intent_spec_v2",
    "build_task_plan_steps",
    "run_reasoning_step",
    "run_pre_execution_steps_from_ledger",
    "list_queued_pre_execution_steps",
    "fetch_session_plan_steps",
    "resolve_execute_step_metadata",
    "list_provider_contracts",
    "provider_or_raise",
    "providers_for_task",
    "rank_task_capabilities",
    "record_provider_outcome",
    "recent_provider_adjustments",
    "emit_memory_candidate",
    "mark_memory_candidate_review",
    "list_memory_candidates",
    "list_memory_candidates_for_sync",
    "upsert_commitment",
    "create_artifact",
    "create_followup",
    "create_decision_window",
    "task_or_none",
    "task_or_raise",
    "list_task_contracts",
    "infer_domain",
    "detect_high_risk_action",
    "match_task_type",
]


def __getattr__(name: str):
    if name == "ProactivePlanner":
        from .proactive import ProactivePlanner

        return ProactivePlanner
    raise AttributeError(f"module 'app.planner' has no attribute {name!r}")
