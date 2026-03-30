from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request

from app.api.dependencies import RequestContext, get_container, get_request_context
from app.api.routes.product_api_contracts import (
    OperatorCenterActionOut,
    OperatorCenterLaneOut,
    OperatorCenterOut,
    WorkspaceDiagnosticsOut,
    WorkspaceMorningMemoSettingsIn,
    WorkspaceOutcomesOut,
    WorkspacePlanDetailOut,
    WorkspaceSupportBundleOut,
    WorkspaceTrustOut,
    WorkspaceUsageDetailOut,
)
from app.container import AppContainer
from app.product.service import build_product_service

router = APIRouter(prefix="/app/api", tags=["product"])


@router.post("/settings/morning-memo", response_model=WorkspaceDiagnosticsOut)
def update_workspace_morning_memo_settings(
    body: WorkspaceMorningMemoSettingsIn,
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> WorkspaceDiagnosticsOut:
    status = container.onboarding.status(principal_id=context.principal_id)
    workspace = dict(status.get("workspace") or {})
    container.onboarding.start_workspace(
        principal_id=context.principal_id,
        workspace_name=str(body.workspace_name or workspace.get("name") or "Executive Workspace").strip() or "Executive Workspace",
        workspace_mode=str(workspace.get("mode") or "personal"),
        region=str(workspace.get("region") or ""),
        language=str(body.language or workspace.get("language") or "en").strip() or "en",
        timezone=str(body.timezone or workspace.get("timezone") or "Europe/Vienna").strip() or "Europe/Vienna",
        selected_channels=tuple(str(value) for value in (status.get("selected_channels") or []) if str(value).strip()),
    )
    refreshed = container.onboarding.status(principal_id=context.principal_id)
    privacy = dict(refreshed.get("privacy") or {})
    morning_memo = dict(dict(refreshed.get("delivery_preferences") or {}).get("morning_memo") or {})
    container.onboarding.finalize(
        principal_id=context.principal_id,
        retention_mode=str(privacy.get("retention_mode") or "full_bodies"),
        metadata_only_channels=tuple(str(value) for value in (privacy.get("metadata_only_channels") or []) if str(value).strip()),
        allow_drafts=bool(privacy.get("allow_drafts")),
        allow_action_suggestions=bool(privacy.get("allow_action_suggestions", True)),
        allow_auto_briefs=body.enabled,
        auto_brief_cadence=str(body.cadence or morning_memo.get("cadence") or "daily_morning").strip() or "daily_morning",
        auto_brief_delivery_time_local=str(body.delivery_time_local or morning_memo.get("delivery_time_local") or "08:00").strip() or "08:00",
        auto_brief_quiet_hours_start=str(body.quiet_hours_start or morning_memo.get("quiet_hours_start") or "20:00").strip() or "20:00",
        auto_brief_quiet_hours_end=str(body.quiet_hours_end or morning_memo.get("quiet_hours_end") or "07:00").strip() or "07:00",
        auto_brief_recipient_email=str(body.recipient_email or morning_memo.get("recipient_email") or "").strip(),
        auto_brief_delivery_channel=str(morning_memo.get("delivery_channel") or "email"),
    )
    service = build_product_service(container)
    service.record_surface_event(
        principal_id=context.principal_id,
        event_type="settings_updated",
        surface="settings_api",
        actor=str(context.operator_id or context.access_email or context.principal_id or "browser").strip(),
    )
    return WorkspaceDiagnosticsOut(**service.workspace_diagnostics(principal_id=context.principal_id))


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
        operator_memo_grounding=dict(payload.get("operator_memo_grounding") or {}) or None,
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


@router.post("/support/fix-verification/request", response_model=WorkspaceSupportBundleOut)
def request_support_fix_verification(
    request: Request,
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> WorkspaceSupportBundleOut:
    service = build_product_service(container)
    actor = str(context.operator_id or context.access_email or context.principal_id or "support").strip()
    try:
        service.request_support_fix_verification(
            principal_id=context.principal_id,
            actor=actor,
            base_url=str(request.base_url),
        )
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return WorkspaceSupportBundleOut(**service.workspace_support_bundle(principal_id=context.principal_id))
