from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.api.dependencies import RequestContext, get_container, get_request_context, resolve_principal_id
from app.container import AppContainer
from app.domain.models import ProviderBindingRecord, ProviderBindingState
from app.services.tool_execution_common import ToolExecutionError

router = APIRouter(prefix="/v1/providers", tags=["providers"])


class ProviderBindingIn(BaseModel):
    principal_id: str | None = Field(default=None, min_length=1, max_length=200)
    provider_key: str = Field(min_length=1, max_length=200)
    status: str = Field(default="enabled", max_length=50)
    priority: int = Field(default=100, ge=0, le=10000)
    scope_json: dict[str, object] = Field(default_factory=dict)
    auth_metadata_json: dict[str, object] = Field(default_factory=dict)
    probe_state: str = Field(default="unknown", max_length=50)
    probe_details_json: dict[str, object] = Field(default_factory=dict)


class ProviderBindingStatusIn(BaseModel):
    status: str = Field(min_length=1, max_length=50)


class ProviderBindingProbeIn(BaseModel):
    probe_state: str = Field(min_length=1, max_length=50)
    probe_details_json: dict[str, object] = Field(default_factory=dict)


class ProviderBindingOut(BaseModel):
    binding_id: str
    principal_id: str
    provider_key: str
    status: str
    priority: int
    probe_state: str
    probe_details_json: dict[str, object]
    scope_json: dict[str, object]
    auth_metadata_json: dict[str, object]
    created_at: str
    updated_at: str


class ProviderStateOut(BaseModel):
    provider_key: str
    display_name: str
    executable: bool
    enabled: bool
    status: str
    source: str
    auth_mode: str
    priority: int
    binding_id: str
    secret_env_names: list[str]
    secret_configured: bool
    capabilities: list[str]
    tool_names: list[str]
    state: str
    health_state: str
    health_details_json: dict[str, object]
    updated_at: str


def _binding_out(row: ProviderBindingRecord) -> ProviderBindingOut:
    return ProviderBindingOut(
        binding_id=row.binding_id,
        principal_id=row.principal_id,
        provider_key=row.provider_key,
        status=row.status,
        priority=row.priority,
        probe_state=row.probe_state,
        probe_details_json=dict(row.probe_details_json or {}),
        scope_json=dict(row.scope_json or {}),
        auth_metadata_json=dict(row.auth_metadata_json or {}),
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _state_out(row: ProviderBindingState) -> ProviderStateOut:
    return ProviderStateOut(
        provider_key=row.provider_key,
        display_name=row.display_name,
        executable=row.executable,
        enabled=row.enabled,
        status=row.status,
        source=row.source,
        auth_mode=row.auth_mode,
        priority=row.priority,
        binding_id=row.binding_id,
        secret_env_names=list(row.secret_env_names),
        secret_configured=row.secret_configured,
        capabilities=list(row.capabilities),
        tool_names=list(row.tool_names),
        state=row.state,
        health_state=row.health_state,
        health_details_json=dict(row.health_details_json or {}),
        updated_at=row.updated_at,
    )


@router.post("/bindings")
def upsert_provider_binding(
    body: ProviderBindingIn,
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> ProviderBindingOut:
    principal_id = resolve_principal_id(body.principal_id, context)
    try:
        row = container.provider_registry.upsert_binding_record(
            principal_id=principal_id,
            provider_key=body.provider_key,
            status=body.status,
            priority=body.priority,
            scope_json=body.scope_json,
            auth_metadata_json=body.auth_metadata_json,
            probe_state=body.probe_state,
            probe_details_json=body.probe_details_json,
        )
    except ToolExecutionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _binding_out(row)


@router.get("/bindings")
def list_provider_bindings(
    principal_id: str | None = Query(default=None, min_length=1),
    limit: int = Query(default=100, ge=1, le=500),
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> list[ProviderBindingOut]:
    resolved_principal = resolve_principal_id(principal_id, context)
    rows = container.provider_registry.list_persisted_binding_records(principal_id=resolved_principal, limit=limit)
    return [_binding_out(row) for row in rows]


@router.get("/bindings/{binding_id}")
def get_provider_binding(
    binding_id: str,
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> ProviderBindingOut:
    row = container.provider_registry.get_persisted_binding_record(
        binding_id=binding_id,
        principal_id=context.principal_id,
    )
    if row is None:
        raise HTTPException(status_code=404, detail="provider_binding_not_found")
    return _binding_out(row)


@router.post("/bindings/{binding_id}/status")
def set_provider_binding_status(
    binding_id: str,
    body: ProviderBindingStatusIn,
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> ProviderBindingOut:
    row = container.provider_registry.set_persisted_binding_status(
        binding_id=binding_id,
        status=body.status,
        principal_id=context.principal_id,
    )
    if row is None:
        raise HTTPException(status_code=404, detail="provider_binding_not_found")
    return _binding_out(row)


@router.post("/bindings/{binding_id}/probe")
def set_provider_binding_probe(
    binding_id: str,
    body: ProviderBindingProbeIn,
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> ProviderBindingOut:
    row = container.provider_registry.set_persisted_binding_probe(
        binding_id=binding_id,
        probe_state=body.probe_state,
        probe_details_json=body.probe_details_json,
        principal_id=context.principal_id,
    )
    if row is None:
        raise HTTPException(status_code=404, detail="provider_binding_not_found")
    return _binding_out(row)


@router.get("/states")
def list_provider_states(
    principal_id: str | None = Query(default=None, min_length=1),
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> list[ProviderStateOut]:
    resolved_principal = resolve_principal_id(principal_id, context)
    rows = container.provider_registry.list_binding_states(principal_id=resolved_principal)
    return [_state_out(row) for row in rows]


@router.get("/states/{provider_key}")
def get_provider_state(
    provider_key: str,
    principal_id: str | None = Query(default=None, min_length=1),
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> ProviderStateOut:
    resolved_principal = resolve_principal_id(principal_id, context)
    row = container.provider_registry.binding_state(provider_key, principal_id=resolved_principal)
    if row is None:
        raise HTTPException(status_code=404, detail="provider_not_found")
    return _state_out(row)
