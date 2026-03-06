from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.api.dependencies import get_container
from app.container import AppContainer

router = APIRouter(prefix="/v1/plans", tags=["plans"])


class PlanCompileIn(BaseModel):
    task_key: str = Field(min_length=1, max_length=200)
    principal_id: str = Field(default="local-user", min_length=1, max_length=200)
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


class PlanOut(BaseModel):
    plan_id: str
    task_key: str
    principal_id: str
    created_at: str
    steps: list[PlanStepOut]


class PlanCompileOut(BaseModel):
    intent: IntentOut
    plan: PlanOut


@router.post("/compile")
def compile_plan(
    body: PlanCompileIn,
    container: AppContainer = Depends(get_container),
) -> PlanCompileOut:
    intent, plan = container.planner.build_plan(
        task_key=body.task_key,
        principal_id=body.principal_id,
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
                )
                for s in plan.steps
            ],
        ),
    )
