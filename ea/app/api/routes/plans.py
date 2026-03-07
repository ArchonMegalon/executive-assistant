from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, model_validator
from pydantic_core import PydanticCustomError

from app.api.dependencies import RequestContext, get_container, get_request_context, resolve_principal_id
from app.container import AppContainer
from app.domain.models import (
    PlanValidationError,
    TaskExecutionRequest,
    artifact_body_ref,
    artifact_preview_text,
    artifact_storage_handle,
    normalize_artifact,
)
from app.services.orchestrator import AsyncExecutionQueuedError, HumanTaskRequiredError
from app.services.policy import ApprovalRequiredError, PolicyDeniedError

router = APIRouter(prefix="/v1/plans", tags=["plans"])


class PlanCompileIn(BaseModel):
    task_key: str = Field(default="", max_length=200)
    skill_key: str = Field(default="", max_length=200)
    principal_id: str | None = Field(default=None, min_length=1, max_length=200)
    goal: str = Field(default="", max_length=2000)

    @model_validator(mode="after")
    def _require_task_key_or_skill_key(self) -> "PlanCompileIn":
        if str(self.task_key or "").strip() or str(self.skill_key or "").strip():
            return self
        raise PydanticCustomError("task_or_skill_key_required", "task_or_skill_key_required")


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
    timeout_budget_seconds: int
    max_attempts: int
    retry_backoff_seconds: int
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
    skill_key: str
    intent: IntentOut
    plan: PlanOut


class PlanExecuteIn(BaseModel):
    task_key: str = Field(default="", max_length=200)
    skill_key: str = Field(default="", max_length=200)
    text: str = Field(default="", max_length=20000)
    principal_id: str | None = Field(default=None, min_length=1, max_length=200)
    goal: str = Field(default="", max_length=2000)
    input_json: dict[str, object] = Field(default_factory=dict)
    context_refs: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _require_text_or_input_json(self) -> "PlanExecuteIn":
        if not str(self.task_key or "").strip() and not str(self.skill_key or "").strip():
            raise PydanticCustomError("task_or_skill_key_required", "task_or_skill_key_required")
        if str(self.text or "").strip() or dict(self.input_json or {}):
            return self
        raise PydanticCustomError("text_or_input_json_required", "text_or_input_json_required")


class PlanExecuteOut(BaseModel):
    skill_key: str
    task_key: str
    artifact_id: str
    kind: str
    content: str
    mime_type: str = "text/plain"
    preview_text: str = ""
    storage_handle: str = ""
    body_ref: str = ""
    structured_output_json: dict[str, object] = Field(default_factory=dict)
    attachments_json: dict[str, object] = Field(default_factory=dict)
    execution_session_id: str
    principal_id: str
    deliverable_type: str = ""


class PlanExecuteAcceptedOut(BaseModel):
    skill_key: str
    task_key: str
    session_id: str
    approval_id: str = ""
    human_task_id: str = ""
    status: str
    next_action: str

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "skill_key": "decision_briefing",
                    "task_key": "decision_brief_approval",
                    "session_id": "session-awaiting-approval",
                    "approval_id": "approval-123",
                    "human_task_id": "",
                    "status": "awaiting_approval",
                    "next_action": "poll_or_subscribe",
                },
                {
                    "skill_key": "stakeholder_briefing",
                    "task_key": "stakeholder_briefing_review",
                    "session_id": "session-awaiting-human",
                    "approval_id": "",
                    "human_task_id": "human-task-123",
                    "status": "awaiting_human",
                    "next_action": "poll_or_subscribe",
                },
                {
                    "skill_key": "rewrite_retry_delayed",
                    "task_key": "rewrite_retry_delayed",
                    "session_id": "session-queued-retry",
                    "approval_id": "",
                    "human_task_id": "",
                    "status": "queued",
                    "next_action": "poll_or_subscribe",
                },
            ]
        }
    }


def _resolve_skill_key(container: AppContainer, task_key: str) -> str:
    resolved_task_key = str(task_key or "").strip()
    if not resolved_task_key:
        return ""
    row = container.skills.get_skill(resolved_task_key)
    if row is None:
        return resolved_task_key
    return str(row.skill_key or resolved_task_key)


def _resolve_task_key(container: AppContainer, *, task_key: str = "", skill_key: str = "") -> str:
    resolved_task_key = str(task_key or "").strip()
    resolved_skill_key = str(skill_key or "").strip()
    if resolved_task_key and not resolved_skill_key:
        return resolved_task_key
    if resolved_skill_key:
        row = container.skills.get_skill(resolved_skill_key)
        if row is None:
            raise HTTPException(status_code=404, detail="skill_not_found")
        row_task_key = str(row.task_key or resolved_skill_key).strip() or resolved_skill_key
        if resolved_task_key and row_task_key != resolved_task_key:
            raise HTTPException(status_code=422, detail="task_skill_key_mismatch")
        return row_task_key
    return resolved_task_key


def _artifact_execute_out_payload(artifact):  # type: ignore[no-untyped-def]
    normalized = normalize_artifact(artifact)
    return {
        "artifact_id": normalized.artifact_id,
        "kind": normalized.kind,
        "content": normalized.content,
        "mime_type": normalized.mime_type,
        "preview_text": normalized.preview_text or artifact_preview_text(normalized.content),
        "storage_handle": normalized.storage_handle or artifact_storage_handle(normalized.artifact_id),
        "body_ref": artifact_body_ref(normalized),
        "structured_output_json": dict(normalized.structured_output_json or {}),
        "attachments_json": dict(normalized.attachments_json or {}),
        "execution_session_id": normalized.execution_session_id,
        "principal_id": normalized.principal_id,
    }


@router.post("/compile")
def compile_plan(
    body: PlanCompileIn,
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> PlanCompileOut:
    principal_id = resolve_principal_id(body.principal_id, context)
    resolved_task_key = _resolve_task_key(
        container,
        task_key=body.task_key,
        skill_key=body.skill_key,
    )
    try:
        intent, plan = container.planner.build_plan(
            task_key=resolved_task_key,
            principal_id=principal_id,
            goal=body.goal,
        )
    except PlanValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    skill_key = _resolve_skill_key(container, plan.task_key)
    return PlanCompileOut(
        skill_key=skill_key,
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
                    timeout_budget_seconds=s.timeout_budget_seconds,
                    max_attempts=s.max_attempts,
                    retry_backoff_seconds=s.retry_backoff_seconds,
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
    resolved_task_key = _resolve_task_key(
        container,
        task_key=body.task_key,
        skill_key=body.skill_key,
    )
    skill_key = _resolve_skill_key(container, resolved_task_key)
    try:
        artifact = container.orchestrator.execute_task_artifact(
            TaskExecutionRequest(
                task_key=resolved_task_key,
                text=str(body.text or ""),
                principal_id=principal_id,
                goal=body.goal,
                input_json=dict(body.input_json or {}),
                context_refs=tuple(str(value or "").strip() for value in (body.context_refs or []) if str(value or "").strip()),
            )
        )
    except PlanValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ApprovalRequiredError as exc:
        return JSONResponse(
            status_code=202,
            content=PlanExecuteAcceptedOut(
                skill_key=skill_key,
                task_key=resolved_task_key,
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
                skill_key=skill_key,
                task_key=resolved_task_key,
                session_id=exc.session_id,
                human_task_id=exc.human_task_id,
                status=exc.status,
                next_action="poll_or_subscribe",
            ).model_dump(),
        )
    except AsyncExecutionQueuedError as exc:
        return JSONResponse(
            status_code=202,
            content=PlanExecuteAcceptedOut(
                skill_key=skill_key,
                task_key=resolved_task_key,
                session_id=exc.session_id,
                status=exc.status,
                next_action="poll_or_subscribe",
            ).model_dump(),
        )
    except PolicyDeniedError as exc:
        reason = str(exc or "policy_denied")
        raise HTTPException(status_code=403, detail=f"policy_denied:{reason}") from exc
    return PlanExecuteOut(
        skill_key=skill_key,
        task_key=resolved_task_key,
        **_artifact_execute_out_payload(artifact),
        deliverable_type=artifact.kind,
    )
