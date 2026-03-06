from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.api.dependencies import get_container
from app.container import AppContainer
from app.domain.models import RewriteRequest
from app.services.policy import ApprovalRequiredError, PolicyDeniedError

router = APIRouter(prefix="/v1/rewrite", tags=["rewrite"])


class RewriteIn(BaseModel):
    text: str


class RewriteOut(BaseModel):
    artifact_id: str
    kind: str
    content: str
    execution_session_id: str


class RewriteAcceptedOut(BaseModel):
    session_id: str
    approval_id: str
    status: str
    next_action: str


class SessionEventOut(BaseModel):
    event_id: str
    name: str
    payload: dict[str, object]
    created_at: str


class SessionStepOut(BaseModel):
    step_id: str
    parent_step_id: str | None
    step_kind: str
    state: str
    attempt_count: int
    input_json: dict[str, object]
    output_json: dict[str, object]
    error_json: dict[str, object]
    correlation_id: str
    causation_id: str
    actor_type: str
    actor_id: str
    created_at: str
    updated_at: str


class SessionReceiptOut(BaseModel):
    receipt_id: str
    step_id: str
    tool_name: str
    action_kind: str
    target_ref: str
    receipt_json: dict[str, object]
    created_at: str


class SessionArtifactOut(BaseModel):
    artifact_id: str
    kind: str
    content: str
    execution_session_id: str


class SessionQueueItemOut(BaseModel):
    queue_id: str
    step_id: str
    state: str
    lease_owner: str
    lease_expires_at: str | None
    attempt_count: int
    next_attempt_at: str | None
    idempotency_key: str
    last_error: str
    created_at: str
    updated_at: str


class SessionRunCostOut(BaseModel):
    cost_id: str
    model_name: str
    tokens_in: int
    tokens_out: int
    cost_usd: float
    created_at: str


class SessionHumanTaskOut(BaseModel):
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
    returned_payload_json: dict[str, object]
    provenance_json: dict[str, object]
    created_at: str
    updated_at: str


class SessionOut(BaseModel):
    session_id: str
    status: str
    created_at: str
    updated_at: str
    intent_task_type: str
    intent_risk_class: str
    events: list[SessionEventOut]
    steps: list[SessionStepOut]
    queue_items: list[SessionQueueItemOut]
    receipts: list[SessionReceiptOut]
    artifacts: list[SessionArtifactOut]
    run_costs: list[SessionRunCostOut]
    human_tasks: list[SessionHumanTaskOut]


@router.post("/artifact")
def create_artifact(
    payload: RewriteIn,
    container: AppContainer = Depends(get_container),
) -> RewriteOut | RewriteAcceptedOut:
    text = str(payload.text or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="text is required")
    try:
        artifact = container.orchestrator.build_artifact(RewriteRequest(text=text))
    except ApprovalRequiredError as exc:
        return JSONResponse(
            status_code=202,
            content=RewriteAcceptedOut(
                session_id=exc.session_id,
                approval_id=exc.approval_id,
                status=exc.status,
                next_action="poll_or_subscribe",
            ).model_dump(),
        )
    except PolicyDeniedError as exc:
        reason = str(exc or "policy_denied")
        raise HTTPException(status_code=403, detail=f"policy_denied:{reason}") from exc
    return RewriteOut(
        artifact_id=artifact.artifact_id,
        kind=artifact.kind,
        content=artifact.content,
        execution_session_id=artifact.execution_session_id,
    )


@router.get("/sessions/{session_id}")
def get_session(
    session_id: str,
    container: AppContainer = Depends(get_container),
) -> SessionOut:
    found = container.orchestrator.fetch_session(session_id)
    if not found:
        raise HTTPException(status_code=404, detail="session not found")
    session = found.session
    events = found.events
    return SessionOut(
        session_id=session.session_id,
        status=session.status,
        created_at=session.created_at,
        updated_at=session.updated_at,
        intent_task_type=session.intent.task_type,
        intent_risk_class=session.intent.risk_class,
        events=[
            SessionEventOut(
                event_id=e.event_id,
                name=e.name,
                payload=e.payload,
                created_at=e.created_at,
            )
            for e in events
        ],
        steps=[
            SessionStepOut(
                step_id=s.step_id,
                parent_step_id=s.parent_step_id,
                step_kind=s.step_kind,
                state=s.state,
                attempt_count=s.attempt_count,
                input_json=s.input_json,
                output_json=s.output_json,
                error_json=s.error_json,
                correlation_id=s.correlation_id,
                causation_id=s.causation_id,
                actor_type=s.actor_type,
                actor_id=s.actor_id,
                created_at=s.created_at,
                updated_at=s.updated_at,
            )
            for s in found.steps
        ],
        queue_items=[
            SessionQueueItemOut(
                queue_id=q.queue_id,
                step_id=q.step_id,
                state=q.state,
                lease_owner=q.lease_owner,
                lease_expires_at=q.lease_expires_at,
                attempt_count=q.attempt_count,
                next_attempt_at=q.next_attempt_at,
                idempotency_key=q.idempotency_key,
                last_error=q.last_error,
                created_at=q.created_at,
                updated_at=q.updated_at,
            )
            for q in found.queue_items
        ],
        receipts=[
            SessionReceiptOut(
                receipt_id=r.receipt_id,
                step_id=r.step_id,
                tool_name=r.tool_name,
                action_kind=r.action_kind,
                target_ref=r.target_ref,
                receipt_json=r.receipt_json,
                created_at=r.created_at,
            )
            for r in found.receipts
        ],
        artifacts=[
            SessionArtifactOut(
                artifact_id=a.artifact_id,
                kind=a.kind,
                content=a.content,
                execution_session_id=a.execution_session_id,
            )
            for a in found.artifacts
        ],
        run_costs=[
            SessionRunCostOut(
                cost_id=c.cost_id,
                model_name=c.model_name,
                tokens_in=c.tokens_in,
                tokens_out=c.tokens_out,
                cost_usd=c.cost_usd,
                created_at=c.created_at,
            )
            for c in found.run_costs
        ],
        human_tasks=[
            SessionHumanTaskOut(
                human_task_id=t.human_task_id,
                session_id=t.session_id,
                step_id=t.step_id,
                principal_id=t.principal_id,
                task_type=t.task_type,
                role_required=t.role_required,
                brief=t.brief,
                input_json=t.input_json,
                desired_output_json=t.desired_output_json,
                priority=t.priority,
                sla_due_at=t.sla_due_at,
                status=t.status,
                assigned_operator_id=t.assigned_operator_id,
                resolution=t.resolution,
                returned_payload_json=t.returned_payload_json,
                provenance_json=t.provenance_json,
                created_at=t.created_at,
                updated_at=t.updated_at,
            )
            for t in found.human_tasks
        ],
    )


@router.get("/artifacts/{artifact_id}")
def get_artifact(
    artifact_id: str,
    container: AppContainer = Depends(get_container),
) -> RewriteOut:
    found = container.orchestrator.fetch_artifact(artifact_id)
    if not found:
        raise HTTPException(status_code=404, detail="artifact_not_found")
    return RewriteOut(
        artifact_id=found.artifact_id,
        kind=found.kind,
        content=found.content,
        execution_session_id=found.execution_session_id,
    )


@router.get("/receipts/{receipt_id}")
def get_receipt(
    receipt_id: str,
    container: AppContainer = Depends(get_container),
) -> SessionReceiptOut:
    found = container.orchestrator.fetch_receipt(receipt_id)
    if not found:
        raise HTTPException(status_code=404, detail="receipt_not_found")
    return SessionReceiptOut(
        receipt_id=found.receipt_id,
        step_id=found.step_id,
        tool_name=found.tool_name,
        action_kind=found.action_kind,
        target_ref=found.target_ref,
        receipt_json=found.receipt_json,
        created_at=found.created_at,
    )


@router.get("/run-costs/{cost_id}")
def get_run_cost(
    cost_id: str,
    container: AppContainer = Depends(get_container),
) -> SessionRunCostOut:
    found = container.orchestrator.fetch_run_cost(cost_id)
    if not found:
        raise HTTPException(status_code=404, detail="run_cost_not_found")
    return SessionRunCostOut(
        cost_id=found.cost_id,
        model_name=found.model_name,
        tokens_in=found.tokens_in,
        tokens_out=found.tokens_out,
        cost_usd=found.cost_usd,
        created_at=found.created_at,
    )
