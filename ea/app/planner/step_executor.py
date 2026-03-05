from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Callable

from app.gog import gog_scout

_PLANNER_PRE_EXEC_STEPS = {
    "collect_intake_context",
    "collect_feedback_context",
    "compile_prompt_pack",
    "prepare_draft_context",
    "prepare_multimodal_context",
    "gather_research_context",
    "ingest_external_event",
    "prepare_external_action",
    "build_approval_context",
    "prepare_route_render_context",
    "analyze_trip_commitment",
    "compare_travel_options",
    "verify_payment_context",
    "gather_project_context",
    "review_health_context",
}


def _is_deterministic_pre_step(*, step_key: str, step_kind: str = "") -> bool:
    key = str(step_key or "").strip().lower()
    kind = str(step_kind or "").strip().lower()
    if not key:
        return False
    if key in {"execute_intent", "render_reply", "safety_gate"}:
        return False
    if key in _PLANNER_PRE_EXEC_STEPS:
        return True
    return kind in {"compile", "context", "approval"}


def _deterministic_output_refs(*, step_key: str, step_order: int = 0) -> list[str]:
    key = str(step_key or "").strip().lower() or "unknown_step"
    order = int(step_order or 0)
    if order > 0:
        return [f"planner_context:{order}:{key}"]
    return [f"planner_context:{key}"]


async def run_reasoning_step(
    *,
    container: str,
    prompt: str,
    google_account: str,
    ui_updater: Callable[[str], Awaitable[None]],
    task_name: str,
    timeout_sec: float = 240.0,
    runner: Callable[..., Awaitable[str]] | None = None,
) -> str:
    execute_runner = runner or gog_scout
    return await asyncio.wait_for(
        execute_runner(
            str(container or ""),
            str(prompt or ""),
            str(google_account or ""),
            ui_updater,
            task_name=str(task_name or "Intent Execution"),
        ),
        timeout=float(timeout_sec),
    )


def run_pre_execution_steps(
    *,
    session_id: str,
    plan_steps: list[dict[str, Any]],
    intent_spec: dict[str, Any],
    mark_step: Callable[..., None],
    append_event: Callable[..., None],
) -> None:
    if not session_id:
        return
    domain = str((intent_spec or {}).get("domain") or "")
    task_type = str((intent_spec or {}).get("task_type") or "")
    objective = str((intent_spec or {}).get("objective") or "")[:200]
    for idx, row in enumerate(list(plan_steps or []), start=1):
        step_key = str((row or {}).get("step_key") or "").strip()
        if not _is_deterministic_pre_step(step_key=step_key):
            continue
        output_refs = _deterministic_output_refs(step_key=step_key, step_order=idx)
        mark_step(
            session_id,
            step_key,
            "running",
            evidence={"domain": domain, "task_type": task_type},
            step_kind="context",
        )
        mark_step(
            session_id,
            step_key,
            "completed",
            result={
                "planner_step": step_key,
                "status": "deterministic_context_ready",
                "domain": domain,
                "task_type": task_type,
                "objective_preview": objective,
                "output_refs": output_refs,
            },
            output_refs=output_refs,
            step_kind="context",
            provider_key="deterministic_planner",
        )
        append_event(
            session_id,
            event_type="planner_context_step_completed",
            message=f"Planner pre-execution step completed: {step_key}",
            payload={
                "step_key": step_key,
                "domain": domain,
                "task_type": task_type,
                "output_refs": output_refs,
            },
        )


def list_queued_pre_execution_steps(
    *,
    session_id: str,
    fetch_steps: Callable[[str], list[dict[str, Any]]] | None = None,
) -> list[dict[str, Any]]:
    if not session_id:
        return []

    if fetch_steps is not None:
        rows = list(fetch_steps(str(session_id)) or [])
    else:
        rows = []
        try:
            from app.db import get_db

            db = get_db()
            rows = list(
                db.fetchall(
                    """
                    SELECT step_order, step_key, step_kind, preconditions_json, evidence_json
                    FROM execution_steps
                    WHERE session_id = %s
                      AND status = 'queued'
                    ORDER BY step_order ASC
                    """,
                    (str(session_id),),
                )
                or []
            )
        except Exception:
            return []

    out: list[dict[str, Any]] = []
    for row in rows:
        step_key = str((row or {}).get("step_key") or "").strip()
        step_kind = str((row or {}).get("step_kind") or "").strip().lower()
        if not _is_deterministic_pre_step(step_key=step_key, step_kind=step_kind):
            continue
        out.append(
            {
                "step_order": int((row or {}).get("step_order") or 0),
                "step_key": step_key,
                "step_kind": step_kind or "generic",
                "preconditions_json": dict((row or {}).get("preconditions_json") or {}),
                "evidence_json": dict((row or {}).get("evidence_json") or {}),
            }
        )
    out.sort(key=lambda row: int(row.get("step_order") or 0))
    return out


def run_pre_execution_steps_from_ledger(
    *,
    session_id: str,
    intent_spec: dict[str, Any],
    mark_step: Callable[..., None],
    append_event: Callable[..., None],
    fetch_steps: Callable[[str], list[dict[str, Any]]] | None = None,
) -> int:
    queued_rows = list_queued_pre_execution_steps(session_id=session_id, fetch_steps=fetch_steps)
    if not queued_rows:
        return 0
    domain = str((intent_spec or {}).get("domain") or "")
    task_type = str((intent_spec or {}).get("task_type") or "")
    objective = str((intent_spec or {}).get("objective") or "")[:200]
    for row in queued_rows:
        step_key = str((row or {}).get("step_key") or "").strip()
        step_order = int((row or {}).get("step_order") or 0)
        output_refs = _deterministic_output_refs(step_key=step_key, step_order=step_order)
        mark_step(
            session_id,
            step_key,
            "running",
            evidence={"domain": domain, "task_type": task_type},
            step_kind=str((row or {}).get("step_kind") or "context"),
        )
        mark_step(
            session_id,
            step_key,
            "completed",
            result={
                "planner_step": step_key,
                "status": "deterministic_context_ready",
                "domain": domain,
                "task_type": task_type,
                "objective_preview": objective,
                "output_refs": output_refs,
            },
            output_refs=output_refs,
            step_kind=str((row or {}).get("step_kind") or "context"),
            provider_key="deterministic_planner",
        )
        append_event(
            session_id,
            event_type="planner_context_step_completed",
            message=f"Planner pre-execution step completed from ledger: {step_key}",
            payload={
                "step_key": step_key,
                "domain": domain,
                "task_type": task_type,
                "output_refs": output_refs,
            },
        )
    return len(queued_rows)


def _normalize_execute_step_metadata(metadata: dict[str, Any], fallback: dict[str, Any]) -> dict[str, Any]:
    task_type = str((metadata or {}).get("task_type") or fallback.get("task_type") or "free_text_response").strip().lower()
    artifact_type = (
        str((metadata or {}).get("output_artifact_type") or fallback.get("output_artifact_type") or "chat_response")
        .strip()
        .lower()
    )
    providers = [str(x) for x in list((metadata or {}).get("provider_candidates") or []) if str(x or "").strip()]
    if not providers:
        providers = [str(x) for x in list(fallback.get("provider_candidates") or []) if str(x or "").strip()]
    metadata_source = str((metadata or {}).get("metadata_source") or fallback.get("metadata_source") or "fallback_default")
    provenance = [str(x) for x in list((metadata or {}).get("metadata_provenance") or []) if str(x or "").strip()]
    if not provenance:
        provenance = [str(x) for x in list(fallback.get("metadata_provenance") or []) if str(x or "").strip()]
    if not provenance:
        provenance = [str(metadata_source)]
    return {
        "task_type": task_type or "free_text_response",
        "output_artifact_type": artifact_type or "chat_response",
        "provider_candidates": providers,
        "metadata_source": metadata_source or "fallback_default",
        "metadata_provenance": provenance,
    }


def _build_execute_step_fallback(
    *,
    plan_steps: list[dict[str, Any]],
    intent_spec: dict[str, Any],
) -> dict[str, Any]:
    execute_row = next(
        (row for row in list(plan_steps or []) if str((row or {}).get("step_key") or "").strip() == "execute_intent"),
        {},
    )
    has_execute_row = bool(execute_row)
    task_type = str((execute_row or {}).get("task_type") or (intent_spec or {}).get("task_type") or "free_text_response")
    artifact_type = str((execute_row or {}).get("output_artifact_type") or "chat_response")
    providers = [str(x) for x in list((execute_row or {}).get("provider_candidates") or []) if str(x or "").strip()]
    source = "plan_steps_execute_step" if has_execute_row else "intent_spec_default"
    return {
        "task_type": task_type,
        "output_artifact_type": artifact_type,
        "provider_candidates": providers,
        "metadata_source": source,
        "metadata_provenance": [source],
    }


def _execute_step_metadata(
    *,
    session_id: str,
    plan_steps: list[dict[str, Any]],
    intent_spec: dict[str, Any],
) -> dict[str, Any]:
    metadata = _build_execute_step_fallback(plan_steps=plan_steps, intent_spec=intent_spec)
    try:
        from app.planner.plan_store import resolve_execute_step_metadata

        resolved = resolve_execute_step_metadata(session_id, fallback=metadata)
        if isinstance(resolved, dict):
            metadata = _normalize_execute_step_metadata(resolved, fallback=metadata)
    except Exception:
        metadata = _normalize_execute_step_metadata({}, fallback=metadata)
    return metadata


async def execute_planned_reasoning_step(
    *,
    session_id: str,
    plan_steps: list[dict[str, Any]],
    intent_spec: dict[str, Any],
    prompt: str,
    container: str,
    google_account: str,
    ui_updater: Callable[[str], Awaitable[None]],
    task_name: str,
    mark_step: Callable[..., None],
    append_event: Callable[..., None],
    run_reasoning_step_func: Callable[..., Awaitable[str]] = run_reasoning_step,
    reasoning_runner: Callable[..., Awaitable[str]] | None = None,
    timeout_sec: float = 240.0,
) -> dict[str, Any]:
    metadata = _execute_step_metadata(session_id=session_id, plan_steps=plan_steps, intent_spec=intent_spec)
    mark_step(
        session_id,
        "execute_intent",
        "running",
        evidence={
            "task_type": metadata["task_type"],
            "output_artifact_type": metadata["output_artifact_type"],
            "provider_candidates": metadata["provider_candidates"],
            "metadata_source": metadata["metadata_source"],
            "metadata_provenance": metadata["metadata_provenance"],
        },
    )
    report = await run_reasoning_step_func(
        container=str(container or ""),
        prompt=str(prompt or ""),
        google_account=str(google_account or ""),
        ui_updater=ui_updater,
        task_name=str(task_name or "Intent Execution"),
        timeout_sec=float(timeout_sec),
        runner=reasoning_runner,
    )
    report_chars = len(str(report or ""))
    mark_step(
        session_id,
        "execute_intent",
        "completed",
        result={
            "report_chars": report_chars,
            "task_type": metadata["task_type"],
            "output_artifact_type": metadata["output_artifact_type"],
            "provider_candidates": metadata["provider_candidates"],
            "metadata_source": metadata["metadata_source"],
            "metadata_provenance": metadata["metadata_provenance"],
        },
    )
    append_event(
        session_id,
        event_type="execute_intent_completed",
        message="Planner-owned execute_intent step completed.",
        payload={
            "task_type": metadata["task_type"],
            "output_artifact_type": metadata["output_artifact_type"],
            "provider_candidates": metadata["provider_candidates"],
            "metadata_source": metadata["metadata_source"],
            "metadata_provenance": metadata["metadata_provenance"],
            "report_chars": report_chars,
        },
    )
    payload = dict(metadata)
    payload["report"] = report
    return payload


__all__ = [
    "run_reasoning_step",
    "run_pre_execution_steps",
    "list_queued_pre_execution_steps",
    "run_pre_execution_steps_from_ledger",
    "execute_planned_reasoning_step",
]
