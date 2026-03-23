from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query

from app.api.dependencies import RequestContext, get_container, get_request_context, resolve_principal_id
from app.container import AppContainer
from app.services import responses_upstream as upstream

router = APIRouter(prefix="/v1/runtime", tags=["runtime"])


def _candidate_out(row) -> dict[str, object]:  # type: ignore[no-untyped-def]
    return {
        "kind": str(row.kind or ""),
        "record_id": str(row.record_id or ""),
        "principal_id": str(row.principal_id or ""),
        "due_at": str(row.due_at or ""),
        "task_key": str(row.task_key or ""),
        "goal": str(row.goal or ""),
        "source_text": str(row.source_text or ""),
        "context_refs": list(row.context_refs or ()),
        "dedupe_key": str(row.dedupe_key or ""),
    }


@router.get("/cognitive-load", response_model=None)
def get_cognitive_load(
    principal_id: str | None = Query(default=None, min_length=1),
    scope: str = Query(default="default", min_length=1, max_length=120),
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> dict[str, object]:
    resolved_principal = resolve_principal_id(principal_id, context)
    state = container.cognitive_load.refresh_for_principal(resolved_principal, scope=scope)
    budget = container.memory_runtime.current_interruption_budget(principal_id=resolved_principal, scope=scope)
    return {
        "principal_id": resolved_principal,
        "scope": scope,
        "state": {
            "principal_id": state.principal_id,
            "state": state.state,
            "messages_last_15m": state.messages_last_15m,
            "observed_at": state.observed_at,
            "interruption_budget_state": state.interruption_budget_state,
        },
        "interruption_budget": None
        if budget is None
        else {
            "budget_id": budget.budget_id,
            "window_kind": budget.window_kind,
            "budget_minutes": budget.budget_minutes,
            "used_minutes": budget.used_minutes,
            "reset_at": budget.reset_at,
            "status": budget.status,
            "notes": budget.notes,
        },
    }


@router.get("/proactive-horizon/scan", response_model=None)
def scan_proactive_horizon(
    principal_id: str | None = Query(default=None, min_length=1),
    hours: int = Query(default=24, ge=1, le=168),
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> dict[str, object]:
    resolved_principal = resolve_principal_id(principal_id, context)
    rows = container.proactive_horizon.scan(
        now=datetime.now(timezone.utc),
        scan_window_hours=hours,
        principal_id=resolved_principal,
    )
    return {
        "principal_id": resolved_principal,
        "hours": hours,
        "candidate_count": len(rows),
        "candidates": [_candidate_out(row) for row in rows],
    }


@router.post("/proactive-horizon/run", response_model=None)
def run_proactive_horizon(
    principal_id: str | None = Query(default=None, min_length=1),
    hours: int = Query(default=24, ge=1, le=168),
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> dict[str, object]:
    resolved_principal = resolve_principal_id(principal_id, context)
    rows = container.proactive_horizon.run_once(
        now=datetime.now(timezone.utc),
        scan_window_hours=hours,
        principal_id=resolved_principal,
    )
    return {
        "principal_id": resolved_principal,
        "hours": hours,
        "launched_count": len(rows),
        "launched": [_candidate_out(row) for row in rows],
    }


@router.get("/lanes/telemetry", response_model=None)
def get_lane_telemetry(
    window: str = Query(default="1h", min_length=1, max_length=20),
    context: RequestContext = Depends(get_request_context),
) -> dict[str, object]:
    report = upstream.codex_status_report(window=window)
    return {
        "principal_id": context.principal_id,
        "window": window,
        "provider_config": dict(report.get("provider_config") or {}),
        "lane_telemetry": dict(report.get("lane_telemetry") or {}),
        "onemin_aggregate": dict(report.get("onemin_aggregate") or {}),
        "onemin_billing_aggregate": dict(report.get("onemin_billing_aggregate") or {}),
        "fleet_burn": dict(report.get("fleet_burn") or {}),
        "avoided_credits": dict(report.get("avoided_credits") or {}),
    }
