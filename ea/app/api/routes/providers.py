from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.api.dependencies import RequestContext, get_container, get_request_context, resolve_principal_id
from app.container import AppContainer
from app.domain.models import ProviderBindingRecord, ProviderBindingState, ToolInvocationRequest
from app.services import responses_upstream as upstream
from app.services.responses_upstream import onemin_owner_account_names_for_email, probe_all_onemin_slots
from app.services.tool_execution_common import ToolExecutionError

router = APIRouter(prefix="/v1/providers", tags=["providers"])

_ONEMIN_DIRECT_API_QUARANTINED_UNTIL = 0.0
_ONEMIN_DIRECT_API_QUARANTINE_REASON = ""


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
    return [_state_out(row) for row in rows]


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
    return _state_out(row)


@router.get("/registry", response_model=dict[str, object])
def get_provider_registry(
    principal_id: str | None = Query(default=None, min_length=1),
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> dict[str, object]:
    resolved_principal = resolve_principal_id(principal_id, context)
    provider_health = upstream._provider_health_report()
    profile_decisions = container.brain_router.list_profile_decisions(principal_id=resolved_principal)
    return container.provider_registry.registry_read_model(
        principal_id=resolved_principal,
        provider_health=provider_health,
        profile_decisions=profile_decisions,
    )


@router.post("/onemin/probe-all", response_model=dict[str, object])
def probe_all_onemin(
    body: OneminProbeAllIn | None = None,
    context: RequestContext = Depends(get_request_context),
) -> dict[str, object]:
    _ = context
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


def _resolve_onemin_account_labels(binding) -> tuple[str, ...]:
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


def _onemin_api_login(*, owner_email: str, timeout_seconds: int) -> dict[str, object]:
    password = _onemin_password()
    if not password:
        raise RuntimeError("onemin_password_missing")
    request = urllib.request.Request(
        f"{_onemin_rest_host()}/auth/login",
        data=json.dumps({"email": owner_email, "password": password}).encode("utf-8"),
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
) -> tuple[dict[str, object], dict[str, object] | None]:
    observed_at = upstream.now_utc_iso()
    user = _onemin_api_login(owner_email=owner_email, timeout_seconds=timeout_seconds)
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

    for idx, row in enumerate(owner_rows):
        if idx >= max_accounts:
            break
        account_name = str(row.get("account_name") or "").strip()
        owner_email = str(row.get("owner_email") or "").strip()
        if not account_name or not owner_email:
            continue
        attempted_count += 1
        try:
            billing_result, member_result = _refresh_onemin_api_account(
                account_name=account_name,
                owner_email=owner_email,
                include_members=include_members,
                timeout_seconds=timeout_seconds,
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
                _quarantine_onemin_direct_api(error_text)
                if not continue_on_rate_limit:
                    break
        if idx + 1 < min(len(owner_rows), max_accounts) and delay_seconds > 0:
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
    timeout_seconds = int(payload.timeout_seconds) if payload.timeout_seconds is not None else 180
    requested_ids = {str(binding_id or "").strip() for binding_id in payload.binding_ids if str(binding_id or "").strip()}
    bindings = [
        binding
        for binding in container.tool_runtime.list_connector_bindings(context.principal_id, limit=500)
        if str(binding.connector_name or "").strip().lower() == "browseract"
        and str(binding.status or "").strip().lower() == "enabled"
        and (not requested_ids or binding.binding_id in requested_ids)
    ]

    billing_results: list[dict[str, object]] = []
    member_results: list[dict[str, object]] = []
    errors: list[dict[str, object]] = []
    skipped: list[dict[str, object]] = []

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
        if not account_labels:
            skipped.append(
                {
                    "binding_id": binding.binding_id,
                    "external_account_ref": binding.external_account_ref,
                    "reason": "account_label_unresolved",
                }
            )
            continue

        if not billing_run_url and not billing_workflow_id:
            skipped.append(
                {
                    "binding_id": binding.binding_id,
                    "external_account_ref": binding.external_account_ref,
                    "reason": "billing_workflow_missing",
                    "account_labels": list(account_labels),
                }
            )
        else:
            for account_label in account_labels:
                try:
                    output = _invoke_browseract_tool(
                        container=container,
                        principal_id=context.principal_id,
                        tool_name="browseract.onemin_billing_usage",
                        action_kind="billing.inspect",
                        payload_json={
                            "binding_id": binding.binding_id,
                            "account_label": account_label,
                            "capture_raw_text": bool(payload.capture_raw_text),
                            **({"run_url": billing_run_url} if billing_run_url else {}),
                            **({"workflow_id": billing_workflow_id} if billing_workflow_id else {}),
                            **({"timeout_seconds": timeout_seconds} if payload.timeout_seconds is not None else {}),
                        },
                    )
                    billing_results.append(
                        {
                            "binding_id": binding.binding_id,
                            "external_account_ref": binding.external_account_ref,
                            "account_label": account_label,
                            **output,
                        }
                    )
                except ToolExecutionError as exc:
                    errors.append(
                        {
                            "binding_id": binding.binding_id,
                            "external_account_ref": binding.external_account_ref,
                            "account_label": account_label,
                            "tool_name": "browseract.onemin_billing_usage",
                            "error": str(exc or "tool_execution_failed"),
                        }
                    )

        if not payload.include_members:
            continue
        if not members_run_url and not members_workflow_id:
            skipped.append(
                {
                    "binding_id": binding.binding_id,
                    "external_account_ref": binding.external_account_ref,
                    "reason": "members_workflow_missing",
                    "account_labels": list(account_labels),
                }
            )
            continue
        for account_label in account_labels:
            try:
                output = _invoke_browseract_tool(
                    container=container,
                    principal_id=context.principal_id,
                    tool_name="browseract.onemin_member_reconciliation",
                    action_kind="billing.reconcile_members",
                    payload_json={
                        "binding_id": binding.binding_id,
                        "account_label": account_label,
                        "capture_raw_text": bool(payload.capture_raw_text),
                        **({"run_url": members_run_url} if members_run_url else {}),
                        **({"workflow_id": members_workflow_id} if members_workflow_id else {}),
                        **({"timeout_seconds": timeout_seconds} if payload.timeout_seconds is not None else {}),
                    },
                )
                member_results.append(
                    {
                        "binding_id": binding.binding_id,
                        "external_account_ref": binding.external_account_ref,
                        "account_label": account_label,
                        **output,
                    }
                )
            except ToolExecutionError as exc:
                errors.append(
                    {
                        "binding_id": binding.binding_id,
                        "external_account_ref": binding.external_account_ref,
                        "account_label": account_label,
                        "tool_name": "browseract.onemin_member_reconciliation",
                        "error": str(exc or "tool_execution_failed"),
                    }
                )

    api_billing_results: list[dict[str, object]] = []
    api_member_results: list[dict[str, object]] = []
    api_attempted_count = 0
    api_skipped_count = 0
    api_rate_limited = False
    if payload.include_provider_api:
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
            all_accounts=bool(payload.provider_api_all_accounts),
            continue_on_rate_limit=bool(payload.provider_api_continue_on_rate_limit),
        )
        billing_results.extend(api_billing_results)
        member_results.extend(api_member_results)
        errors.extend(api_errors)

    note = ""
    if not bindings and api_billing_results:
        note = "No BrowserAct connector bindings were configured; refreshed top-up telemetry through the direct 1min API."
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
        "api_account_count": len([row for row in upstream.onemin_owner_rows() if row.get("account_name") and row.get("owner_email")]),
        "api_account_attempted": api_attempted_count,
        "api_account_skipped": api_skipped_count,
        "api_rate_limited": api_rate_limited,
        "selected_binding_ids": [binding.binding_id for binding in bindings],
        "billing_refresh_count": len(billing_results),
        "member_reconciliation_count": len(member_results),
        "api_billing_refresh_count": len(api_billing_results),
        "api_member_reconciliation_count": len(api_member_results),
        "billing_results": billing_results,
        "member_results": member_results,
        "errors": errors,
        "skipped": skipped,
        "note": note,
    }


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
