from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import os
import re
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.api.dependencies import RequestContext, get_container, get_request_context, is_operator_context as shared_is_operator_context, resolve_principal_id
from app.container import AppContainer
from app.domain.models import ProviderBindingRecord, ProviderBindingState, ToolInvocationRequest
from app.services import responses_upstream as upstream
from app.services.responses_upstream import onemin_owner_account_names_for_email, probe_all_onemin_slots
from app.services.tool_execution_common import ToolExecutionError

router = APIRouter(prefix="/v1/providers", tags=["providers"])

_ONEMIN_DIRECT_API_QUARANTINED_UNTIL = 0.0
_ONEMIN_DIRECT_API_QUARANTINE_REASON = ""
_MEDIA_CHALLENGER_LEDGER_PATH = Path(os.getenv("EA_MEDIA_CHALLENGER_LEDGER_PATH", "/docker/fleet/state/chummer6/ea_challenger_ledger.json"))
_MEDIA_PROVIDER_SCHEDULER_PATH = Path(os.getenv("EA_MEDIA_PROVIDER_SCHEDULER_PATH", "/docker/fleet/state/chummer6/ea_provider_scheduler.json"))


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


class OneminProbeAllIn(BaseModel):
    include_reserve: bool = Field(default=True)


class OneminBillingRefreshIn(BaseModel):
    include_members: bool = Field(default=True)
    include_provider_api: bool = Field(default=True)
    provider_api_all_accounts: bool = Field(default=False)
    provider_api_continue_on_rate_limit: bool = Field(default=False)
    capture_raw_text: bool = Field(default=True)
    timeout_seconds: int | None = Field(default=None, ge=30, le=1800)
    binding_ids: list[str] = Field(default_factory=list)
    account_labels: list[str] = Field(default_factory=list)


class OneminImageReserveIn(BaseModel):
    request_id: str = Field(default="", max_length=200)
    estimated_credits: int = Field(default=1200, ge=0, le=100000000)
    allow_reserve: bool = Field(default=False)


class OneminLeaseReleaseIn(BaseModel):
    status: str = Field(default="released", min_length=1, max_length=50)
    error: str = Field(default="", max_length=1000)
    actual_credits_delta: int | None = Field(default=None, ge=0, le=100000000)


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


def _redacted_auth_metadata(auth_metadata_json: dict[str, object] | None) -> dict[str, object]:
    payload = dict(auth_metadata_json or {})
    return {
        "redacted": bool(payload),
        "field_count": len(payload),
    }


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
        auth_metadata_json=_redacted_auth_metadata(row.auth_metadata_json),
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


def _state_out_redacted(row: ProviderBindingState) -> ProviderStateOut:
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
        secret_env_names=[],
        secret_configured=row.secret_configured,
        capabilities=list(row.capabilities),
        tool_names=list(row.tool_names),
        state=row.state,
        health_state=row.health_state,
        health_details_json={},
        updated_at=row.updated_at,
    )


def _redact_registry_for_principal(view: dict[str, object]) -> dict[str, object]:
    result = dict(view or {})
    redacted_providers: list[dict[str, object]] = []
    for provider in list(result.get("providers") or []):
        row = dict(provider or {})
        slot_pool = dict(row.get("slot_pool") or {})
        slot_pool["owners"] = []
        slot_pool["lease_holders"] = []
        slot_pool["last_used_principal_id"] = ""
        slot_pool["last_used_principal_label"] = ""
        slot_pool["last_used_owner_category"] = ""
        slot_pool["last_used_lane_role"] = ""
        slot_pool["last_used_hub_user_id"] = ""
        slot_pool["last_used_hub_group_id"] = ""
        slot_pool["last_used_sponsor_session_id"] = ""
        slot_pool["last_used_at"] = None
        row["slot_pool"] = slot_pool
        row["last_used_principal_id"] = ""
        row["last_used_principal_label"] = ""
        row["last_used_owner_category"] = ""
        row["last_used_lane_role"] = ""
        row["last_used_hub_user_id"] = ""
        row["last_used_hub_group_id"] = ""
        row["last_used_sponsor_session_id"] = ""
        row["last_used_at"] = None
        redacted_providers.append(row)
    result["providers"] = redacted_providers
    redacted_lanes: list[dict[str, object]] = []
    for lane in list(result.get("lanes") or []):
        row = dict(lane or {})
        capacity_summary = dict(row.get("capacity_summary") or {})
        capacity_summary["slot_owners"] = []
        capacity_summary["lease_holders"] = []
        capacity_summary["last_used_principal_id"] = ""
        capacity_summary["last_used_principal_label"] = ""
        capacity_summary["last_used_owner_category"] = ""
        capacity_summary["last_used_lane_role"] = ""
        capacity_summary["last_used_hub_user_id"] = ""
        capacity_summary["last_used_hub_group_id"] = ""
        capacity_summary["last_used_sponsor_session_id"] = ""
        capacity_summary["last_used_at"] = None
        row["capacity_summary"] = capacity_summary
        row["last_used_principal_id"] = ""
        row["last_used_principal_label"] = ""
        row["last_used_owner_category"] = ""
        row["last_used_lane_role"] = ""
        row["last_used_hub_user_id"] = ""
        row["last_used_hub_group_id"] = ""
        row["last_used_sponsor_session_id"] = ""
        row["last_used_at"] = None
        redacted_lanes.append(row)
    result["lanes"] = redacted_lanes
    return result


def _load_json_file(path: Path) -> dict[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _floatish(value: object, *, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default


def _media_scheduler_summary(now_epoch: float) -> dict[str, object]:
    scheduler = _load_json_file(_MEDIA_PROVIDER_SCHEDULER_PATH)
    providers = scheduler.get("providers") if isinstance(scheduler.get("providers"), dict) else {}
    rows: list[dict[str, object]] = []
    for provider_key, raw_entry in sorted(providers.items()):
        entry = dict(raw_entry or {})
        active_target = str(entry.get("active_target") or "").strip()
        active_until_epoch = _floatish(entry.get("active_until_epoch"), default=0.0)
        wait_seconds = max(0, int(round(active_until_epoch - now_epoch))) if active_target else 0
        rows.append(
            {
                "provider_key": str(provider_key or "").strip(),
                "state": "active" if active_target and wait_seconds > 0 else "idle",
                "active_target": active_target,
                "wait_seconds_remaining": wait_seconds,
                "updated_at_epoch": _floatish(entry.get("updated_at"), default=0.0),
            }
        )
    return {
        "path": str(_MEDIA_PROVIDER_SCHEDULER_PATH),
        "provider_count": len(rows),
        "active_provider_count": sum(1 for row in rows if row["state"] == "active"),
        "providers": rows,
    }


def _media_challenger_summary() -> dict[str, object]:
    ledger = _load_json_file(_MEDIA_CHALLENGER_LEDGER_PATH)
    assets = ledger.get("assets") if isinstance(ledger.get("assets"), dict) else {}
    rows: list[dict[str, object]] = []
    for target, raw_entry in sorted(assets.items()):
        entry = dict(raw_entry or {})
        challenger = dict(entry.get("last_challenger") or {})
        rows.append(
            {
                "target": str(target or "").strip(),
                "provider": str(entry.get("provider") or "").strip(),
                "status": str(entry.get("status") or "").strip(),
                "score": _floatish(entry.get("score"), default=0.0),
                "updated_at_epoch": _floatish(entry.get("updated_at"), default=0.0),
                "last_challenger_provider": str(challenger.get("provider") or "").strip(),
                "last_challenger_status": str(challenger.get("status") or "").strip(),
                "last_challenger_beat_champion": bool(challenger.get("beat_champion")),
                "last_challenger_updated_at_epoch": _floatish(challenger.get("updated_at"), default=0.0),
            }
        )
    return {
        "path": str(_MEDIA_CHALLENGER_LEDGER_PATH),
        "asset_count": len(rows),
        "challenger_count": sum(1 for row in rows if row["last_challenger_provider"]),
        "assets": rows[:50],
    }


@router.post("/bindings", response_model=ProviderBindingOut)
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


@router.get("/bindings", response_model=list[ProviderBindingOut])
def list_provider_bindings(
    principal_id: str | None = Query(default=None, min_length=1),
    limit: int = Query(default=100, ge=1, le=500),
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> list[ProviderBindingOut]:
    resolved_principal = resolve_principal_id(principal_id, context)
    rows = container.provider_registry.list_persisted_binding_records(principal_id=resolved_principal, limit=limit)
    return [_binding_out(row) for row in rows]


@router.get("/bindings/{binding_id}", response_model=ProviderBindingOut)
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


@router.post("/bindings/{binding_id}/status", response_model=ProviderBindingOut)
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


@router.post("/bindings/{binding_id}/probe", response_model=ProviderBindingOut)
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


@router.get("/states", response_model=list[ProviderStateOut])
def list_provider_states(
    principal_id: str | None = Query(default=None, min_length=1),
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> list[ProviderStateOut]:
    resolved_principal = resolve_principal_id(principal_id, context)
    rows = container.provider_registry.list_binding_states(principal_id=resolved_principal)
    include_sensitive = _is_operator_context(context)
    serializer = _state_out if include_sensitive else _state_out_redacted
    return [serializer(row) for row in rows]


@router.get("/states/{provider_key}", response_model=ProviderStateOut)
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
    return _state_out(row) if _is_operator_context(context) else _state_out_redacted(row)


@router.get("/registry", response_model=dict[str, object])
def get_provider_registry(
    principal_id: str | None = Query(default=None, min_length=1),
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> dict[str, object]:
    resolved_principal = resolve_principal_id(principal_id, context)
    provider_health = upstream._provider_health_report()
    profile_decisions = container.brain_router.list_profile_decisions(principal_id=resolved_principal)
    view = container.provider_registry.registry_read_model(
        principal_id=resolved_principal,
        provider_health=provider_health,
        profile_decisions=profile_decisions,
    )
    if not _is_operator_context(context):
        view = _redact_registry_for_principal(view)
    return view


@router.get("/media-stewardship", response_model=None)
def get_media_stewardship(
    context: RequestContext = Depends(get_request_context),
) -> dict[str, object]:
    if not _is_operator_context(context):
        raise HTTPException(status_code=403, detail="operator_scope_required")
    now_epoch = time.time()
    return {
        "contract_name": "ea.media_stewardship",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "provider_scheduler": _media_scheduler_summary(now_epoch),
        "challenger_ledger": _media_challenger_summary(),
    }


@router.post("/onemin/probe-all", response_model=dict[str, object])
def probe_all_onemin(
    body: OneminProbeAllIn | None = None,
    context: RequestContext = Depends(get_request_context),
) -> dict[str, object]:
    if not _is_operator_context(context):
        raise HTTPException(status_code=403, detail="operator_scope_required")
    include_reserve = True if body is None else bool(body.include_reserve)
    return probe_all_onemin_slots(include_reserve=include_reserve)


_ONEMIN_SLOT_ENV_RE = re.compile(r"^ONEMIN_AI_API_KEY(?:_FALLBACK_\d+)?$")


@router.get("/onemin/aggregate", response_model=None)
def get_onemin_aggregate(
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> dict[str, object]:
    return container.onemin_manager.aggregate_snapshot(
        provider_health=upstream._provider_health_report(),
        binding_rows=_enabled_browseract_bindings(container, context.principal_id),
        principal_id=context.principal_id,
    )


@router.get("/onemin/actual-credits", response_model=None)
def get_onemin_actual_credits(
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> dict[str, object]:
    return container.onemin_manager.actual_credits_snapshot(
        provider_health=upstream._provider_health_report(),
        binding_rows=_enabled_browseract_bindings(container, context.principal_id),
        principal_id=context.principal_id,
    )


@router.get("/onemin/accounts", response_model=None)
def get_onemin_accounts(
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> dict[str, object]:
    return {
        "provider_key": "onemin",
        "principal_id": context.principal_id,
        "accounts": container.onemin_manager.accounts_snapshot(
            provider_health=upstream._provider_health_report(),
            binding_rows=_enabled_browseract_bindings(container, context.principal_id),
            principal_id=context.principal_id,
        ),
    }


@router.get("/onemin/runway", response_model=None)
def get_onemin_runway(
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> dict[str, object]:
    return {
        "provider_key": "onemin",
        "principal_id": context.principal_id,
        "forecast": container.onemin_manager.runway_snapshot(
            provider_health=upstream._provider_health_report(),
            binding_rows=_enabled_browseract_bindings(container, context.principal_id),
            principal_id=context.principal_id,
        ),
    }


@router.get("/onemin/leases", response_model=None)
def get_onemin_leases(
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> dict[str, object]:
    return {
        "provider_key": "onemin",
        "principal_id": context.principal_id,
        "leases": container.onemin_manager.leases_snapshot(principal_id=context.principal_id),
    }


@router.get("/onemin/occupancy", response_model=None)
def get_onemin_occupancy(
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> dict[str, object]:
    return {
        "provider_key": "onemin",
        "principal_id": context.principal_id,
        **container.onemin_manager.occupancy_snapshot(principal_id=context.principal_id),
    }


@router.post("/onemin/reserve-image", response_model=None)
def reserve_onemin_image(
    body: OneminImageReserveIn,
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> dict[str, object]:
    operator_allowed = _is_operator_context(context)
    binding_rows = _enabled_browseract_bindings(container, context.principal_id)
    allowed_account_labels = {
        label
        for binding in binding_rows
        for label in _resolve_onemin_account_labels(binding)
        if str(label or "").strip()
    }
    if not operator_allowed and not allowed_account_labels:
        raise HTTPException(status_code=403, detail="onemin_image_binding_required")
    request_id = str(body.request_id or "").strip() or f"image-{uuid.uuid4().hex[:16]}"
    lease = container.onemin_manager.reserve_for_provider_health(
        provider_health=upstream._provider_health_report(),
        lane="image",
        capability="image_generate",
        principal_id=context.principal_id,
        request_id=request_id,
        estimated_credits=int(body.estimated_credits or 0),
        allow_reserve=bool(body.allow_reserve),
        allowed_account_labels=None if operator_allowed else allowed_account_labels,
    )
    if lease is None:
        raise HTTPException(status_code=409, detail="onemin_image_capacity_unavailable")
    response = {
        "provider_key": "onemin",
        "principal_id": context.principal_id,
        "lease_id": str(lease.get("lease_id") or ""),
        "request_id": request_id,
        "task_class": str(lease.get("task_class") or ""),
        "estimated_credits": int(body.estimated_credits or 0),
    }
    if operator_allowed:
        response.update(
            {
                "account_id": str(lease.get("account_name") or ""),
                "credential_id": str(lease.get("credential_id") or ""),
                "slot_name": str(lease.get("slot_name") or ""),
                "secret_env_name": str(lease.get("secret_env_name") or ""),
            }
        )
    return response


@router.post("/onemin/leases/{lease_id}/release", response_model=None)
def release_onemin_lease(
    lease_id: str,
    body: OneminLeaseReleaseIn,
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> dict[str, object]:
    lease_rows = container.onemin_manager.leases_snapshot(principal_id=context.principal_id)
    if not any(str(row.get("lease_id") or "") == lease_id for row in lease_rows):
        raise HTTPException(status_code=404, detail="onemin_lease_not_found")
    if body.actual_credits_delta is not None:
        container.onemin_manager.record_usage(
            lease_id=lease_id,
            actual_credits_delta=int(body.actual_credits_delta),
            status="in_flight",
        )
    container.onemin_manager.release_lease(
        lease_id=lease_id,
        status=str(body.status or "released").strip() or "released",
        error=body.error,
    )
    return {
        "provider_key": "onemin",
        "principal_id": context.principal_id,
        "lease_id": lease_id,
        "status": str(body.status or "released").strip() or "released",
        "actual_credits_delta": body.actual_credits_delta,
    }


def _binding_run_url(binding_metadata: dict[str, object], *keys: str) -> str:
    for key in keys:
        value = str(binding_metadata.get(key) or "").strip()
        if value:
            return value
    return ""


def _binding_workflow_id(binding_metadata: dict[str, object], *keys: str) -> str:
    for key in keys:
        value = str(binding_metadata.get(key) or "").strip()
        if value:
            return value
    return ""


def _binding_has_trusted_onemin_mapping(binding) -> bool:
    binding_metadata = dict(getattr(binding, "auth_metadata_json", {}) or {})
    return bool(binding_metadata.get("trusted_onemin_mapping"))


def _resolve_onemin_account_labels(binding) -> tuple[str, ...]:
    if not _binding_has_trusted_onemin_mapping(binding):
        return ()
    binding_metadata = dict(binding.auth_metadata_json or {})

    explicit_labels: list[str] = []
    for key in (
        "onemin_account_name",
        "onemin_account_names",
        "account_name",
        "account_names",
        "slot_env_name",
        "slot_env_names",
    ):
        raw = binding_metadata.get(key)
        if isinstance(raw, str):
            values = [raw]
        elif isinstance(raw, (list, tuple, set)):
            values = [str(item or "") for item in raw]
        else:
            values = []
        for value in values:
            normalized = str(value or "").strip()
            if normalized and normalized not in explicit_labels:
                explicit_labels.append(normalized)
    if explicit_labels:
        return tuple(explicit_labels)

    external_account_ref = str(binding.external_account_ref or "").strip()
    if external_account_ref and _ONEMIN_SLOT_ENV_RE.fullmatch(external_account_ref):
        return (external_account_ref,)

    owner_email = str(
        binding_metadata.get("owner_email")
        or binding_metadata.get("onemin_owner_email")
        or binding_metadata.get("account_email")
        or external_account_ref
        or ""
    ).strip()
    matches = onemin_owner_account_names_for_email(owner_email=owner_email)
    if len(matches) == 1:
        return matches

    fallback = external_account_ref or str(binding.binding_id or "").strip()
    return (fallback,) if fallback else ()


def _enabled_browseract_bindings(container: AppContainer, principal_id: str) -> list[object]:
    return [
        binding
        for binding in container.tool_runtime.list_connector_bindings(principal_id, limit=500)
        if str(binding.connector_name or "").strip().lower() == "browseract"
        and str(binding.status or "").strip().lower() == "enabled"
    ]


def _all_enabled_browseract_bindings(container: AppContainer) -> list[object]:
    return [
        binding
        for binding in container.tool_runtime.list_connector_bindings_for_connector("browseract", limit=1000)
        if str(binding.status or "").strip().lower() == "enabled"
    ]


def _operator_principal_allowlist() -> set[str]:
    values: set[str] = set()
    for env_name in ("EA_OPERATOR_PRINCIPAL_IDS", "EA_OPERATOR_PRINCIPALS"):
        raw = str(upstream._env(env_name) or "").strip()  # type: ignore[attr-defined]
        if not raw:
            continue
        for item in raw.split(","):
            normalized = str(item or "").strip()
            if normalized:
                values.add(normalized)
    return values


def _operator_email_allowlist() -> set[str]:
    values: set[str] = set()
    for env_name in ("EA_OPERATOR_EMAILS", "EA_OPERATOR_ACCESS_EMAILS"):
        raw = str(upstream._env(env_name) or "").strip()  # type: ignore[attr-defined]
        if not raw:
            continue
        for item in raw.split(","):
            normalized = str(item or "").strip().lower()
            if normalized:
                values.add(normalized)
    return values


def _is_operator_context(context: RequestContext) -> bool:
    return shared_is_operator_context(context)


def _invoke_browseract_tool(
    *,
    container: AppContainer,
    principal_id: str,
    tool_name: str,
    action_kind: str,
    payload_json: dict[str, object],
) -> dict[str, object]:
    result = container.tool_execution.execute_invocation(
        ToolInvocationRequest(
            session_id=f"provider-refresh:{uuid.uuid4()}",
            step_id=f"provider-refresh-step:{uuid.uuid4()}",
            tool_name=tool_name,
            action_kind=action_kind,
            payload_json=payload_json,
            context_json={"principal_id": principal_id},
        )
    )
    return dict(result.output_json or {})


def _onemin_rest_host() -> str:
    return "https://api.1min.ai"


def _onemin_app_version() -> str:
    return "1.1.45"


def _onemin_request_headers(*, token: str = "", include_json_content_type: bool = False) -> dict[str, str]:
    headers = {
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9",
        "Origin": "https://app.1min.ai",
        "Referer": "https://app.1min.ai/",
        "User-Agent": (
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        ),
        "X-App-Version": _onemin_app_version(),
    }
    if include_json_content_type:
        headers["Content-Type"] = "application/json"
    if token:
        headers["X-Auth-Token"] = f"Bearer {token}"
    return headers


def _onemin_direct_api_quarantine_seconds() -> float:
    raw = str(upstream._env("ONEMIN_DIRECT_API_CLOUDFLARE_COOLDOWN_SECONDS") or "").strip()  # type: ignore[attr-defined]
    try:
        seconds = float(raw) if raw else 7200.0
    except Exception:
        seconds = 7200.0
    return max(300.0, seconds)


def _onemin_direct_api_batch_size() -> int:
    raw = str(upstream._env("ONEMIN_DIRECT_API_BATCH_SIZE") or "").strip()  # type: ignore[attr-defined]
    try:
        value = int(raw) if raw else 0
    except Exception:
        value = 0
    return value


def _onemin_direct_api_batch_backoff_seconds() -> float:
    raw = str(upstream._env("ONEMIN_DIRECT_API_BATCH_BACKOFF_SECONDS") or "").strip()  # type: ignore[attr-defined]
    try:
        value = float(raw) if raw else 0.0
    except Exception:
        value = 0.0
    return max(0.0, value)


def _onemin_browseract_max_accounts_per_refresh() -> int:
    raw = str(upstream._env("ONEMIN_BROWSERACT_MAX_ACCOUNTS_PER_REFRESH") or "").strip()  # type: ignore[attr-defined]
    try:
        value = int(raw) if raw else 50
    except Exception:
        value = 50
    return max(1, min(50, value))


def _onemin_browseract_parallelism() -> int:
    raw = str(upstream._env("ONEMIN_BROWSERACT_PARALLELISM") or "").strip()  # type: ignore[attr-defined]
    try:
        value = int(raw) if raw else 6
    except Exception:
        value = 6
    return max(1, min(12, value))


def _onemin_browseract_timeout_seconds(requested_timeout_seconds: int | None = None) -> int:
    if requested_timeout_seconds is not None:
        return max(30, min(int(requested_timeout_seconds), 1800))
    raw = str(upstream._env("ONEMIN_BROWSERACT_TIMEOUT_SECONDS") or "").strip()  # type: ignore[attr-defined]
    try:
        value = int(raw) if raw else 75
    except Exception:
        value = 75
    return max(30, min(value, 1800))


def _onemin_browseract_systemic_failure_threshold() -> int:
    raw = str(upstream._env("ONEMIN_BROWSERACT_SYSTEMIC_FAILURE_THRESHOLD") or "").strip()  # type: ignore[attr-defined]
    try:
        value = int(raw) if raw else 2
    except Exception:
        value = 2
    return max(1, min(value, 10))


def _run_onemin_browseract_jobs(
    *,
    jobs: list[dict[str, object]],
    max_workers: int,
    invoke_job,
    tool_name: str,
    stop_on_failure_codes: set[str] | None = None,
    max_consecutive_stop_failures: int = 0,
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    if not jobs:
        return [], []

    result_rows: list[tuple[int, dict[str, object]]] = []
    error_rows: list[tuple[int, dict[str, object]]] = []

    def _record_result(index: int, job: dict[str, object], output: dict[str, object]) -> None:
        result_rows.append(
            (
                index,
                {
                    "binding_id": str(job.get("binding_id") or ""),
                    "external_account_ref": str(job.get("external_account_ref") or ""),
                    "account_label": str(job.get("account_label") or ""),
                    **dict(output or {}),
                },
            )
        )

    def _record_error(index: int, job: dict[str, object], exc: Exception) -> None:
        error_text = str(exc or "tool_execution_failed")
        error_rows.append(
            (
                index,
                {
                    "binding_id": str(job.get("binding_id") or ""),
                    "external_account_ref": str(job.get("external_account_ref") or ""),
                    "account_label": str(job.get("account_label") or ""),
                    "tool_name": tool_name,
                    "error": error_text,
                    "failure_code": _onemin_browseract_failure_code(error_text),
                },
            )
        )

    ordered_jobs = list(enumerate(jobs))
    worker_count = min(max(int(max_workers), 1), len(ordered_jobs))
    if worker_count <= 1:
        last_failure_code = ""
        consecutive_stop_failures = 0
        for index, job in ordered_jobs:
            try:
                _record_result(index, job, dict(invoke_job(job) or {}))
                last_failure_code = ""
                consecutive_stop_failures = 0
            except Exception as exc:  # pragma: no cover - parity with threaded path
                _record_error(index, job, exc)
                failure_code = _onemin_browseract_failure_code(str(exc or "tool_execution_failed"))
                if (
                    stop_on_failure_codes
                    and max_consecutive_stop_failures > 0
                    and failure_code in stop_on_failure_codes
                ):
                    if failure_code == last_failure_code:
                        consecutive_stop_failures += 1
                    else:
                        last_failure_code = failure_code
                        consecutive_stop_failures = 1
                    if consecutive_stop_failures >= max_consecutive_stop_failures:
                        break
                else:
                    last_failure_code = ""
                    consecutive_stop_failures = 0
        return (
            [row for _, row in sorted(result_rows, key=lambda item: item[0])],
            [row for _, row in sorted(error_rows, key=lambda item: item[0])],
        )

    with ThreadPoolExecutor(max_workers=worker_count, thread_name_prefix="onemin-browseract") as executor:
        future_to_job: dict[object, tuple[int, dict[str, object]]] = {}
        for index, job in ordered_jobs:
            future = executor.submit(invoke_job, job)
            future_to_job[future] = (index, job)
        for future in as_completed(future_to_job):
            index, job = future_to_job[future]
            try:
                _record_result(index, job, dict(future.result() or {}))
            except Exception as exc:
                _record_error(index, job, exc)

    return (
        [row for _, row in sorted(result_rows, key=lambda item: item[0])],
        [row for _, row in sorted(error_rows, key=lambda item: item[0])],
    )


def _onemin_browseract_failure_code(error: object) -> str:
    lowered = str(error or "").strip().lower()
    if not lowered:
        return ""
    marker = "ui_lane_failure:"
    if marker in lowered:
        remainder = lowered.split(marker, 1)[1]
        parts = [part for part in remainder.split(":") if part]
        if len(parts) >= 2:
            return parts[-1]
    if "auth_request_failed" in lowered or "api.1min.ai/auth/login" in lowered:
        return "auth_request_failed"
    if "invalid_credentials" in lowered or "email or password you entered is incorrect" in lowered:
        return "invalid_credentials"
    if "challenge_required" in lowered or "turnstile" in lowered or "cloudflare" in lowered:
        return "challenge_required"
    if "session_expired" in lowered or "please sign in" in lowered or "login required" in lowered:
        return "session_expired"
    if "lane_unavailable" in lowered:
        return "lane_unavailable"
    if "timeout" in lowered:
        return "timeout"
    if "browseract_template_execution_failed" in lowered or "ui_service_worker_failed" in lowered:
        return "ui_worker_failed"
    return ""


def _onemin_direct_api_quarantine_remaining() -> tuple[float, str]:
    remaining = max(0.0, _ONEMIN_DIRECT_API_QUARANTINED_UNTIL - time.time())
    return remaining, str(_ONEMIN_DIRECT_API_QUARANTINE_REASON or "").strip()


def _quarantine_onemin_direct_api(reason: str) -> None:
    global _ONEMIN_DIRECT_API_QUARANTINED_UNTIL, _ONEMIN_DIRECT_API_QUARANTINE_REASON
    _ONEMIN_DIRECT_API_QUARANTINE_REASON = str(reason or "cloudflare_quarantine")
    _ONEMIN_DIRECT_API_QUARANTINED_UNTIL = max(
        _ONEMIN_DIRECT_API_QUARANTINED_UNTIL,
        time.time() + _onemin_direct_api_quarantine_seconds(),
    )


def _onemin_password() -> str:
    return str(
        upstream._env("ONEMIN_DEFAULT_PASSWORD")  # type: ignore[attr-defined]
        or upstream._env("BROWSERACT_PASSWORD")  # type: ignore[attr-defined]
        or ""
    ).strip()


def _onemin_owner_email_for_account(*, account_label: str) -> str:
    normalized = str(account_label or "").strip()
    if not normalized:
        return ""
    for row in upstream.onemin_owner_rows():
        if normalized in {
            str(row.get("account_name") or "").strip(),
            str(row.get("slot") or "").strip(),
            str(row.get("owner_label") or "").strip(),
        }:
            return str(row.get("owner_email") or "").strip()
    return ""


def _browseract_onemin_login_ready(*, account_label: str, binding_metadata: dict[str, object] | None = None) -> bool:
    credentials = upstream.onemin_account_login_credentials(
        account_name=account_label,
        binding_metadata=dict(binding_metadata or {}),
    )
    login_email = str(credentials.get("login_email") or _onemin_owner_email_for_account(account_label=account_label)).strip()
    login_password = str(credentials.get("login_password") or _onemin_password()).strip()
    return bool(login_email and login_password)


def _normalized_onemin_owner_rows(*, account_labels: set[str] | None = None) -> list[dict[str, str]]:
    normalized_labels = {str(value or "").strip() for value in (account_labels or set()) if str(value or "").strip()}
    rows: list[dict[str, str]] = []
    seen_labels: set[str] = set()
    for row in upstream.onemin_owner_rows():
        account_name = str(row.get("account_name") or "").strip()
        owner_email = str(row.get("owner_email") or "").strip()
        if not account_name or not owner_email:
            continue
        if normalized_labels and account_name not in normalized_labels:
            continue
        if account_name in seen_labels:
            continue
        seen_labels.add(account_name)
        rows.append(
            {
                "account_name": account_name,
                "owner_email": owner_email,
            }
        )
    return rows


def _browseract_job_supports_onemin_account(
    *,
    job: dict[str, object],
    account_label: str,
    require_members: bool = False,
) -> bool:
    binding_metadata = dict(job.get("binding_metadata") or {})
    if require_members:
        if str(job.get("members_run_url") or "").strip() or str(job.get("members_workflow_id") or "").strip():
            return True
    else:
        if str(job.get("billing_run_url") or "").strip() or str(job.get("billing_workflow_id") or "").strip():
            return True
    return _browseract_onemin_login_ready(
        account_label=account_label,
        binding_metadata=binding_metadata,
    )


def _select_onemin_browseract_binding_job(
    *,
    binding_jobs: list[dict[str, object]],
    account_label: str,
    require_members: bool = False,
) -> dict[str, object] | None:
    def _explicit_account_labels(binding_metadata: dict[str, object]) -> set[str]:
        labels: set[str] = set()
        for key in (
            "account_labels",
            "onemin_account_name",
            "onemin_account_names",
            "account_name",
            "account_names",
            "slot_env_name",
            "slot_env_names",
        ):
            raw = binding_metadata.get(key)
            if isinstance(raw, str):
                values = [raw]
            elif isinstance(raw, (list, tuple, set)):
                values = list(raw)
            else:
                values = []
            for value in values:
                normalized = str(value or "").strip()
                if normalized:
                    labels.add(normalized)
        return labels

    def _job_priority(job: dict[str, object]) -> tuple[int, int, int, int, str, str]:
        binding_metadata = dict(job.get("binding_metadata") or {})
        explicit_labels = _explicit_account_labels(binding_metadata)
        external_account_ref = str(job.get("external_account_ref") or "").strip()
        has_workflow = bool(
            str(job.get("members_run_url" if require_members else "billing_run_url") or "").strip()
            or str(job.get("members_workflow_id" if require_members else "billing_workflow_id") or "").strip()
        )
        has_owner_mapping = bool(
            explicit_labels
            or str(binding_metadata.get("owner_email") or binding_metadata.get("onemin_owner_email") or "").strip()
            or bool(binding_metadata.get("trusted_onemin_mapping"))
        )
        return (
            0 if account_label in explicit_labels else 1,
            0 if has_workflow else 1,
            0 if has_owner_mapping else 1,
            0 if external_account_ref and _ONEMIN_SLOT_ENV_RE.fullmatch(external_account_ref) else 1,
            str(getattr(job.get("binding"), "binding_id", "") or ""),
            external_account_ref,
        )

    candidates = [
        job
        for job in binding_jobs
        if _browseract_job_supports_onemin_account(
            job=job,
            account_label=account_label,
            require_members=require_members,
        )
    ]
    if not candidates:
        return None
    candidates.sort(key=_job_priority)
    best_priority = _job_priority(candidates[0])
    best_candidates = [job for job in candidates if _job_priority(job) == best_priority]
    seed = sum(ord(char) for char in str(account_label or ""))
    return best_candidates[seed % len(best_candidates)]


def _onemin_parse_iso(value: object) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    candidate = text.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(candidate)
    except Exception:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _partition_onemin_browseract_account_labels(
    *,
    container: AppContainer,
    principal_id: str,
    binding_rows: list[object],
    account_labels: list[str],
) -> tuple[list[str], list[str]]:
    normalized_labels: list[str] = []
    seen: set[str] = set()
    for value in account_labels:
        normalized = str(value or "").strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        normalized_labels.append(normalized)
    if len(normalized_labels) <= 1:
        if not normalized_labels:
            return [], []
        return normalized_labels, []

    try:
        account_rows = container.onemin_manager.accounts_snapshot(
            provider_health=upstream._provider_health_report(),
            binding_rows=binding_rows,
            principal_id=principal_id,
        )
    except Exception:
        return normalized_labels, []

    details_by_label: dict[str, dict[str, object]] = {}
    for row in account_rows:
        label = str(row.get("account_label") or row.get("account_id") or "").strip()
        if label and label not in details_by_label:
            details_by_label[label] = dict(row)

    original_index = {label: index for index, label in enumerate(normalized_labels)}

    def _sort_key(label: str) -> tuple[int, float, int]:
        row = details_by_label.get(label) or {}
        has_actual = bool(row.get("has_actual_billing"))
        last_snapshot = _onemin_parse_iso(row.get("last_billing_snapshot_at"))
        freshness = last_snapshot.timestamp() if last_snapshot is not None else -1.0
        return (
            freshness,
            original_index.get(label, 0),
        )
    missing_labels = sorted(
        [label for label in normalized_labels if not bool((details_by_label.get(label) or {}).get("has_actual_billing"))],
        key=_sort_key,
    )
    actual_labels = sorted(
        [label for label in normalized_labels if bool((details_by_label.get(label) or {}).get("has_actual_billing"))],
        key=_sort_key,
    )
    return missing_labels, actual_labels


def _onemin_interval_for_type(*, topup_type: str, subscription_cycle: str) -> timedelta | None:
    normalized_type = str(topup_type or "").strip().upper()
    normalized_cycle = str(subscription_cycle or "").strip().upper()
    if normalized_type == "DAILY_FREE_CREDIT":
        return timedelta(days=1)
    if any(marker in normalized_type for marker in ("MONTH", "SUBSCRIPTION", "RENEW", "RECURRING")):
        return timedelta(days=30 if normalized_cycle != "YEARLY" else 365)
    if normalized_cycle == "YEARLY":
        return timedelta(days=365)
    if normalized_cycle == "MONTHLY" and normalized_type not in {"SIGNUP_CREDIT", "WELCOME_CREDIT"}:
        return timedelta(days=30)
    return None


def _onemin_latest_remaining_credits(*, topups: list[dict[str, object]], usages: list[dict[str, object]]) -> int | None:
    latest_epoch = -1.0
    latest_value: int | None = None
    for row in topups:
        observed_at = _onemin_parse_iso(row.get("createdAt"))
        value = row.get("afterTopup")
        if observed_at is None or value in (None, ""):
            continue
        epoch = observed_at.timestamp()
        if epoch >= latest_epoch:
            try:
                latest_value = int(round(float(value)))
                latest_epoch = epoch
            except Exception:
                continue
    for row in usages:
        observed_at = _onemin_parse_iso(row.get("createdAt"))
        value = row.get("afterDeduction")
        if observed_at is None or value in (None, ""):
            continue
        epoch = observed_at.timestamp()
        if epoch >= latest_epoch:
            try:
                latest_value = int(round(float(value)))
                latest_epoch = epoch
            except Exception:
                continue
    return latest_value


def _onemin_predict_next_topup(
    *,
    topups: list[dict[str, object]],
    subscription_cycle: str,
) -> tuple[str | None, str | None, str | None, float | None]:
    by_type: dict[str, list[dict[str, object]]] = {}
    for row in topups:
        topup_type = str(row.get("type") or "").strip()
        if not topup_type:
            continue
        by_type.setdefault(topup_type, []).append(row)

    now = datetime.now(timezone.utc)
    candidates: list[tuple[datetime, datetime, float | None]] = []
    for topup_type, rows in by_type.items():
        ordered = sorted(rows, key=lambda item: (_onemin_parse_iso(item.get("createdAt")) or datetime.min.replace(tzinfo=timezone.utc)))
        if not ordered:
            continue
        last_row = ordered[-1]
        last_at = _onemin_parse_iso(last_row.get("createdAt"))
        if last_at is None:
            continue
        interval = None
        if len(ordered) >= 2:
            previous_at = _onemin_parse_iso(ordered[-2].get("createdAt"))
            if previous_at is not None:
                delta = last_at - previous_at
                if delta.total_seconds() > 0:
                    interval = delta
        if interval is None:
            interval = _onemin_interval_for_type(topup_type=topup_type, subscription_cycle=subscription_cycle)
        if interval is None or interval.total_seconds() <= 0:
            continue
        next_at = last_at + interval
        while next_at <= now:
            next_at += interval
        amount = None
        try:
            if last_row.get("credit") not in (None, ""):
                amount = float(last_row.get("credit") or 0.0)
        except Exception:
            amount = None
        candidates.append((next_at, last_at, amount))

    if not candidates:
        return None, None, None, None
    next_at, cycle_start, amount = sorted(candidates, key=lambda item: item[0])[0]
    next_iso = next_at.isoformat().replace("+00:00", "Z")
    start_iso = cycle_start.isoformat().replace("+00:00", "Z")
    return start_iso, next_iso, next_iso, amount


def _onemin_api_get_json(*, url: str, headers: dict[str, str], timeout_seconds: int) -> dict[str, object]:
    request = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            payload = json.loads(response.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"onemin_api_http_{exc.code}:{detail[:240]}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"onemin_api_transport_error:{exc.reason}") from exc
    if not isinstance(payload, dict):
        raise ValueError("invalid_onemin_api_payload")
    return payload


def _onemin_api_login(*, login_email: str, login_password: str, timeout_seconds: int) -> dict[str, object]:
    email = str(login_email or "").strip()
    password = str(login_password or "").strip()
    if not email:
        raise RuntimeError("onemin_login_email_missing")
    if not password:
        raise RuntimeError("onemin_password_missing")
    request = urllib.request.Request(
        f"{_onemin_rest_host()}/auth/login",
        data=json.dumps({"email": email, "password": password}).encode("utf-8"),
        headers=_onemin_request_headers(include_json_content_type=True),
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            payload = json.loads(response.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"onemin_login_http_{exc.code}:{detail[:240]}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"onemin_login_transport_error:{exc.reason}") from exc
    if not isinstance(payload, dict):
        raise ValueError("invalid_onemin_login_payload")
    user = payload.get("user")
    if not isinstance(user, dict):
        raise ValueError("invalid_onemin_login_user")
    return user


def _onemin_members_url(*, team_id: str) -> str:
    filters = json.dumps({"orderBy": [{"createdAt": "desc"}], "page": 1, "pageSize": 1000}, separators=(",", ":"))
    return f"{_onemin_rest_host()}/teams/{team_id}/members?filters={quote(filters, safe='')}"


def _refresh_onemin_api_account(
    *,
    account_name: str,
    owner_email: str,
    include_members: bool,
    timeout_seconds: int,
    login_email: str = "",
    login_password: str = "",
) -> tuple[dict[str, object], dict[str, object] | None]:
    observed_at = upstream.now_utc_iso()
    user = _onemin_api_login(
        login_email=str(login_email or owner_email).strip(),
        login_password=str(login_password or _onemin_password()).strip(),
        timeout_seconds=timeout_seconds,
    )
    teams = user.get("teams") if isinstance(user.get("teams"), list) else []
    if not teams:
        raise RuntimeError("onemin_team_missing")
    team_row = teams[0] if isinstance(teams[0], dict) else {}
    team = team_row.get("team") if isinstance(team_row.get("team"), dict) else {}
    team_id = str(team_row.get("teamId") or team.get("uuid") or "").strip()
    token = str(user.get("token") or "").strip()
    if not team_id or not token:
        raise RuntimeError("onemin_login_incomplete")
    headers = _onemin_request_headers(token=token)
    topups_payload = _onemin_api_get_json(
        url=f"{_onemin_rest_host()}/teams/{team_id}/topups",
        headers=headers,
        timeout_seconds=timeout_seconds,
    )
    usages_payload = _onemin_api_get_json(
        url=f"{_onemin_rest_host()}/teams/{team_id}/usages",
        headers=headers,
        timeout_seconds=timeout_seconds,
    )
    invoices_payload = _onemin_api_get_json(
        url=f"{_onemin_rest_host()}/billings/teams/{team_id}/invoices",
        headers=headers,
        timeout_seconds=timeout_seconds,
    )
    topups = [dict(row) for row in (topups_payload.get("topupList") or []) if isinstance(row, dict)]
    usages = [dict(row) for row in (usages_payload.get("usageList") or []) if isinstance(row, dict)]
    invoices = [dict(row) for row in (invoices_payload.get("invoiceList") or []) if isinstance(row, dict)]
    subscription = team.get("subscription") if isinstance(team.get("subscription"), dict) else {}
    cycle_start_at, next_topup_at, cycle_end_at, topup_amount = _onemin_predict_next_topup(
        topups=topups,
        subscription_cycle=str(subscription.get("cycle") or ""),
    )
    billing_snapshot = upstream.record_onemin_billing_snapshot(
        account_name=account_name,
        source="onemin.api.billing_refresh",
        snapshot_json={
            "observed_at": observed_at,
            "remaining_credits": _onemin_latest_remaining_credits(topups=topups, usages=usages),
            "max_credits": None,
            "used_percent": None,
            "next_topup_at": next_topup_at,
            "cycle_start_at": cycle_start_at,
            "cycle_end_at": cycle_end_at,
            "topup_amount": topup_amount,
            "rollover_enabled": None,
            "basis": "actual_provider_api",
            "source_url": f"{_onemin_rest_host()}/teams/{team_id}/topups",
            "structured_output_json": {
                "owner_email": owner_email,
                "team_id": team_id,
                "team_name": str(team.get("name") or ""),
                "subscription": dict(subscription),
                "topup_list": topups,
                "usage_list": usages,
                "invoice_list": invoices,
            },
        },
    )
    billing_result = {
        "refresh_backend": "onemin_api",
        "account_label": account_name,
        "owner_email": owner_email,
        "team_id": team_id,
        **billing_snapshot,
    }

    if not include_members:
        return billing_result, None

    members_payload = _onemin_api_get_json(
        url=_onemin_members_url(team_id=team_id),
        headers=headers,
        timeout_seconds=timeout_seconds,
    )
    members = []
    for row in members_payload.get("members") or []:
        if not isinstance(row, dict):
            continue
        user_row = row.get("user") if isinstance(row.get("user"), dict) else {}
        members.append(
            {
                "name": str(row.get("userName") or "").strip(),
                "email": str(user_row.get("email") or "").strip(),
                "status": str(row.get("status") or "").strip(),
                "role": str(row.get("role") or "").strip(),
                "credit_limit": row.get("creditLimit"),
                "used_credit": row.get("usedCredit"),
            }
        )
    member_snapshot = upstream.record_onemin_member_reconciliation_snapshot(
        account_name=account_name,
        source="onemin.api.members",
        snapshot_json={
            "observed_at": observed_at,
            "basis": "actual_provider_api",
            "source_url": _onemin_members_url(team_id=team_id),
            "members_json": members,
            "structured_output_json": {
                "owner_email": owner_email,
                "team_id": team_id,
            },
        },
    )
    member_result = {
        "refresh_backend": "onemin_api",
        "account_label": account_name,
        "owner_email": owner_email,
        "team_id": team_id,
        "matched_owner_slots": len(onemin_owner_account_names_for_email(owner_email=owner_email)),
        **member_snapshot,
    }
    return billing_result, member_result


def _refresh_onemin_via_provider_api(
    *,
    include_members: bool,
    timeout_seconds: int,
    all_accounts: bool = False,
    continue_on_rate_limit: bool = False,
    account_labels: set[str] | None = None,
    account_login_credentials: dict[str, dict[str, str]] | None = None,
) -> tuple[
    list[dict[str, object]],
    list[dict[str, object]],
    list[dict[str, object]],
    int,
    int,
    bool,
]:
    billing_results: list[dict[str, object]] = []
    member_results: list[dict[str, object]] = []
    errors: list[dict[str, object]] = []
    owner_rows = [
        row
        for row in upstream.onemin_owner_rows()
        if str(row.get("account_name") or "").strip() and str(row.get("owner_email") or "").strip()
    ]
    login_credentials = dict(account_login_credentials or {})
    normalized_labels = {str(value or "").strip() for value in (account_labels or set()) if str(value or "").strip()}
    if normalized_labels:
        owner_rows = [row for row in owner_rows if str(row.get("account_name") or "").strip() in normalized_labels]

    if all_accounts:
        max_accounts = len(owner_rows)
    else:
        max_accounts_raw = str(upstream._env("ONEMIN_DIRECT_API_MAX_ACCOUNTS_PER_REFRESH") or "").strip()  # type: ignore[attr-defined]
        try:
            max_accounts = int(max_accounts_raw) if max_accounts_raw else 0
        except Exception:
            max_accounts = 0
        if max_accounts <= 0:
            max_accounts = 5
        if max_accounts > len(owner_rows) and owner_rows:
            max_accounts = len(owner_rows)

    delay_raw = str(upstream._env("ONEMIN_DIRECT_API_MIN_ACCOUNT_DELAY_SECONDS") or "").strip()  # type: ignore[attr-defined]
    try:
        delay_seconds = float(delay_raw) if delay_raw else 0.25
    except Exception:
        delay_seconds = 0.25

    batch_size = _onemin_direct_api_batch_size()
    if batch_size <= 0:
        batch_size = max(1, min(4, max_accounts))
    elif batch_size > max(1, max_accounts):
        batch_size = max(1, max_accounts)

    batch_backoff_seconds = _onemin_direct_api_batch_backoff_seconds()
    attempted_count = 0
    rate_limited = False
    quarantine_remaining, quarantine_reason = _onemin_direct_api_quarantine_remaining()
    if quarantine_remaining > 0:
        errors.append(
            {
                "tool_name": "onemin.api.billing_refresh",
                "error": f"onemin_api_quarantined:{int(round(quarantine_remaining))}s:{quarantine_reason or 'cloudflare_block'}",
            }
        )
        return (
            billing_results,
            member_results,
            errors,
            0,
            len(owner_rows),
            True,
        )

    rows = owner_rows[:max_accounts] if max_accounts > 0 else []
    stop_processing = False
    for batch_start in range(0, len(rows), batch_size):
        batch_rows = rows[batch_start : batch_start + batch_size]
        batch_rate_limited = False
        for row in batch_rows:
            account_name = str(row.get("account_name") or "").strip()
            owner_email = str(row.get("owner_email") or "").strip()
            if not account_name or not owner_email:
                continue
            attempted_count += 1
            try:
                credentials = dict(login_credentials.get(account_name) or {})
                billing_result, member_result = _refresh_onemin_api_account(
                    account_name=account_name,
                    owner_email=owner_email,
                    include_members=include_members,
                    timeout_seconds=timeout_seconds,
                    login_email=str(credentials.get("login_email") or owner_email).strip(),
                    login_password=str(credentials.get("login_password") or "").strip(),
                )
                billing_results.append(billing_result)
                if member_result is not None:
                    member_results.append(member_result)
            except Exception as exc:
                error_text = str(exc or "onemin_api_refresh_failed")
                errors.append(
                    {
                        "account_label": account_name,
                        "owner_email": owner_email,
                        "tool_name": "onemin.api.billing_refresh",
                        "error": error_text,
                    }
                )
                if (
                    "onemin_login_http_429" in error_text
                    or "onemin_api_http_429" in error_text
                    or "error code: 1010" in error_text
                    or "error code: 1015" in error_text
                ):
                    rate_limited = True
                    batch_rate_limited = True
                    _quarantine_onemin_direct_api(error_text)
                    if not continue_on_rate_limit:
                        stop_processing = True
                        break
        if stop_processing:
            break
        if batch_start + batch_size >= len(rows):
            break
        if batch_rate_limited and batch_backoff_seconds > 0:
            time.sleep(batch_backoff_seconds)
        elif delay_seconds > 0:
            time.sleep(delay_seconds)
    if attempted_count <= len(owner_rows):
        skipped_count = max(0, len(owner_rows) - attempted_count)
    else:
        skipped_count = 0
    return (
        billing_results,
        member_results,
        errors,
        attempted_count,
        skipped_count,
        rate_limited,
    )


@router.post("/onemin/billing-refresh", response_model=None)
def refresh_onemin_billing(
    body: OneminBillingRefreshIn | None = None,
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> dict[str, object]:
    payload = body or OneminBillingRefreshIn()
    timeout_seconds = _onemin_browseract_timeout_seconds(payload.timeout_seconds)
    requested_ids = {str(binding_id or "").strip() for binding_id in payload.binding_ids if str(binding_id or "").strip()}
    requested_account_labels = {str(account_label or "").strip() for account_label in payload.account_labels if str(account_label or "").strip()}
    operator_allowed = _is_operator_context(context)
    allow_global_provider_api = bool(payload.provider_api_all_accounts) and operator_allowed
    all_api_account_rows = _normalized_onemin_owner_rows(account_labels=requested_account_labels or None)
    principal_browseract_bindings = _enabled_browseract_bindings(container, context.principal_id)
    use_all_browseract_bindings = bool(
        operator_allowed
        and all_api_account_rows
        and (
            allow_global_provider_api
            or requested_account_labels
            or not principal_browseract_bindings
        )
    )
    bindings = [
        binding
        for binding in (
            _all_enabled_browseract_bindings(container) if use_all_browseract_bindings else principal_browseract_bindings
        )
        if (not requested_ids or binding.binding_id in requested_ids)
    ]
    browseract_binding_partition_principal_id = "" if use_all_browseract_bindings else context.principal_id

    billing_results: list[dict[str, object]] = []
    member_results: list[dict[str, object]] = []
    errors: list[dict[str, object]] = []
    skipped: list[dict[str, object]] = []
    bound_account_labels: set[str] = set()
    bound_account_label_order: list[str] = []
    bound_account_login_credentials: dict[str, dict[str, str]] = {}
    browseract_billing_scheduled_labels: set[str] = set()
    browseract_billing_attempted_labels: set[str] = set()
    browseract_billing_result_labels: set[str] = set()
    browseract_billing_error_labels: set[str] = set()
    browseract_member_attempted_labels: set[str] = set()
    browseract_max_accounts = _onemin_browseract_max_accounts_per_refresh()
    browseract_parallelism = _onemin_browseract_parallelism()
    all_account_login_credentials: dict[str, dict[str, str]] = {}
    refresh_allowed, throttle_seconds_remaining, throttle_reason = container.onemin_manager.begin_billing_refresh()
    binding_jobs: list[dict[str, object]] = []

    try:
        for binding in bindings:
            binding_metadata = dict(binding.auth_metadata_json or {})
            billing_run_url = _binding_run_url(
                binding_metadata,
                "onemin_billing_usage_run_url",
                "browseract_onemin_billing_usage_run_url",
                "run_url",
            )
            billing_workflow_id = _binding_workflow_id(
                binding_metadata,
                "onemin_billing_usage_workflow_id",
                "browseract_onemin_billing_usage_workflow_id",
                "workflow_id",
            )
            members_run_url = _binding_run_url(
                binding_metadata,
                "onemin_members_run_url",
                "browseract_onemin_members_run_url",
            )
            members_workflow_id = _binding_workflow_id(
                binding_metadata,
                "onemin_members_workflow_id",
                "browseract_onemin_members_workflow_id",
            )
            account_labels = _resolve_onemin_account_labels(binding)
            if requested_account_labels:
                account_labels = [account_label for account_label in account_labels if account_label in requested_account_labels]
            for account_label in account_labels:
                if account_label not in bound_account_labels:
                    bound_account_labels.add(account_label)
                    bound_account_label_order.append(account_label)
                credentials = upstream.onemin_account_login_credentials(
                    account_name=account_label,
                    binding_metadata=binding_metadata,
                )
                if credentials:
                    bound_account_login_credentials[account_label] = credentials
            binding_jobs.append(
                {
                    "binding": binding,
                    "binding_metadata": binding_metadata,
                    "principal_id": str(binding.principal_id or context.principal_id),
                    "binding_id": binding.binding_id,
                    "external_account_ref": binding.external_account_ref,
                    "billing_run_url": billing_run_url,
                    "billing_workflow_id": billing_workflow_id,
                    "members_run_url": members_run_url,
                    "members_workflow_id": members_workflow_id,
                    "account_labels": account_labels,
                }
            )
            if not account_labels:
                skipped.append(
                    {
                        "binding_id": binding.binding_id,
                        "external_account_ref": binding.external_account_ref,
                        "reason": "account_label_unresolved" if not requested_account_labels else "account_label_filtered",
                    }
                )
        for row in all_api_account_rows:
            account_label = str(row.get("account_name") or "").strip()
            if not account_label or account_label in all_account_login_credentials:
                continue
            credentials = upstream.onemin_account_login_credentials(
                account_name=account_label,
                binding_metadata={},
            )
            if credentials:
                all_account_login_credentials[account_label] = credentials
        all_account_login_credentials.update(bound_account_login_credentials)
        browseract_scope = "bound_accounts_only"
        browseract_target_label_order = list(bound_account_label_order)
        if allow_global_provider_api and all_api_account_rows:
            browseract_scope = "all_owner_accounts"
            browseract_target_label_order = [
                str(row.get("account_name") or "").strip()
                for row in all_api_account_rows
                if str(row.get("account_name") or "").strip()
            ]
        elif not browseract_target_label_order and binding_jobs and all_api_account_rows:
            browseract_scope = "owner_account_recovery"
            browseract_target_label_order = [
                str(row.get("account_name") or "").strip()
                for row in all_api_account_rows
                if str(row.get("account_name") or "").strip()
            ]
        browseract_target_labels = {
            str(value or "").strip()
            for value in browseract_target_label_order
            if str(value or "").strip()
        }
        if refresh_allowed:
            stale_labels, actual_labels = _partition_onemin_browseract_account_labels(
                container=container,
                principal_id=browseract_binding_partition_principal_id if browseract_scope == "bound_accounts_only" else "",
                binding_rows=bindings if browseract_scope == "bound_accounts_only" else [],
                account_labels=browseract_target_label_order,
            )
            selected_browseract_labels = set()
            if stale_labels:
                selected_browseract_labels.update(
                    container.onemin_manager.select_billing_refresh_account_labels(
                        stale_labels,
                        limit=min(browseract_max_accounts, len(stale_labels)),
                    )
                )
            remaining_browseract_slots = max(browseract_max_accounts - len(selected_browseract_labels), 0)
            if remaining_browseract_slots > 0 and actual_labels:
                selected_browseract_labels.update(
                    container.onemin_manager.select_billing_refresh_account_labels(
                        actual_labels,
                        limit=min(remaining_browseract_slots, len(actual_labels)),
                    )
                )
        else:
            selected_browseract_labels = set()
        if requested_account_labels:
            unresolved_requested_labels = sorted(requested_account_labels - browseract_target_labels)
            for account_label in unresolved_requested_labels:
                skipped.append(
                    {
                        "account_label": account_label,
                        "reason": "account_label_not_bound" if browseract_scope == "bound_accounts_only" else "account_label_not_available",
                    }
                )
        browseract_billing_jobs: list[dict[str, object]] = []
        browseract_member_jobs: list[dict[str, object]] = []
        billing_job_results: list[dict[str, object]] = []
        billing_job_errors: list[dict[str, object]] = []
        member_job_results: list[dict[str, object]] = []
        member_job_errors: list[dict[str, object]] = []
        if refresh_allowed:
            if browseract_scope == "bound_accounts_only":
                for job in binding_jobs:
                    binding = job["binding"]
                    binding_metadata = dict(job.get("binding_metadata") or {})
                    billing_run_url = str(job.get("billing_run_url") or "")
                    billing_workflow_id = str(job.get("billing_workflow_id") or "")
                    members_run_url = str(job.get("members_run_url") or "")
                    members_workflow_id = str(job.get("members_workflow_id") or "")
                    account_labels = tuple(str(value or "").strip() for value in (job.get("account_labels") or ()) if str(value or "").strip())
                    for account_label in account_labels:
                        if account_label not in selected_browseract_labels:
                            skipped.append(
                                {
                                    "binding_id": binding.binding_id,
                                    "external_account_ref": binding.external_account_ref,
                                    "account_label": account_label,
                                    "reason": "browseract_refresh_capped",
                                }
                            )
                            continue
                        if account_label in browseract_billing_scheduled_labels:
                            continue
                        if not billing_run_url and not billing_workflow_id and not _browseract_onemin_login_ready(
                            account_label=account_label,
                            binding_metadata=binding_metadata,
                        ):
                            continue
                        browseract_billing_scheduled_labels.add(account_label)
                        browseract_billing_jobs.append(
                            {
                                "principal_id": str(job.get("principal_id") or context.principal_id),
                                "binding_id": binding.binding_id,
                                "external_account_ref": binding.external_account_ref,
                                "account_label": account_label,
                                "capture_raw_text": bool(payload.capture_raw_text),
                                "billing_run_url": billing_run_url,
                                "billing_workflow_id": billing_workflow_id,
                                "members_run_url": members_run_url,
                                "members_workflow_id": members_workflow_id,
                                "member_login_ready": _browseract_onemin_login_ready(
                                    account_label=account_label,
                                    binding_metadata=binding_metadata,
                                ),
                                "timeout_seconds": timeout_seconds,
                            }
                        )
            else:
                for account_label in browseract_target_label_order:
                    if account_label not in selected_browseract_labels:
                        skipped.append(
                            {
                                "account_label": account_label,
                                "reason": "browseract_refresh_capped",
                            }
                        )
                        continue
                    if account_label in browseract_billing_scheduled_labels:
                        continue
                    selected_binding_job = _select_onemin_browseract_binding_job(
                        binding_jobs=binding_jobs,
                        account_label=account_label,
                        require_members=False,
                    )
                    if selected_binding_job is None:
                        skipped.append(
                            {
                                "account_label": account_label,
                                "reason": "browseract_login_unavailable",
                            }
                        )
                        continue
                    binding_metadata = dict(selected_binding_job.get("binding_metadata") or {})
                    browseract_billing_scheduled_labels.add(account_label)
                    browseract_billing_jobs.append(
                        {
                            "principal_id": str(selected_binding_job.get("principal_id") or context.principal_id),
                            "binding_id": str(selected_binding_job.get("binding_id") or ""),
                            "external_account_ref": str(selected_binding_job.get("external_account_ref") or ""),
                            "account_label": account_label,
                            "capture_raw_text": bool(payload.capture_raw_text),
                            "billing_run_url": str(selected_binding_job.get("billing_run_url") or ""),
                            "billing_workflow_id": str(selected_binding_job.get("billing_workflow_id") or ""),
                            "members_run_url": str(selected_binding_job.get("members_run_url") or ""),
                            "members_workflow_id": str(selected_binding_job.get("members_workflow_id") or ""),
                            "member_login_ready": _browseract_onemin_login_ready(
                                account_label=account_label,
                                binding_metadata=binding_metadata,
                            ),
                            "timeout_seconds": timeout_seconds,
                        }
                    )

        if refresh_allowed and browseract_billing_jobs:
            effective_browseract_parallelism = 1 if browseract_scope != "bound_accounts_only" else max(
                1,
                min(
                    browseract_parallelism,
                    len(
                        {
                            str(job.get("binding_id") or "").strip()
                            for job in browseract_billing_jobs
                            if str(job.get("binding_id") or "").strip()
                        }
                    )
                    or 1,
                ),
            )
            billing_job_results, billing_job_errors = _run_onemin_browseract_jobs(
                jobs=browseract_billing_jobs,
                max_workers=effective_browseract_parallelism,
                tool_name="browseract.onemin_billing_usage",
                stop_on_failure_codes={
                    "auth_request_failed",
                    "challenge_required",
                    "session_expired",
                    "timeout",
                    "ui_worker_failed",
                    "lane_unavailable",
                },
                max_consecutive_stop_failures=_onemin_browseract_systemic_failure_threshold(),
                invoke_job=lambda job: _invoke_browseract_tool(
                    container=container,
                    principal_id=str(job.get("principal_id") or context.principal_id),
                    tool_name="browseract.onemin_billing_usage",
                    action_kind="billing.inspect",
                    payload_json={
                        "binding_id": str(job.get("binding_id") or ""),
                        "account_label": str(job.get("account_label") or ""),
                        "capture_raw_text": bool(job.get("capture_raw_text")),
                        **({"run_url": str(job.get("billing_run_url") or "")} if str(job.get("billing_run_url") or "").strip() else {}),
                        **({"workflow_id": str(job.get("billing_workflow_id") or "")} if str(job.get("billing_workflow_id") or "").strip() else {}),
                        "timeout_seconds": int(job.get("timeout_seconds") or timeout_seconds),
                    },
                ),
            )
            billing_results.extend(billing_job_results)
            browseract_billing_result_labels.update(
                str(row.get("account_label") or "").strip()
                for row in billing_job_results
                if str(row.get("account_label") or "").strip()
            )
            browseract_billing_error_labels.update(
                str(row.get("account_label") or "").strip()
                for row in billing_job_errors
                if str(row.get("account_label") or "").strip()
            )
            browseract_billing_attempted_labels = {
                str(row.get("account_label") or "").strip()
                for row in [*billing_job_results, *billing_job_errors]
                if str(row.get("account_label") or "").strip()
            }

        if refresh_allowed and payload.include_members:
            for job in browseract_billing_jobs:
                account_label = str(job.get("account_label") or "").strip()
                if not account_label or account_label not in browseract_billing_result_labels:
                    continue
                if account_label in browseract_member_attempted_labels:
                    continue
                members_run_url = str(job.get("members_run_url") or "")
                members_workflow_id = str(job.get("members_workflow_id") or "")
                if not members_run_url and not members_workflow_id and not bool(job.get("member_login_ready")):
                    continue
                browseract_member_attempted_labels.add(account_label)
                browseract_member_jobs.append(dict(job))

        if refresh_allowed and browseract_member_jobs:
            effective_member_parallelism = 1 if browseract_scope != "bound_accounts_only" else max(
                1,
                min(
                    browseract_parallelism,
                    len(
                        {
                            str(job.get("binding_id") or "").strip()
                            for job in browseract_member_jobs
                            if str(job.get("binding_id") or "").strip()
                        }
                    )
                    or 1,
                ),
            )
            member_job_results, member_job_errors = _run_onemin_browseract_jobs(
                jobs=browseract_member_jobs,
                max_workers=effective_member_parallelism,
                tool_name="browseract.onemin_member_reconciliation",
                stop_on_failure_codes={
                    "auth_request_failed",
                    "challenge_required",
                    "session_expired",
                    "timeout",
                    "ui_worker_failed",
                    "lane_unavailable",
                },
                max_consecutive_stop_failures=_onemin_browseract_systemic_failure_threshold(),
                invoke_job=lambda job: _invoke_browseract_tool(
                    container=container,
                    principal_id=str(job.get("principal_id") or context.principal_id),
                    tool_name="browseract.onemin_member_reconciliation",
                    action_kind="billing.reconcile_members",
                    payload_json={
                        "binding_id": str(job.get("binding_id") or ""),
                        "account_label": str(job.get("account_label") or ""),
                        "capture_raw_text": bool(job.get("capture_raw_text")),
                        **({"run_url": str(job.get("members_run_url") or "")} if str(job.get("members_run_url") or "").strip() else {}),
                        **({"workflow_id": str(job.get("members_workflow_id") or "")} if str(job.get("members_workflow_id") or "").strip() else {}),
                        "timeout_seconds": int(job.get("timeout_seconds") or timeout_seconds),
                    },
                ),
            )
            member_results.extend(member_job_results)

        selected_binding_ids: list[str] = []
        seen_selected_binding_ids: set[str] = set()
        for job in [*browseract_billing_jobs, *browseract_member_jobs]:
            binding_id = str(job.get("binding_id") or "").strip()
            if not binding_id or binding_id in seen_selected_binding_ids:
                continue
            seen_selected_binding_ids.add(binding_id)
            selected_binding_ids.append(binding_id)

        api_billing_results: list[dict[str, object]] = []
        api_member_results: list[dict[str, object]] = []
        api_errors: list[dict[str, object]] = []
        api_attempted_count = 0
        api_skipped_count = 0
        api_rate_limited = False
        provider_api_target_labels: set[str] = set()
        browseract_failed_labels = {
            str(row.get("account_label") or "").strip()
            for row in [*billing_job_errors, *member_job_errors]
            if str(row.get("account_label") or "").strip()
        }
        recovered_browseract_labels: set[str] = set()
        effective_include_provider_api = bool(payload.include_provider_api)
        provider_api_skip_reason = ""
        provider_api_recovery_mode = ""
        browseract_gap_labels = browseract_target_labels - browseract_billing_attempted_labels
        if effective_include_provider_api and not allow_global_provider_api and not browseract_target_labels:
            effective_include_provider_api = False
        if effective_include_provider_api:
            if browseract_failed_labels:
                provider_api_target_labels = set(browseract_failed_labels | browseract_gap_labels)
                provider_api_recovery_mode = "browseract_failure_recovery"
            elif browseract_gap_labels:
                provider_api_target_labels = set(browseract_gap_labels)
                provider_api_recovery_mode = "browseract_gap_recovery"
            elif browseract_billing_attempted_labels:
                effective_include_provider_api = False
                provider_api_skip_reason = "browseract_login_refresh"
                api_skipped_count = len(browseract_target_labels) if browseract_target_labels else len(all_api_account_rows)
            elif not allow_global_provider_api:
                provider_api_target_labels = set(browseract_target_labels)
        if refresh_allowed and effective_include_provider_api:
            effective_api_all_accounts = bool(allow_global_provider_api and not provider_api_target_labels)
            effective_api_account_labels = None if effective_api_all_accounts else provider_api_target_labels or set(browseract_target_labels)
            effective_api_login_credentials = None if effective_api_all_accounts else {
                account_label: credentials
                for account_label, credentials in all_account_login_credentials.items()
                if account_label in (effective_api_account_labels or set())
            }
            (
                api_billing_results,
                api_member_results,
                api_errors,
                api_attempted_count,
                api_skipped_count,
                api_rate_limited,
            ) = _refresh_onemin_via_provider_api(
                include_members=bool(payload.include_members),
                timeout_seconds=timeout_seconds,
                all_accounts=effective_api_all_accounts,
                continue_on_rate_limit=bool(payload.provider_api_continue_on_rate_limit) and operator_allowed,
                account_labels=effective_api_account_labels,
                account_login_credentials=effective_api_login_credentials,
            )
            existing_billing_labels = {
                str(row.get("account_label") or "").strip()
                for row in billing_results
                if str(row.get("account_label") or "").strip()
            }
            for row in api_billing_results:
                account_label = str(row.get("account_label") or "").strip()
                if account_label:
                    recovered_browseract_labels.add(account_label)
                if account_label and account_label in existing_billing_labels:
                    continue
                billing_results.append(row)
                if account_label:
                    existing_billing_labels.add(account_label)
            existing_member_labels = {
                str(row.get("account_label") or "").strip()
                for row in member_results
                if str(row.get("account_label") or "").strip()
            }
            for row in api_member_results:
                account_label = str(row.get("account_label") or "").strip()
                if account_label:
                    recovered_browseract_labels.add(account_label)
                if account_label and account_label in existing_member_labels:
                    continue
                member_results.append(row)
                if account_label:
                    existing_member_labels.add(account_label)
        elif effective_include_provider_api:
            api_skipped_count = len(all_api_account_rows) if allow_global_provider_api else len(browseract_target_labels)

        unrecovered_browseract_errors = [
            row
            for row in [*billing_job_errors, *member_job_errors]
            if str(row.get("account_label") or "").strip() not in recovered_browseract_labels
        ]
        errors.extend(unrecovered_browseract_errors)
        errors.extend(api_errors)

        provider_health = upstream._provider_health_report()
        principal_binding_rows = _enabled_browseract_bindings(container, context.principal_id)
        aggregate_snapshot = container.onemin_manager.aggregate_snapshot(
            provider_health=provider_health,
            binding_rows=principal_binding_rows,
            principal_id=context.principal_id,
        )
        actual_credits_snapshot = container.onemin_manager.actual_credits_snapshot(
            provider_health=provider_health,
            binding_rows=principal_binding_rows,
            principal_id=context.principal_id,
        )
        global_aggregate_snapshot = (
            container.onemin_manager.aggregate_snapshot(
                provider_health=provider_health,
                binding_rows=_all_enabled_browseract_bindings(container),
                principal_id="",
            )
            if operator_allowed
            else {}
        )
        api_quarantine_remaining, api_quarantine_reason = _onemin_direct_api_quarantine_remaining()
        browseract_scope_label = "owner-ledger 1min account(s)" if browseract_scope != "bound_accounts_only" else "bound 1min account(s)"

        note = ""
        if not refresh_allowed:
            throttle_window = max(int(round(throttle_seconds_remaining)), 1)
            if throttle_reason == "in_flight":
                note = f"Live 1min billing refresh is already in progress; retry in about {throttle_window}s."
            else:
                note = f"Live 1min billing refresh is throttled to one run per minute; retry in about {throttle_window}s."
        elif provider_api_recovery_mode == "browseract_failure_recovery":
            recovered_count = len(recovered_browseract_labels & browseract_failed_labels)
            failed_count = len(browseract_failed_labels)
            unrecovered_count = len(unrecovered_browseract_errors)
            if api_rate_limited:
                note = (
                    f"BrowserAct failed for {failed_count} {browseract_scope_label}; direct 1min API fallback was rate-limited or quarantined. "
                    "Aggregate balances reflect the latest known snapshots and estimates."
                )
            elif recovered_count and unrecovered_count:
                note = (
                    f"BrowserAct failed for {failed_count} {browseract_scope_label}; direct 1min API fallback recovered "
                    f"{recovered_count} and {unrecovered_count} remain unrecovered."
                )
            elif recovered_count:
                note = f"BrowserAct failures were recovered through the direct 1min API for {recovered_count} {browseract_scope_label}."
            elif failed_count:
                note = (
                    f"BrowserAct failed for {failed_count} {browseract_scope_label}, and direct 1min API fallback did not recover any account this cycle."
                )
        elif provider_api_recovery_mode == "browseract_gap_recovery":
            recovered_count = len(api_billing_results)
            gap_count = len(browseract_gap_labels)
            if recovered_count:
                note = (
                    f"BrowserAct did not attempt {gap_count} {browseract_scope_label}; direct 1min API covered "
                    f"{recovered_count} account(s) that were outside the live browser pass."
                )
            else:
                note = (
                    f"BrowserAct skipped {gap_count} {browseract_scope_label}, and direct 1min API did not recover any skipped account this cycle."
                )
        elif provider_api_skip_reason == "browseract_login_refresh":
            if len(browseract_billing_attempted_labels) < len(browseract_target_labels):
                note = (
                    f"{'Owner-ledger' if browseract_scope != 'bound_accounts_only' else 'Bound'} 1min account telemetry refreshed through BrowserAct login-backed billing pages "
                    f"for {len(browseract_billing_attempted_labels)} of {len(browseract_target_labels)} "
                    f"{'owner-ledger' if browseract_scope != 'bound_accounts_only' else 'bound'} accounts this cycle; "
                    "direct 1min API refresh was skipped to avoid provider rate limiting."
                )
            else:
                note = (
                    f"{'Owner-ledger' if browseract_scope != 'bound_accounts_only' else 'Bound'} 1min account telemetry refreshed through BrowserAct login-backed billing pages; "
                    "direct 1min API refresh was skipped to avoid provider rate limiting."
                )
        elif bool(payload.include_provider_api) and not effective_include_provider_api:
            note = "Direct 1min API refresh is disabled without operator scope or an eligible 1min account selection."
        elif not bindings and api_billing_results:
            note = "No BrowserAct connector bindings were configured; refreshed 1min account telemetry through the direct 1min API."
        elif not bindings and api_rate_limited:
            note = "No enabled BrowserAct connector bindings were configured, and direct 1min API calls were rate-limited. Retry later or add BrowserAct bindings for browser-backed billing probes."
        elif not bindings:
            note = "No enabled BrowserAct connector bindings were configured for this principal."
        elif not billing_results and not member_results and not errors:
            note = "No BrowserAct 1min billing or member workflows were configured on the selected bindings."

        return {
            "provider_key": "onemin",
            "principal_id": context.principal_id,
            "connector_binding_count": len(bindings),
            "api_account_count": len(all_api_account_rows),
            "api_account_attempted": api_attempted_count,
            "api_account_skipped": api_skipped_count,
            "api_rate_limited": api_rate_limited,
            "provider_api_quarantine_seconds_remaining": max(int(round(api_quarantine_remaining)), 0),
            "provider_api_quarantine_reason": api_quarantine_reason,
            "refresh_throttled": not refresh_allowed,
            "refresh_throttle_seconds_remaining": max(int(round(throttle_seconds_remaining)), 0) if not refresh_allowed else 0,
            "provider_api_scope": "global" if allow_global_provider_api else "bound_accounts_only",
            "provider_api_recovery_mode": provider_api_recovery_mode,
            "provider_api_target_labels": sorted(provider_api_target_labels),
            "browseract_scope": browseract_scope,
            "browseract_target_labels": sorted(browseract_target_labels),
            "selected_binding_ids": selected_binding_ids,
            "candidate_binding_ids": [binding.binding_id for binding in bindings],
            "billing_refresh_count": len(billing_results),
            "member_reconciliation_count": len(member_results),
            "api_billing_refresh_count": len(api_billing_results),
            "api_member_reconciliation_count": len(api_member_results),
            "browseract_failed_labels": sorted(browseract_failed_labels),
            "browseract_recovered_labels": sorted(recovered_browseract_labels & browseract_failed_labels),
            "billing_results": billing_results,
            "member_results": member_results,
            "errors": errors,
            "skipped": skipped,
            "aggregate_snapshot": aggregate_snapshot,
            "actual_credits_snapshot": actual_credits_snapshot,
            "global_aggregate_snapshot": global_aggregate_snapshot,
            "note": note,
        }
    finally:
        if refresh_allowed:
            container.onemin_manager.finish_billing_refresh()


@router.post("/onemin/member-reconcile", response_model=None)
def reconcile_onemin_members(
    body: OneminBillingRefreshIn | None = None,
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> dict[str, object]:
    payload = body or OneminBillingRefreshIn()
    return refresh_onemin_billing(
        OneminBillingRefreshIn(
            include_members=True,
            include_provider_api=payload.include_provider_api,
            provider_api_all_accounts=payload.provider_api_all_accounts,
            provider_api_continue_on_rate_limit=payload.provider_api_continue_on_rate_limit,
            capture_raw_text=payload.capture_raw_text,
            timeout_seconds=payload.timeout_seconds,
            binding_ids=list(payload.binding_ids),
        ),
        container=container,
        context=context,
    )
