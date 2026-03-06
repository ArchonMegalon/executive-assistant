from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.api.dependencies import RequestContext, get_container, get_request_context, resolve_principal_id
from app.container import AppContainer

router = APIRouter(prefix="/v1/human/tasks", tags=["human"])


class HumanTaskCreateIn(BaseModel):
    session_id: str
    step_id: str | None = None
    principal_id: str | None = None
    task_type: str
    role_required: str
    brief: str
    input_json: dict[str, object] = Field(default_factory=dict)
    desired_output_json: dict[str, object] = Field(default_factory=dict)
    priority: str = "normal"
    sla_due_at: str | None = None
    resume_session_on_return: bool = False


class HumanTaskClaimIn(BaseModel):
    operator_id: str


class HumanTaskReturnIn(BaseModel):
    operator_id: str
    resolution: str
    returned_payload_json: dict[str, object] = Field(default_factory=dict)
    provenance_json: dict[str, object] = Field(default_factory=dict)


class HumanTaskOut(BaseModel):
    human_task_id: str
    session_id: str
    step_id: str | None
    principal_id: str
    task_type: str
    role_required: str
    brief: str
    input_json: dict[str, object]
    desired_output_json: dict[str, object]
    priority: str
    sla_due_at: str | None
    status: str
    assigned_operator_id: str
    resolution: str
    resume_session_on_return: bool
    returned_payload_json: dict[str, object]
    provenance_json: dict[str, object]
    created_at: str
    updated_at: str


def _to_out(row) -> HumanTaskOut:  # type: ignore[no-untyped-def]
    return HumanTaskOut(
        human_task_id=row.human_task_id,
        session_id=row.session_id,
        step_id=row.step_id,
        principal_id=row.principal_id,
        task_type=row.task_type,
        role_required=row.role_required,
        brief=row.brief,
        input_json=row.input_json,
        desired_output_json=row.desired_output_json,
        priority=row.priority,
        sla_due_at=row.sla_due_at,
        status=row.status,
        assigned_operator_id=row.assigned_operator_id,
        resolution=row.resolution,
        resume_session_on_return=row.resume_session_on_return,
        returned_payload_json=row.returned_payload_json,
        provenance_json=row.provenance_json,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


@router.post("")
def create_human_task(
    payload: HumanTaskCreateIn,
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> HumanTaskOut:
    principal_id = resolve_principal_id(payload.principal_id, context)
    try:
        row = container.orchestrator.create_human_task(
            session_id=payload.session_id,
            step_id=payload.step_id,
            principal_id=principal_id,
            task_type=payload.task_type,
            role_required=payload.role_required,
            brief=payload.brief,
            input_json=payload.input_json,
            desired_output_json=payload.desired_output_json,
            priority=payload.priority,
            sla_due_at=payload.sla_due_at,
            resume_session_on_return=payload.resume_session_on_return,
        )
    except KeyError as exc:
        code = str(exc.args[0] or "session_not_found")
        status_code = 400 if code == "step_id_required" else 404
        raise HTTPException(status_code=status_code, detail=code) from exc
    return _to_out(row)


@router.get("")
def list_human_tasks(
    principal_id: str | None = None,
    session_id: str | None = None,
    status: str | None = None,
    role_required: str | None = None,
    assigned_operator_id: str | None = None,
    overdue_only: bool = False,
    limit: int = Query(default=50, ge=1, le=500),
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> list[HumanTaskOut]:
    resolved_principal = resolve_principal_id(principal_id, context)
    rows = container.orchestrator.list_human_tasks(
        principal_id=resolved_principal,
        session_id=session_id,
        status=status,
        role_required=role_required,
        assigned_operator_id=assigned_operator_id,
        overdue_only=overdue_only,
        limit=limit,
    )
    return [_to_out(row) for row in rows]


@router.get("/{human_task_id}")
def get_human_task(
    human_task_id: str,
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> HumanTaskOut:
    row = container.orchestrator.fetch_human_task(human_task_id, principal_id=context.principal_id)
    if row is None:
        raise HTTPException(status_code=404, detail="human_task_not_found")
    return _to_out(row)


@router.post("/{human_task_id}/claim")
def claim_human_task(
    human_task_id: str,
    payload: HumanTaskClaimIn,
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> HumanTaskOut:
    found = container.orchestrator.fetch_human_task(human_task_id, principal_id=context.principal_id)
    if found is None:
        raise HTTPException(status_code=404, detail="human_task_not_found")
    row = container.orchestrator.claim_human_task(
        human_task_id,
        principal_id=context.principal_id,
        operator_id=payload.operator_id,
    )
    if row is None:
        raise HTTPException(status_code=409, detail="human_task_not_claimable")
    return _to_out(row)


@router.post("/{human_task_id}/return")
def return_human_task(
    human_task_id: str,
    payload: HumanTaskReturnIn,
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> HumanTaskOut:
    found = container.orchestrator.fetch_human_task(human_task_id, principal_id=context.principal_id)
    if found is None:
        raise HTTPException(status_code=404, detail="human_task_not_found")
    row = container.orchestrator.return_human_task(
        human_task_id,
        principal_id=context.principal_id,
        operator_id=payload.operator_id,
        resolution=payload.resolution,
        returned_payload_json=payload.returned_payload_json,
        provenance_json=payload.provenance_json,
    )
    if row is None:
        raise HTTPException(status_code=409, detail="human_task_not_returnable")
    return _to_out(row)
