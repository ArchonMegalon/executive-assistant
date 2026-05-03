from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Body, Depends, HTTPException
from pydantic import BaseModel, Field

from app.api.dependencies import RequestContext, get_container, get_request_context, require_operator_context
from app.container import AppContainer
from app.domain.models import ToolInvocationRequest
from app.services.ltd_runtime_catalog import LtdRuntimeAction, LtdRuntimeCatalogService
from app.services.ltd_runtime_skill_projection import infer_onemin_media_feature_type
from app.services.tool_execution import ToolExecutionError

router = APIRouter(
    prefix="/v1/ltds/runtime-catalog",
    tags=["ltd-runtime"],
    dependencies=[Depends(require_operator_context)],
)
log = logging.getLogger("ea.api.ltd_runtime")


class LtdDiscoverAccountIn(BaseModel):
    binding_id: str = Field(min_length=1, max_length=200)
    requested_fields: list[str] = Field(default_factory=list)
    instructions: str = Field(default="", max_length=4000)
    run_url: str = Field(default="", max_length=4000)


class LtdActionExecutionOut(BaseModel):
    service_name: str
    action_key: str
    tool_name: str
    action_kind: str
    target_ref: str
    output_json: dict[str, object]
    receipt_json: dict[str, object]


def _catalog(container: AppContainer) -> LtdRuntimeCatalogService:
    return LtdRuntimeCatalogService(provider_registry=container.provider_registry)


def _http_status_for_tool_error(detail: str) -> int:
    if detail.startswith("tool_not_registered:") or detail.startswith("connector_binding_not_found:"):
        return 404
    if detail == "principal_scope_mismatch" or detail.startswith("connector_binding_scope_mismatch:"):
        return 403
    if (
        detail.startswith("connector_binding_required:")
        or detail in {"tool_name_required", "principal_id_required", "connector_dispatch_channel_required"}
        or detail.startswith("run_url_or_workflow_id_required:")
        or detail.startswith("prompt_required:")
    ):
        return 400
    return 409


def _resolved_action_or_404(
    *,
    container: AppContainer,
    service_name: str,
    action_key: str,
) -> tuple[str, LtdRuntimeAction]:
    catalog = _catalog(container)
    profile = catalog.get_profile(service_name)
    if profile is None:
        raise HTTPException(status_code=404, detail="ltd_service_not_found")
    action = catalog.get_action(profile.service_name, action_key)
    if action is None:
        raise HTTPException(status_code=404, detail="ltd_runtime_action_not_found")
    return profile.service_name, action


def _execute_catalog_action(
    *,
    container: AppContainer,
    context: RequestContext,
    service_name: str,
    action: LtdRuntimeAction,
    payload_json: dict[str, object],
) -> LtdActionExecutionOut:
    if not action.executable or action.execution_mode != "tool_execution":
        raise HTTPException(status_code=409, detail="ltd_runtime_action_not_executable")
    payload = dict(payload_json or {})
    payload.setdefault("action_key", action.action_key)
    if action.action_key == "discover_account":
        payload["service_name"] = service_name
    if action.tool_name == "provider.onemin.media_transform" and not str(payload.get("feature_type") or "").strip():
        inferred_feature_type = infer_onemin_media_feature_type(input_json=payload)
        if inferred_feature_type:
            payload["feature_type"] = inferred_feature_type
    invocation = ToolInvocationRequest(
        session_id=f"ltd-runtime:{uuid.uuid4()}",
        step_id=f"ltd-runtime-step:{uuid.uuid4()}",
        tool_name=action.tool_name,
        action_kind=action.action_kind,
        payload_json=payload,
        context_json={"principal_id": context.principal_id},
    )
    try:
        result = container.tool_execution.execute_invocation(invocation)
    except ToolExecutionError as exc:
        detail = str(exc or "tool_execution_failed")
        log.warning(
            "ltd_runtime_action_failed service=%s action=%s principal=%s detail=%s",
            service_name,
            action.action_key,
            context.principal_id,
            detail,
        )
        raise HTTPException(status_code=_http_status_for_tool_error(detail), detail=detail) from exc
    return LtdActionExecutionOut(
        service_name=service_name,
        action_key=action.action_key,
        tool_name=result.tool_name,
        action_kind=result.action_kind,
        target_ref=result.target_ref,
        output_json=dict(result.output_json or {}),
        receipt_json=dict(result.receipt_json or {}),
    )


@router.get("")
def list_runtime_catalog(
    container: AppContainer = Depends(get_container),
) -> list[dict[str, object]]:
    return [profile.as_dict() for profile in _catalog(container).list_profiles()]


@router.get("/{service_name}")
def get_runtime_profile(
    service_name: str,
    container: AppContainer = Depends(get_container),
) -> dict[str, object]:
    profile = _catalog(container).get_profile(service_name)
    if profile is None:
        raise HTTPException(status_code=404, detail="ltd_service_not_found")
    return profile.as_dict()


@router.post("/{service_name}/discover-account")
def discover_account(
    service_name: str,
    body: LtdDiscoverAccountIn,
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> LtdActionExecutionOut:
    resolved_service_name, action = _resolved_action_or_404(
        container=container,
        service_name=service_name,
        action_key="discover_account",
    )
    payload_json: dict[str, object] = {
        "binding_id": body.binding_id,
        "requested_fields": list(body.requested_fields or []),
    }
    if str(body.instructions or "").strip():
        payload_json["instructions"] = body.instructions
    if str(body.run_url or "").strip():
        payload_json["run_url"] = body.run_url
    return _execute_catalog_action(
        container=container,
        context=context,
        service_name=resolved_service_name,
        action=action,
        payload_json=payload_json,
    )


@router.post("/{service_name}/inspect-workspace")
def inspect_workspace(
    service_name: str,
    body: dict[str, object] = Body(default_factory=dict),
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> LtdActionExecutionOut:
    resolved_service_name, action = _resolved_action_or_404(
        container=container,
        service_name=service_name,
        action_key="inspect_workspace",
    )
    return _execute_catalog_action(
        container=container,
        context=context,
        service_name=resolved_service_name,
        action=action,
        payload_json=body,
    )


@router.post("/{service_name}/actions/{action_key}")
def execute_action(
    service_name: str,
    action_key: str,
    body: dict[str, object] = Body(default_factory=dict),
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> LtdActionExecutionOut:
    resolved_service_name, action = _resolved_action_or_404(
        container=container,
        service_name=service_name,
        action_key=action_key,
    )
    return _execute_catalog_action(
        container=container,
        context=context,
        service_name=resolved_service_name,
        action=action,
        payload_json=body,
    )
