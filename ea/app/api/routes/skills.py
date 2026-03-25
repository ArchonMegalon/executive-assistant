from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.api.dependencies import get_container, require_operator_context
from app.container import AppContainer

router = APIRouter(prefix="/v1/skills", tags=["skills"], dependencies=[Depends(require_operator_context)])


class SkillIn(BaseModel):
    skill_key: str = Field(min_length=1, max_length=200)
    task_key: str = Field(default="", max_length=200)
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=2000)
    deliverable_type: str = Field(min_length=1, max_length=200)
    default_risk_class: str = Field(default="low", max_length=100)
    default_approval_class: str = Field(default="none", max_length=100)
    workflow_template: str = Field(default="rewrite", max_length=200)
    allowed_tools: list[str] = Field(default_factory=list)
    evidence_requirements: list[str] = Field(default_factory=list)
    memory_write_policy: str = Field(default="reviewed_only", max_length=100)
    memory_reads: list[str] = Field(default_factory=list)
    memory_writes: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    input_schema_json: dict[str, object] = Field(default_factory=dict)
    output_schema_json: dict[str, object] = Field(default_factory=dict)
    authority_profile_json: dict[str, object] = Field(default_factory=dict)
    model_policy_json: dict[str, object] = Field(default_factory=dict)
    provider_hints_json: dict[str, object] = Field(default_factory=dict)
    tool_policy_json: dict[str, object] = Field(default_factory=dict)
    human_policy_json: dict[str, object] = Field(default_factory=dict)
    evaluation_cases_json: list[dict[str, object]] = Field(default_factory=list)
    budget_policy_json: dict[str, object] = Field(default_factory=dict)
    runtime_policy_json: dict[str, object] = Field(default_factory=dict)


class SkillOut(BaseModel):
    skill_key: str
    task_key: str
    name: str
    description: str
    deliverable_type: str
    default_risk_class: str
    default_approval_class: str
    workflow_template: str
    allowed_tools: list[str]
    evidence_requirements: list[str]
    memory_write_policy: str
    memory_reads: list[str]
    memory_writes: list[str]
    tags: list[str]
    input_schema_json: dict[str, object]
    output_schema_json: dict[str, object]
    authority_profile_json: dict[str, object]
    model_policy_json: dict[str, object]
    provider_hints_json: dict[str, object]
    tool_policy_json: dict[str, object]
    human_policy_json: dict[str, object]
    evaluation_cases_json: list[dict[str, object]]
    updated_at: str


def _to_out(row) -> SkillOut:
    return SkillOut(
        skill_key=row.skill_key,
        task_key=row.task_key,
        name=row.name,
        description=row.description,
        deliverable_type=row.deliverable_type,
        default_risk_class=row.default_risk_class,
        default_approval_class=row.default_approval_class,
        workflow_template=row.workflow_template,
        allowed_tools=list(row.allowed_tools),
        evidence_requirements=list(row.evidence_requirements),
        memory_write_policy=row.memory_write_policy,
        memory_reads=list(row.memory_reads),
        memory_writes=list(row.memory_writes),
        tags=list(row.tags),
        input_schema_json=dict(row.input_schema_json),
        output_schema_json=dict(row.output_schema_json),
        authority_profile_json=dict(row.authority_profile_json),
        model_policy_json=dict(row.model_policy_json),
        provider_hints_json=dict(row.provider_hints_json),
        tool_policy_json=dict(row.tool_policy_json),
        human_policy_json=dict(row.human_policy_json),
        evaluation_cases_json=[dict(value) for value in row.evaluation_cases_json],
        updated_at=row.updated_at,
    )


@router.post("")
def upsert_skill(
    body: SkillIn,
    container: AppContainer = Depends(get_container),
) -> SkillOut:
    row = container.skills.upsert_skill(
        skill_key=body.skill_key,
        task_key=body.task_key,
        name=body.name,
        description=body.description,
        deliverable_type=body.deliverable_type,
        default_risk_class=body.default_risk_class,
        default_approval_class=body.default_approval_class,
        workflow_template=body.workflow_template,
        allowed_tools=tuple(body.allowed_tools),
        evidence_requirements=tuple(body.evidence_requirements),
        memory_write_policy=body.memory_write_policy,
        memory_reads=tuple(body.memory_reads),
        memory_writes=tuple(body.memory_writes),
        tags=tuple(body.tags),
        input_schema_json=body.input_schema_json,
        output_schema_json=body.output_schema_json,
        authority_profile_json=body.authority_profile_json,
        model_policy_json=body.model_policy_json,
        provider_hints_json=body.provider_hints_json,
        tool_policy_json=body.tool_policy_json,
        human_policy_json=body.human_policy_json,
        evaluation_cases_json=tuple(body.evaluation_cases_json),
        budget_policy_json=body.budget_policy_json,
        runtime_policy_json=body.runtime_policy_json,
        provided_fields=set(getattr(body, "model_fields_set", set())),
    )
    return _to_out(row)


@router.get("")
def list_skills(
    limit: int = Query(default=100, ge=1, le=500),
    provider_hint: str = Query(default="", max_length=200),
    container: AppContainer = Depends(get_container),
) -> list[SkillOut]:
    return [_to_out(row) for row in container.skills.list_skills(limit=limit, provider_hint=provider_hint)]


@router.get("/{skill_key}")
def get_skill(
    skill_key: str,
    container: AppContainer = Depends(get_container),
) -> SkillOut:
    row = container.skills.get_skill(skill_key)
    if row is None:
        raise HTTPException(status_code=404, detail="skill_not_found")
    return _to_out(row)
