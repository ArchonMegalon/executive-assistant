from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.dependencies import RequestContext, get_container, get_request_context
from app.api.routes.product_api_contracts import (
    OperatorCenterActionOut,
    OperatorCenterLaneOut,
    OperatorCenterOut,
    WorkspaceDiagnosticsOut,
    WorkspaceOutcomesOut,
    WorkspacePlanDetailOut,
    WorkspaceSupportBundleOut,
    WorkspaceTrustOut,
    WorkspaceUsageDetailOut,
)
from app.container import AppContainer
from app.product.service import build_product_service

router = APIRouter(prefix="/app/api", tags=["product"])


@router.get("/diagnostics", response_model=WorkspaceDiagnosticsOut)
def get_workspace_diagnostics(
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> WorkspaceDiagnosticsOut:
    service = build_product_service(container)
    return WorkspaceDiagnosticsOut(**service.workspace_diagnostics(principal_id=context.principal_id))


@router.get("/operator-center", response_model=OperatorCenterOut)
def get_operator_center(
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> OperatorCenterOut:
    service = build_product_service(container)
    payload = service.operator_center(
        principal_id=context.principal_id,
        operator_id=str(context.operator_id or "").strip(),
    )
    return OperatorCenterOut(
        generated_at=str(payload.get("generated_at") or ""),
        workspace=dict(payload.get("workspace") or {}),
        operators=dict(payload.get("operators") or {}),
        queue_health=dict(payload.get("queue_health") or {}),
        providers=dict(payload.get("providers") or {}),
        readiness=dict(payload.get("readiness") or {}),
        delivery=dict(payload.get("delivery") or {}),
        access=dict(payload.get("access") or {}),
        sync=dict(payload.get("sync") or {}),
        usage={str(key): int(value or 0) for key, value in dict(payload.get("usage") or {}).items()},
        lanes=[OperatorCenterLaneOut(**dict(value)) for value in list(payload.get("lanes") or [])],
        next_actions=[OperatorCenterActionOut(**dict(value)) for value in list(payload.get("next_actions") or [])],
        recent_runtime=[dict(value) for value in list(payload.get("recent_runtime") or [])],
        snapshot={str(key): int(value or 0) for key, value in dict(payload.get("snapshot") or {}).items()},
    )


@router.get("/plan", response_model=WorkspacePlanDetailOut)
def get_workspace_plan_detail(
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> WorkspacePlanDetailOut:
    service = build_product_service(container)
    diagnostics = service.workspace_diagnostics(principal_id=context.principal_id)
    service.record_surface_event(
        principal_id=context.principal_id,
        event_type="plan_opened",
        surface="plan_api",
        actor=str(context.operator_id or context.access_email or context.principal_id or "browser").strip(),
    )
    return WorkspacePlanDetailOut(
        workspace=dict(diagnostics.get("workspace") or {}),
        selected_channels=[str(value) for value in (diagnostics.get("selected_channels") or []) if str(value).strip()],
        plan=dict(diagnostics.get("plan") or {}),
        billing=dict(diagnostics.get("billing") or {}),
        entitlements=dict(diagnostics.get("entitlements") or {}),
        commercial=dict(diagnostics.get("commercial") or {}),
        operators=dict(diagnostics.get("operators") or {}),
    )


@router.get("/usage", response_model=WorkspaceUsageDetailOut)
def get_workspace_usage_detail(
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> WorkspaceUsageDetailOut:
    service = build_product_service(container)
    service.record_surface_event(
        principal_id=context.principal_id,
        event_type="usage_opened",
        surface="usage_api",
        actor=str(context.operator_id or context.access_email or context.principal_id or "browser").strip(),
    )
    diagnostics = service.workspace_diagnostics(principal_id=context.principal_id)
    return WorkspaceUsageDetailOut(
        workspace=dict(diagnostics.get("workspace") or {}),
        selected_channels=[str(value) for value in (diagnostics.get("selected_channels") or []) if str(value).strip()],
        usage={str(key): int(value or 0) for key, value in dict(diagnostics.get("usage") or {}).items()},
        analytics=dict(diagnostics.get("analytics") or {}),
        readiness=dict(diagnostics.get("readiness") or {}),
        operators=dict(diagnostics.get("operators") or {}),
    )


@router.get("/outcomes", response_model=WorkspaceOutcomesOut)
def get_workspace_outcomes(
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> WorkspaceOutcomesOut:
    service = build_product_service(container)
    service.record_surface_event(
        principal_id=context.principal_id,
        event_type="outcomes_opened",
        surface="outcomes_api",
        actor=str(context.operator_id or context.access_email or context.principal_id or "browser").strip(),
    )
    return WorkspaceOutcomesOut(**service.workspace_outcomes(principal_id=context.principal_id))


@router.get("/trust", response_model=WorkspaceTrustOut)
def get_workspace_trust(
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> WorkspaceTrustOut:
    service = build_product_service(container)
    service.record_surface_event(
        principal_id=context.principal_id,
        event_type="trust_opened",
        surface="trust_api",
        actor=str(context.operator_id or context.access_email or context.principal_id or "browser").strip(),
    )
    return WorkspaceTrustOut(**service.workspace_trust_summary(principal_id=context.principal_id))


@router.get("/diagnostics/export", response_model=WorkspaceSupportBundleOut)
def export_workspace_support_bundle(
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> WorkspaceSupportBundleOut:
    service = build_product_service(container)
    service.record_surface_event(
        principal_id=context.principal_id,
        event_type="support_bundle_opened",
        surface="diagnostics_export",
        actor=str(context.operator_id or context.access_email or context.principal_id or "browser").strip(),
    )
    return WorkspaceSupportBundleOut(**service.workspace_support_bundle(principal_id=context.principal_id))


@router.get("/support", response_model=WorkspaceSupportBundleOut)
def get_workspace_support_detail(
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> WorkspaceSupportBundleOut:
    service = build_product_service(container)
    service.record_surface_event(
        principal_id=context.principal_id,
        event_type="support_opened",
        surface="support_api",
        actor=str(context.operator_id or context.access_email or context.principal_id or "browser").strip(),
    )
    return WorkspaceSupportBundleOut(**service.workspace_support_bundle(principal_id=context.principal_id))
