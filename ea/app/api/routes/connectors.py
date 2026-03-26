from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.api.dependencies import RequestContext, get_container, get_request_context, is_operator_context, resolve_principal_id
from app.container import AppContainer

router = APIRouter(prefix="/v1/connectors", tags=["connectors"])


class ConnectorBindingIn(BaseModel):
    principal_id: str | None = Field(default=None, min_length=1, max_length=200)
    connector_name: str = Field(min_length=1, max_length=100)
    external_account_ref: str = Field(min_length=1, max_length=200)
    scope_json: dict[str, object] = Field(default_factory=dict)
    auth_metadata_json: dict[str, object] = Field(default_factory=dict)
    status: str = Field(default="enabled", max_length=50)


class ConnectorStatusIn(BaseModel):
    status: str = Field(min_length=1, max_length=50)


class ConnectorBindingOut(BaseModel):
    binding_id: str
    principal_id: str
    connector_name: str
    external_account_ref: str
    scope_json: dict[str, object]
    auth_metadata_json: dict[str, object]
    status: str
    created_at: str
    updated_at: str


def _redacted_auth_metadata(auth_metadata_json: dict[str, object] | None) -> dict[str, object]:
    payload = dict(auth_metadata_json or {})
    return {
        "redacted": bool(payload),
        "field_count": len(payload),
    }


def _is_browseract_connector(connector_name: str) -> bool:
    return str(connector_name or "").strip().lower() == "browseract"


def _resolve_binding_principal(requested_principal_id: str | None, context: RequestContext) -> str:
    requested = str(requested_principal_id or "").strip()
    if is_operator_context(context):
        return requested or context.principal_id
    return resolve_principal_id(requested_principal_id, context)


@router.post("/bindings")
def upsert_binding(
    body: ConnectorBindingIn,
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> ConnectorBindingOut:
    connector_name = str(body.connector_name or "").strip()
    operator_allowed = is_operator_context(context)
    if _is_browseract_connector(connector_name) and not operator_allowed:
        raise HTTPException(status_code=403, detail="connector_operator_scope_required")
    auth_metadata_json = dict(body.auth_metadata_json or {})
    if _is_browseract_connector(connector_name):
        auth_metadata_json["trusted_onemin_mapping"] = True
    row = container.tool_runtime.upsert_connector_binding(
        principal_id=_resolve_binding_principal(body.principal_id, context),
        connector_name=connector_name,
        external_account_ref=body.external_account_ref,
        scope_json=body.scope_json,
        auth_metadata_json=auth_metadata_json,
        status=body.status,
    )
    return ConnectorBindingOut(
        binding_id=row.binding_id,
        principal_id=row.principal_id,
        connector_name=row.connector_name,
        external_account_ref=row.external_account_ref,
        scope_json=row.scope_json,
        auth_metadata_json=_redacted_auth_metadata(row.auth_metadata_json),
        status=row.status,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


@router.get("/bindings")
def list_bindings(
    principal_id: str | None = Query(default=None, min_length=1),
    limit: int = Query(default=100, ge=1, le=500),
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> list[ConnectorBindingOut]:
    operator_allowed = is_operator_context(context)
    rows = container.tool_runtime.list_connector_bindings(
        principal_id=_resolve_binding_principal(principal_id, context),
        limit=limit,
    )
    if not operator_allowed:
        rows = [row for row in rows if not _is_browseract_connector(row.connector_name)]
    return [
        ConnectorBindingOut(
            binding_id=r.binding_id,
            principal_id=r.principal_id,
            connector_name=r.connector_name,
            external_account_ref=r.external_account_ref,
            scope_json=r.scope_json,
            auth_metadata_json=_redacted_auth_metadata(r.auth_metadata_json),
            status=r.status,
            created_at=r.created_at,
            updated_at=r.updated_at,
        )
        for r in rows
    ]


@router.post("/bindings/{binding_id}/status")
def set_binding_status(
    binding_id: str,
    body: ConnectorStatusIn,
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> ConnectorBindingOut:
    operator_allowed = is_operator_context(context)
    existing = container.tool_runtime.get_connector_binding(binding_id)
    if not existing:
        raise HTTPException(status_code=404, detail="binding_not_found")
    if _is_browseract_connector(existing.connector_name):
        if not operator_allowed:
            raise HTTPException(status_code=404, detail="binding_not_found")
    elif existing.principal_id != context.principal_id and not operator_allowed:
        raise HTTPException(status_code=404, detail="binding_not_found")
    row = container.tool_runtime.set_connector_binding_status(binding_id, body.status)
    if not row:
        raise HTTPException(status_code=404, detail="binding_not_found")
    return ConnectorBindingOut(
        binding_id=row.binding_id,
        principal_id=row.principal_id,
        connector_name=row.connector_name,
        external_account_ref=row.external_account_ref,
        scope_json=row.scope_json,
        auth_metadata_json=_redacted_auth_metadata(row.auth_metadata_json),
        status=row.status,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )
