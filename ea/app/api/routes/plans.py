from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.api.dependencies import RequestContext, get_container, get_request_context, resolve_principal_id
from app.container import AppContainer
from app.domain.models import TaskExecutionRequest
from app.services.orchestrator import HumanTaskRequiredError
from app.services.policy import ApprovalRequiredError, PolicyDeniedError

router = APIRouter(prefix="/v1/plans", tags=["plans"])


class PlanCompileIn(BaseModel):
    task_key: str = Field(min_length=1, max_length=200)
    principal_id: str | None = Field(default=None, min_length=1, max_length=200)
    goal: str = Field(default="", max_length=2000)


class IntentOut(BaseModel):
    principal_id: str
    goal: str
    task_type: str
    deliverable_type: str
    risk_class: str
    approval_class: str
    budget_class: str
    stakeholders: list[str]
    evidence_requirements: list[str]
    allowed_tools: list[str]
    desired_artifact: str
    time_horizon: str
    interruption_budget: str
    memory_write_policy: str


class PlanStepOut(BaseModel):
    step_key: str
    step_kind: str
    tool_name: str
    owner: str
    authority_class: str
    review_class: str
    failure_strategy: str
    evidence_required: list[str]
    approval_required: bool
    reversible: bool
    expected_artifact: str
    fallback: str
    depends_on: list[str]
    input_keys: list[str]
    output_keys: list[str]
    task_type: str
    role_required: str
    brief: str
    priority: str
    sla_minutes: int
    auto_assign_if_unique: bool
    desired_output_json: dict[str, object]
    authority_required: str
    why_human: str
    quality_rubric_json: dict[str, object]


class PlanOut(BaseModel):
    plan_id: str
    task_key: str
    principal_id: str
    created_at: str
    steps: list[PlanStepOut]


class PlanCompileOut(BaseModel):
    intent: IntentOut
    plan: PlanOut


class PlanExecuteIn(BaseModel):
    task_key: str = Field(min_length=1, max_length=200)
    text: str = Field(min_length=1, max_length=20000)
    principal_id: str | None = Field(default=None, min_length=1, max_length=200)
    goal: str = Field(default="", max_length=2000)


class PlanExecuteOut(BaseModel):
    task_key: str
    artifact_id: str
    kind: str
    content: str
    preview_text: str = ""
    storage_handle: str = ""
    execution_session_id: str
    deliverable_type: str = ""


class PlanExecuteAcceptedOut(BaseModel):
    task_key: str
    session_id: str
    approval_id: str = ""
    human_task_id: str = ""
    status: str
    next_action: str


@router.post("/compile")
def compile_plan(
    body: PlanCompileIn,
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> PlanCompileOut:
    principal_id = resolve_principal_id(body.principal_id, context)
    intent, plan = container.planner.build_plan(
        task_key=body.task_key,
        principal_id=principal_id,
        goal=body.goal,
    )
    return PlanCompileOut(
        intent=IntentOut(
            principal_id=intent.principal_id,
            goal=intent.goal,
            task_type=intent.task_type,
            deliverable_type=intent.deliverable_type,
            risk_class=intent.risk_class,
            approval_class=intent.approval_class,
            budget_class=intent.budget_class,
            stakeholders=list(intent.stakeholders),
            evidence_requirements=list(intent.evidence_requirements),
            allowed_tools=list(intent.allowed_tools),
            desired_artifact=intent.desired_artifact,
            time_horizon=intent.time_horizon,
            interruption_budget=intent.interruption_budget,
            memory_write_policy=intent.memory_write_policy,
        ),
        plan=PlanOut(
            plan_id=plan.plan_id,
            task_key=plan.task_key,
            principal_id=plan.principal_id,
            created_at=plan.created_at,
            steps=[
                PlanStepOut(
                    step_key=s.step_key,
                    step_kind=s.step_kind,
                    tool_name=s.tool_name,
                    owner=s.owner,
                    authority_class=s.authority_class,
                    review_class=s.review_class,
                    failure_strategy=s.failure_strategy,
                    evidence_required=list(s.evidence_required),
                    approval_required=s.approval_required,
                    reversible=s.reversible,
                    expected_artifact=s.expected_artifact,
                    fallback=s.fallback,
                    depends_on=list(s.depends_on),
                    input_keys=list(s.input_keys),
                    output_keys=list(s.output_keys),
                    task_type=s.task_type,
                    role_required=s.role_required,
                    brief=s.brief,
                    priority=s.priority,
                    sla_minutes=s.sla_minutes,
                    auto_assign_if_unique=s.auto_assign_if_unique,
                    desired_output_json=dict(s.desired_output_json),
                    authority_required=s.authority_required,
                    why_human=s.why_human,
                    quality_rubric_json=dict(s.quality_rubric_json),
                )
                for s in plan.steps
            ],
        ),
    )


@router.post("/execute")
def execute_plan(
    body: PlanExecuteIn,
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> PlanExecuteOut | PlanExecuteAcceptedOut:
    principal_id = resolve_principal_id(body.principal_id, context)
    try:
        artifact = container.orchestrator.execute_task_artifact(
            TaskExecutionRequest(
                task_key=body.task_key,
                text=str(body.text or ""),
                principal_id=principal_id,
                goal=body.goal,
            )
        )
    except ApprovalRequiredError as exc:
        return JSONResponse(
            status_code=202,
            content=PlanExecuteAcceptedOut(
                task_key=body.task_key,
                session_id=exc.session_id,
                approval_id=exc.approval_id,
                status=exc.status,
                next_action="poll_or_subscribe",
            ).model_dump(),
        )
    except HumanTaskRequiredError as exc:
        return JSONResponse(
            status_code=202,
            content=PlanExecuteAcceptedOut(
                task_key=body.task_key,
                session_id=exc.session_id,
                human_task_id=exc.human_task_id,
                status=exc.status,
                next_action="poll_or_subscribe",
            ).model_dump(),
        )
    except PolicyDeniedError as exc:
        reason = str(exc or "policy_denied")
        raise HTTPException(status_code=403, detail=f"policy_denied:{reason}") from exc
    return PlanExecuteOut(
        task_key=body.task_key,
        artifact_id=artifact.artifact_id,
        kind=artifact.kind,
        content=artifact.content,
        preview_text=(f"{artifact.content[:157]}..." if len(artifact.content) > 160 else artifact.content),
        storage_handle=f"artifact://{artifact.artifact_id}",
        execution_session_id=artifact.execution_session_id,
        deliverable_type=artifact.kind,
    )
