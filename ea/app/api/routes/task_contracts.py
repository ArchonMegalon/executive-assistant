from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.api.dependencies import get_container, require_operator_context
from app.container import AppContainer

router = APIRouter(prefix="/v1/tasks/contracts", tags=["task-contracts"], dependencies=[Depends(require_operator_context)])


class TaskContractIn(BaseModel):
    task_key: str = Field(min_length=1, max_length=200)
    deliverable_type: str = Field(min_length=1, max_length=200)
    default_risk_class: str = Field(default="low", max_length=100)
    default_approval_class: str = Field(default="none", max_length=100)
    allowed_tools: list[str] = Field(default_factory=list)
    evidence_requirements: list[str] = Field(default_factory=list)
    memory_write_policy: str = Field(default="reviewed_only", max_length=100)
    budget_policy_json: dict[str, object] = Field(default_factory=dict)
    runtime_policy_json: dict[str, object] = Field(default_factory=dict)


class TaskContractOut(BaseModel):
    task_key: str
    deliverable_type: str
    default_risk_class: str
    default_approval_class: str
    allowed_tools: list[str]
    evidence_requirements: list[str]
    memory_write_policy: str
    budget_policy_json: dict[str, object]
    runtime_policy_json: dict[str, object]
    updated_at: str


@router.post("")
def upsert_task_contract(
    body: TaskContractIn,
    container: AppContainer = Depends(get_container),
) -> TaskContractOut:
    row = container.task_contracts.upsert_contract(
        task_key=body.task_key,
        deliverable_type=body.deliverable_type,
        default_risk_class=body.default_risk_class,
        default_approval_class=body.default_approval_class,
        allowed_tools=tuple(body.allowed_tools),
        evidence_requirements=tuple(body.evidence_requirements),
        memory_write_policy=body.memory_write_policy,
        budget_policy_json=body.budget_policy_json,
        runtime_policy_json=body.runtime_policy_json,
    )
    return TaskContractOut(
        task_key=row.task_key,
        deliverable_type=row.deliverable_type,
        default_risk_class=row.default_risk_class,
        default_approval_class=row.default_approval_class,
        allowed_tools=list(row.allowed_tools),
        evidence_requirements=list(row.evidence_requirements),
        memory_write_policy=row.memory_write_policy,
        budget_policy_json=row.budget_policy_json,
        runtime_policy_json=row.runtime_policy_json,
        updated_at=row.updated_at,
    )


@router.get("")
def list_task_contracts(
    limit: int = Query(default=100, ge=1, le=500),
    container: AppContainer = Depends(get_container),
) -> list[TaskContractOut]:
    rows = container.task_contracts.list_contracts(limit=limit)
    return [
        TaskContractOut(
            task_key=r.task_key,
            deliverable_type=r.deliverable_type,
            default_risk_class=r.default_risk_class,
            default_approval_class=r.default_approval_class,
            allowed_tools=list(r.allowed_tools),
            evidence_requirements=list(r.evidence_requirements),
            memory_write_policy=r.memory_write_policy,
            budget_policy_json=r.budget_policy_json,
            runtime_policy_json=r.runtime_policy_json,
            updated_at=r.updated_at,
        )
        for r in rows
    ]


@router.get("/{task_key}")
def get_task_contract(
    task_key: str,
    container: AppContainer = Depends(get_container),
) -> TaskContractOut:
    row = container.task_contracts.get_contract(task_key)
    if not row:
        raise HTTPException(status_code=404, detail="task_contract_not_found")
    return TaskContractOut(
        task_key=row.task_key,
        deliverable_type=row.deliverable_type,
        default_risk_class=row.default_risk_class,
        default_approval_class=row.default_approval_class,
        allowed_tools=list(row.allowed_tools),
        evidence_requirements=list(row.evidence_requirements),
        memory_write_policy=row.memory_write_policy,
        budget_policy_json=row.budget_policy_json,
        runtime_policy_json=row.runtime_policy_json,
        updated_at=row.updated_at,
    )
