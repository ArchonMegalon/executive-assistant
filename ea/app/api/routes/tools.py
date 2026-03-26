from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.api.dependencies import RequestContext, get_container, get_request_context, require_operator_context
from app.container import AppContainer
from app.domain.models import ToolInvocationRequest
from app.services.tool_execution import ToolExecutionError

router = APIRouter(prefix="/v1/tools", tags=["tools"])
log = logging.getLogger("ea.api.tools")


class ToolIn(BaseModel):
    tool_name: str = Field(min_length=1, max_length=200)
    version: str = Field(default="v1", max_length=100)
    input_schema_json: dict[str, object] = Field(default_factory=dict)
    output_schema_json: dict[str, object] = Field(default_factory=dict)
    policy_json: dict[str, object] = Field(default_factory=dict)
    allowed_channels: list[str] = Field(default_factory=list)
    approval_default: str = Field(default="none", max_length=100)
    enabled: bool = True


class ToolOut(BaseModel):
    tool_name: str
    version: str
    input_schema_json: dict[str, object]
    output_schema_json: dict[str, object]
    policy_json: dict[str, object]
    allowed_channels: list[str]
    approval_default: str
    enabled: bool
    updated_at: str


class ToolExecuteIn(BaseModel):
    tool_name: str = Field(min_length=1, max_length=200)
    action_kind: str = Field(default="", max_length=200)
    payload_json: dict[str, object] = Field(default_factory=dict)


class ToolExecutionOut(BaseModel):
    tool_name: str
    action_kind: str
    target_ref: str
    output_json: dict[str, object]
    receipt_json: dict[str, object]


@router.post("/registry", dependencies=[Depends(require_operator_context)])
def upsert_tool(
    body: ToolIn,
    container: AppContainer = Depends(get_container),
) -> ToolOut:
    row = container.tool_runtime.upsert_tool(
        tool_name=body.tool_name,
        version=body.version,
        input_schema_json=body.input_schema_json,
        output_schema_json=body.output_schema_json,
        policy_json=body.policy_json,
        allowed_channels=tuple(body.allowed_channels),
        approval_default=body.approval_default,
        enabled=body.enabled,
    )
    return ToolOut(
        tool_name=row.tool_name,
        version=row.version,
        input_schema_json=row.input_schema_json,
        output_schema_json=row.output_schema_json,
        policy_json=row.policy_json,
        allowed_channels=list(row.allowed_channels),
        approval_default=row.approval_default,
        enabled=row.enabled,
        updated_at=row.updated_at,
    )


@router.get("/registry", dependencies=[Depends(require_operator_context)])
def list_enabled_tools(
    limit: int = Query(default=100, ge=1, le=500),
    container: AppContainer = Depends(get_container),
) -> list[ToolOut]:
    rows = container.tool_runtime.list_enabled_tools(limit=limit)
    return [
        ToolOut(
            tool_name=r.tool_name,
            version=r.version,
            input_schema_json=r.input_schema_json,
            output_schema_json=r.output_schema_json,
            policy_json=r.policy_json,
            allowed_channels=list(r.allowed_channels),
            approval_default=r.approval_default,
            enabled=r.enabled,
            updated_at=r.updated_at,
        )
        for r in rows
    ]


@router.get("/registry/{tool_name}", dependencies=[Depends(require_operator_context)])
def get_tool(
    tool_name: str,
    container: AppContainer = Depends(get_container),
) -> ToolOut:
    row = container.tool_runtime.get_tool(tool_name)
    if not row:
        raise HTTPException(status_code=404, detail="tool_not_found")
    return ToolOut(
        tool_name=row.tool_name,
        version=row.version,
        input_schema_json=row.input_schema_json,
        output_schema_json=row.output_schema_json,
        policy_json=row.policy_json,
        allowed_channels=list(row.allowed_channels),
        approval_default=row.approval_default,
        enabled=row.enabled,
        updated_at=row.updated_at,
    )


@router.post("/execute", dependencies=[Depends(require_operator_context)])
def execute_tool(
    body: ToolExecuteIn,
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> ToolExecutionOut:
    invocation = ToolInvocationRequest(
        session_id=f"direct-tool:{uuid.uuid4()}",
        step_id=f"direct-step:{uuid.uuid4()}",
        tool_name=body.tool_name,
        action_kind=body.action_kind,
        payload_json=body.payload_json,
        context_json={"principal_id": context.principal_id},
    )
    try:
        result = container.tool_execution.execute_invocation(invocation)
    except ToolExecutionError as exc:
        detail = str(exc or "tool_execution_failed")
        log.warning(
            "tool_execution_failed tool=%s principal=%s detail=%s",
            body.tool_name,
            context.principal_id,
            detail,
        )
        if detail.startswith("tool_not_registered:") or detail.startswith("connector_binding_not_found:"):
            status_code = 404
        elif detail == "principal_scope_mismatch" or detail.startswith("connector_binding_scope_mismatch:"):
            status_code = 403
        elif (
            detail.startswith("connector_binding_required:")
            or detail in {"tool_name_required", "principal_id_required", "connector_dispatch_channel_required"}
        ):
            status_code = 400
        else:
            status_code = 409
        raise HTTPException(status_code=status_code, detail=detail) from exc
    return ToolExecutionOut(
        tool_name=result.tool_name,
        action_kind=result.action_kind,
        target_ref=result.target_ref,
        output_json=result.output_json,
        receipt_json=result.receipt_json,
    )
