from __future__ import annotations

import base64
import hashlib
import hmac
import ipaddress
import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone

from fastapi import Depends, HTTPException, Request
from fastapi.params import Depends as DependsMarker

from app.container import AppContainer
from app.services.cloudflare_access import (
    CloudflareAccessIdentity,
    build_operator_id,
    build_operator_notes,
    resolve_access_identity,
)
from app.settings import (
    RuntimeProfile,
    is_prod_mode,
    resolve_runtime_profile,
    resolve_signing_secret,
    resolve_workspace_access_token_audience,
    resolve_workspace_access_token_issuer,
    resolve_workspace_access_token_key_version,
)


_LOG = logging.getLogger(__name__)
_WORKSPACE_ACCESS_MAX_TTL_SECONDS = 7 * 24 * 60 * 60
_WORKSPACE_ACCESS_CLOCK_SKEW_SECONDS = 5 * 60


def get_container(request: Request) -> AppContainer:
    container = getattr(request.app.state, "container", None)
    if container is None:
        raise RuntimeError("application container is not initialized")
    return container


def _extract_token(request: Request) -> str:
    ea_api_token = str(request.headers.get("x-ea-api-token") or "").strip()
    if ea_api_token:
        return ea_api_token
    api_token = str(request.headers.get("x-api-token") or "").strip()
    if api_token:
        return api_token
    header = str(request.headers.get("authorization") or "").strip()
    if header.lower().startswith("bearer "):
        return header[7:].strip()
    return ""


def _telegram_webhook_secret_candidates(*, bot_key: str = "") -> tuple[str, ...]:
    candidates: list[str] = []
    normalized_bot_key = str(bot_key or "").strip()
    raw_registry = str(os.environ.get("EA_TELEGRAM_BOT_REGISTRY_JSON") or "").strip()
    if raw_registry:
        try:
            parsed = json.loads(raw_registry)
        except json.JSONDecodeError:
            parsed = {}
        if isinstance(parsed, dict):
            for raw_key, raw_value in parsed.items():
                if normalized_bot_key and str(raw_key or "").strip() != normalized_bot_key:
                    continue
                if not isinstance(raw_value, dict):
                    continue
                secret = str(raw_value.get("secret") or "").strip()
                if secret:
                    candidates.append(secret)
    if not normalized_bot_key or normalized_bot_key == "default":
        fallback = str(os.environ.get("EA_TELEGRAM_INGEST_SECRET") or "").strip()
        if fallback:
            candidates.append(fallback)
    return tuple(dict.fromkeys(candidates))


def _telegram_webhook_request_authenticated(request: Request) -> bool:
    if request.method.upper() != "POST":
        return False
    path = str(request.url.path or "").strip()
    prefix = "/v1/channels/telegram/ingest"
    if path != prefix and not path.startswith(f"{prefix}/"):
        return False
    provided = str(request.headers.get("x-telegram-bot-api-secret-token") or "").strip()
    if not provided:
        return False
    bot_key = ""
    if path.startswith(f"{prefix}/"):
        bot_key = path.removeprefix(f"{prefix}/").strip("/")
        if "/" in bot_key:
            return False
    for expected in _telegram_webhook_secret_candidates(bot_key=bot_key):
        if hmac.compare_digest(provided, expected):
            return True
    return False


def _log_auth_failure(
    request: Request,
    *,
    detail: str,
    profile: RuntimeProfile,
    expected_token_configured: bool,
) -> None:
    client_host = ""
    client_port = ""
    if request.client is not None:
        client_host = str(getattr(request.client, "host", "") or "")
        client_port = str(getattr(request.client, "port", "") or "")
    authorization = str(request.headers.get("authorization") or "")
    x_ea_api_token = str(request.headers.get("x-ea-api-token") or "")
    x_api_token = str(request.headers.get("x-api-token") or "")
    principal_header = str(
        request.headers.get("x-ea-principal-id")
        or request.headers.get("x-principal-id")
        or request.headers.get("x-ea-operator-id")
        or ""
    ).strip()
    user_agent = str(request.headers.get("user-agent") or "").strip()
    _LOG.warning(
        "ea_auth_failure detail=%s method=%s path=%s client_host=%s client_port=%s auth_mode=%s has_bearer=%s has_x_ea_api_token=%s has_x_api_token=%s has_principal=%s expected_token_configured=%s user_agent=%r",
        detail,
        request.method,
        str(request.url.path or ""),
        client_host,
        client_port,
        str(profile.auth_mode or ""),
        bool(authorization.strip().lower().startswith("bearer ")),
        bool(x_ea_api_token.strip()),
        bool(x_api_token.strip()),
        bool(principal_header),
        bool(expected_token_configured),
        user_agent[:160],
    )


def _configured_api_token(container: AppContainer) -> str:
    return str(container.settings.auth.api_token or "").strip()


def _workspace_access_secret(container: AppContainer) -> str:
    return resolve_signing_secret(container.settings, purpose="workspace-access")


def _workspace_access_token_issuer(container: AppContainer) -> str:
    return resolve_workspace_access_token_issuer(container.settings)


def _workspace_access_token_audience(container: AppContainer) -> str:
    return resolve_workspace_access_token_audience(container.settings)


def _workspace_access_token_key_version(container: AppContainer) -> str:
    return resolve_workspace_access_token_key_version(container.settings)


def _extract_workspace_session_token(request: Request) -> str:
    return (
        str(request.headers.get("x-ea-workspace-session") or "").strip()
        or str(request.cookies.get("ea_workspace_session") or "").strip()
    )


def _verify_signed_payload(*, secret: str, token: str) -> dict[str, object] | None:
    normalized = str(token or "").strip()
    if not normalized or "." not in normalized:
        return None
    payload_b64, signature = normalized.rsplit(".", 1)
    expected = hmac.new(secret.encode("utf-8"), payload_b64.encode("utf-8"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, expected):
        return None
    padding = "=" * ((4 - len(payload_b64) % 4) % 4)
    try:
        payload_bytes = base64.urlsafe_b64decode(f"{payload_b64}{padding}".encode("ascii"))
        payload = json.loads(payload_bytes.decode("utf-8"))
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    issued_raw = str(payload.get("issued_at") or "").strip()
    expires_raw = str(payload.get("expires_at") or "").strip()
    if not issued_raw or not expires_raw:
        return None
    try:
        issued_at = datetime.fromisoformat(issued_raw)
        expires_at = datetime.fromisoformat(expires_raw)
    except ValueError:
        return None
    if issued_at.tzinfo is None:
        issued_at = issued_at.replace(tzinfo=timezone.utc)
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    now = datetime.now(timezone.utc)
    if issued_at > now and (issued_at - now).total_seconds() > _WORKSPACE_ACCESS_CLOCK_SKEW_SECONDS:
        return None
    if expires_at <= now:
        return None
    ttl_seconds = (expires_at - issued_at).total_seconds()
    if ttl_seconds <= 0 or ttl_seconds > _WORKSPACE_ACCESS_MAX_TTL_SECONDS:
        return None
    return payload


def _workspace_session_payload(request: Request, container: AppContainer) -> dict[str, object] | None:
    cached = getattr(request.state, "workspace_access_session_payload", None)
    if isinstance(cached, dict):
        return cached
    if cached is False:
        return None
    token = _extract_workspace_session_token(request)
    if not token:
        setattr(request.state, "workspace_access_session_payload", False)
        return None
    payload = _verify_signed_payload(secret=_workspace_access_secret(container), token=token)
    if payload is None or not hmac.compare_digest(
        str(payload.get("token_kind") or "").strip(),
        "workspace_access_session",
    ):
        setattr(request.state, "workspace_access_session_payload", False)
        return None
    principal_id = str(payload.get("principal_id") or "").strip()
    session_id = str(payload.get("session_id") or "").strip()
    if (
        not principal_id
        or not session_id
        or str(payload.get("iss") or "").strip() != _workspace_access_token_issuer(container)
        or str(payload.get("aud") or "").strip() != _workspace_access_token_audience(container)
        or str(payload.get("kid") or "").strip() != _workspace_access_token_key_version(container)
        or not str(payload.get("jti") or "").strip()
    ):
        setattr(request.state, "workspace_access_session_payload", False)
        return None
    rows = list(container.channel_runtime.list_recent_observations(limit=1000, principal_id=principal_id))
    rows.sort(key=lambda row: (str(row.created_at or ""), str(row.observation_id or "")))
    revoked = False
    issued_payload: dict[str, object] | None = None
    for row in rows:
        event_type = str(row.event_type or "").strip().lower()
        payload_row = dict(row.payload or {})
        current_session_id = str(payload_row.get("session_id") or row.source_id or "").strip()
        if current_session_id != session_id:
            continue
        if event_type == "workspace_access_session_revoked":
            revoked = True
        elif event_type == "workspace_access_session_issued":
            revoked = False
            issued_payload = payload_row
    if revoked:
        setattr(request.state, "workspace_access_session_payload", False)
        return None
    if issued_payload is None:
        setattr(request.state, "workspace_access_session_payload", False)
        return None
    if (
        str(issued_payload.get("jti") or "").strip() != str(payload.get("jti") or "").strip()
        or str(issued_payload.get("issuer") or issued_payload.get("iss") or "").strip() != str(payload.get("iss") or "").strip()
        or str(issued_payload.get("audience") or issued_payload.get("aud") or "").strip() != str(payload.get("aud") or "").strip()
        or str(issued_payload.get("key_version") or issued_payload.get("kid") or "").strip() != str(payload.get("kid") or "").strip()
        or int(issued_payload.get("session_version") or 0) != int(payload.get("session_version") or 0)
    ):
        setattr(request.state, "workspace_access_session_payload", False)
        return None
    setattr(request.state, "workspace_access_session_payload", payload)
    return payload


def _requested_operator_id(request: Request) -> str:
    return str(request.headers.get("x-ea-operator-id") or "").strip()


def _client_host(request: Request) -> str:
    client = getattr(request, "client", None)
    return str(getattr(client, "host", "") or "").strip()


def _normalized_host_header_host(value: object) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    candidate = raw.split(",", 1)[0].strip()
    if candidate.startswith("[") and "]" in candidate:
        return candidate[1:candidate.index("]")].strip().lower()
    if ":" in candidate and candidate.count(":") == 1:
        host_part, _port = candidate.rsplit(":", 1)
        if host_part:
            return host_part.strip().lower()
    return candidate.strip().lower()


def _request_targets_loopback_host(request: Request) -> bool:
    for header_name in ("x-forwarded-host", "host"):
        normalized = _normalized_host_header_host(request.headers.get(header_name))
        if _is_loopback_host(normalized):
            return True
    return False


def _is_docker_host_gateway_host(host: str) -> bool:
    normalized = str(host or "").strip().lower()
    if not normalized:
        return False
    try:
        address = ipaddress.ip_address(normalized)
    except ValueError:
        return False
    if not isinstance(address, ipaddress.IPv4Address):
        return False
    return bool(address.is_private and not address.is_loopback and address.exploded.endswith(".1"))


def _is_loopback_host(host: str) -> bool:
    normalized = str(host or "").strip().lower()
    if not normalized:
        return False
    if normalized in {"localhost", "testclient"}:
        return True
    try:
        return ipaddress.ip_address(normalized).is_loopback
    except ValueError:
        return False


def _loopback_no_auth_allowed(request: Request, container: AppContainer) -> bool:
    if not bool(getattr(container.settings.auth, "allow_loopback_no_auth", False)):
        return False
    return _is_loopback_host(_client_host(request))


def _provision_access_identity(container: AppContainer, identity: CloudflareAccessIdentity) -> None:
    operator_id = build_operator_id(identity)
    current = container.orchestrator.fetch_operator_profile(operator_id, principal_id=identity.principal_id)
    notes = build_operator_notes(identity)
    if (
        current is not None
        and current.display_name == identity.display_name
        and current.status == "active"
        and current.notes == notes
    ):
        return
    container.orchestrator.upsert_operator_profile(
        principal_id=identity.principal_id,
        operator_id=operator_id,
        display_name=identity.display_name,
        roles=("operator", "cloudflare_access"),
        trust_tier="standard",
        status="active",
        notes=notes,
    )


def get_cloudflare_access_identity(
    request: Request,
    container: AppContainer = Depends(get_container),
) -> CloudflareAccessIdentity | None:
    cached = getattr(request.state, "cloudflare_access_identity", None)
    if isinstance(cached, CloudflareAccessIdentity):
        return cached
    if cached is False:
        return None
    try:
        identity = resolve_access_identity(headers=request.headers, settings=container.settings.auth)
    except Exception as exc:
        setattr(request.state, "cloudflare_access_error", str(exc))
        raise HTTPException(status_code=401, detail="cloudflare_access_invalid") from exc
    if identity is None:
        setattr(request.state, "cloudflare_access_identity", False)
        return None
    _provision_access_identity(container, identity)
    setattr(request.state, "cloudflare_access_identity", identity)
    return identity


def _runtime_profile(container: AppContainer):
    profile = getattr(container, "runtime_profile", None)
    if profile is not None:
        return profile
    settings = container.settings
    if hasattr(settings, "storage"):
        return resolve_runtime_profile(settings)
    mode = str(getattr(getattr(settings, "runtime", None), "mode", "dev") or "dev").strip().lower() or "dev"
    api_token = str(getattr(getattr(settings, "auth", None), "api_token", "") or "").strip()
    auth_mode = "token" if mode == "prod" or api_token else "anonymous_dev"
    principal_source = "authenticated_header" if mode == "prod" else (
        "authenticated_header_or_default" if auth_mode == "token" else "caller_header_or_default"
    )
    return RuntimeProfile(
        mode=mode,
        storage_backend="postgres" if mode == "prod" else "memory",
        durability="durable" if mode == "prod" else "ephemeral",
        auth_mode=auth_mode,
        principal_source=principal_source,
        database_required=mode == "prod",
        database_configured=False,
        source_backend="memory",
    )


def _resolved_principal_id(
    request: Request,
    *,
    container: AppContainer,
    authenticated: bool,
    access_identity: CloudflareAccessIdentity | None = None,
) -> str:
    profile = _runtime_profile(container)
    if access_identity is not None:
        return access_identity.principal_id
    principal_id = str(request.headers.get("x-ea-principal-id") or "").strip()
    fallback_principal = str(container.settings.auth.default_principal_id or "").strip()
    if principal_id:
        if profile.caller_principal_header_requires_authentication and not authenticated:
            return ""
        if _loopback_no_auth_allowed(request, container):
            return principal_id
        if authenticated and not authenticated_principal_override_allowed(request):
            principal_id = ""
        else:
            return principal_id
    if fallback_principal and authenticated and profile.default_principal_fallback_allowed:
        return fallback_principal
    if profile.default_principal_fallback_allowed:
        return fallback_principal or "local-user"
    codexea_principal = _codexea_authenticated_principal_id(request)
    if authenticated and codexea_principal:
        return codexea_principal
    return ""


def _codexea_authenticated_principal_id(request: Request) -> str:
    path = str(getattr(getattr(request, "url", None), "path", "") or "").strip()
    if not (
        path == "/v1/models"
        or path == "/v1/responses"
        or path.startswith("/v1/responses/")
        or path == "/v1/codex"
        or path.startswith("/v1/codex/")
    ):
        return ""
    return (
        str(os.environ.get("EA_CODEXEA_AUTHENTICATED_PRINCIPAL_ID") or "").strip()
        or str(os.environ.get("EA_CODEXEA_PRINCIPAL_ID") or "").strip()
    )


def require_request_auth(
    request: Request,
    container: AppContainer = Depends(get_container),
    access_identity: CloudflareAccessIdentity | None = Depends(get_cloudflare_access_identity),
) -> None:
    if _telegram_webhook_request_authenticated(request):
        return None
    get_request_context(request, container, access_identity)
    return None


@dataclass(frozen=True)
class RequestContext:
    principal_id: str
    authenticated: bool
    auth_source: str = "anonymous"
    access_email: str = ""
    operator_id: str = ""
    operator_authorized: bool = False


def authenticated_principal_override_allowed(request: Request) -> bool:
    runtime_mode: object = os.environ.get("EA_RUNTIME_MODE")
    app = getattr(request, "app", None)
    scope = getattr(request, "scope", None)
    if isinstance(scope, dict):
        app = scope.get("app") or app
    state = getattr(app, "state", None)
    container = getattr(state, "container", None) if state is not None else None
    if container is None:
        state = getattr(request, "app", None)
        if state is not None:
            container = getattr(state, "container", None) or state
    if container is not None:
        settings = getattr(container, "settings", None)
        runtime_settings = getattr(settings, "runtime", None) if settings is not None else None
        runtime_mode = (
            getattr(runtime_settings, "mode", None)
            or getattr(settings, "runtime_mode", None)
            or runtime_mode
        )
    if is_prod_mode(runtime_mode):
        return False
    client_host = _client_host(request)
    if not (
        _is_loopback_host(client_host)
        or (_is_docker_host_gateway_host(client_host) and _request_targets_loopback_host(request))
    ):
        return False
    for env_name in (
        "EA_TRUST_AUTHENTICATED_PRINCIPAL_HEADER",
        "EA_ALLOW_AUTHENTICATED_PRINCIPAL_HEADER",
        "EA_TRUST_API_TOKEN_PRINCIPAL_HEADER",
    ):
        if str(os.environ.get(env_name) or "").strip().lower() in {"1", "true", "yes", "on"}:
            return True
    return False


def is_operator_context(context: RequestContext) -> bool:
    return bool(context.operator_authorized and str(context.operator_id or "").strip())


_OPERATOR_PRIVILEGED_ROLES = frozenset({"operator", "admin", "reviewer", "cloudflare_access"})


def _authorized_operator_id(
    container: AppContainer,
    *,
    principal_id: str,
    operator_id: str = "",
) -> str:
    normalized_principal = str(principal_id or "").strip()
    normalized_operator = str(operator_id or "").strip()
    if not normalized_principal or not normalized_operator:
        return ""
    profile = container.orchestrator.fetch_operator_profile(normalized_operator, principal_id=normalized_principal)
    if profile is None:
        return ""
    if str(profile.status or "").strip().lower() != "active":
        return ""
    roles = {str(role or "").strip().lower() for role in tuple(profile.roles or ()) if str(role or "").strip()}
    if not roles.intersection(_OPERATOR_PRIVILEGED_ROLES):
        return ""
    return normalized_operator


def _default_authorized_operator_id(
    container: AppContainer,
    *,
    principal_id: str,
) -> str:
    normalized_principal = str(principal_id or "").strip()
    if not normalized_principal:
        return ""
    list_profiles = getattr(getattr(container, "orchestrator", None), "list_operator_profiles", None)
    if not callable(list_profiles):
        return ""
    try:
        rows = list_profiles(principal_id=normalized_principal, status="active", limit=25)
    except TypeError:
        return ""
    for row in list(rows or []):
        operator_id = _authorized_operator_id(
            container,
            principal_id=normalized_principal,
            operator_id=str(getattr(row, "operator_id", "") or "").strip(),
        )
        if operator_id:
            return operator_id
    return ""


def get_request_context(
    request: Request,
    container: AppContainer = Depends(get_container),
    access_identity: CloudflareAccessIdentity | None = Depends(get_cloudflare_access_identity),
) -> RequestContext:
    cached_context = getattr(request.state, "ea_request_context", None)
    if isinstance(cached_context, RequestContext):
        return cached_context
    if isinstance(access_identity, DependsMarker):
        access_identity = get_cloudflare_access_identity(request, container)
    profile = _runtime_profile(container)
    if access_identity is not None:
        principal_id = _resolved_principal_id(
            request,
            container=container,
            authenticated=True,
            access_identity=access_identity,
        )
        operator_id = _authorized_operator_id(
            container,
            principal_id=principal_id,
            operator_id=build_operator_id(access_identity),
        )
        context = RequestContext(
            principal_id=principal_id,
            authenticated=True,
            auth_source="cloudflare_access",
            access_email=access_identity.email,
            operator_id=operator_id,
            operator_authorized=bool(operator_id),
        )
        setattr(request.state, "ea_request_context", context)
        return context
    workspace_session = _workspace_session_payload(request, container)
    if workspace_session is not None:
        principal_id = str(workspace_session.get("principal_id") or "").strip()
        if not principal_id:
            _log_auth_failure(request, detail="principal_required", profile=profile, expected_token_configured=bool(_configured_api_token(container)))
            raise HTTPException(status_code=401, detail="principal_required")
        role = str(workspace_session.get("role") or "principal").strip().lower() or "principal"
        operator_id = ""
        if role == "operator":
            operator_id = _authorized_operator_id(
                container,
                principal_id=principal_id,
                operator_id=str(workspace_session.get("operator_id") or "").strip(),
            )
        context = RequestContext(
            principal_id=principal_id,
            authenticated=True,
            auth_source="workspace_access_session",
            access_email=str(workspace_session.get("email") or "").strip().lower(),
            operator_id=operator_id,
            operator_authorized=bool(operator_id),
        )
        setattr(request.state, "ea_request_context", context)
        return context
    loopback_no_auth_allowed = _loopback_no_auth_allowed(request, container)
    token_authenticated_on_loopback = False
    if loopback_no_auth_allowed:
        expected = _configured_api_token(container)
        token_authenticated_on_loopback = bool(expected and hmac.compare_digest(_extract_token(request), expected))
    if loopback_no_auth_allowed and not token_authenticated_on_loopback:
        principal_id = _resolved_principal_id(request, container=container, authenticated=True)
        if not principal_id:
            _log_auth_failure(request, detail="principal_required", profile=profile, expected_token_configured=bool(_configured_api_token(container)))
            raise HTTPException(status_code=401, detail="principal_required")
        operator_id = _authorized_operator_id(
            container,
            principal_id=principal_id,
            operator_id=_requested_operator_id(request),
        )
        if not operator_id:
            operator_id = _default_authorized_operator_id(
                container,
                principal_id=principal_id,
            )
        context = RequestContext(
            principal_id=principal_id,
            authenticated=True,
            auth_source="loopback_no_auth",
            operator_id=operator_id,
            operator_authorized=bool(operator_id),
        )
        setattr(request.state, "ea_request_context", context)
        return context
    authenticated = False
    if profile.auth_mode in {"token", "token_or_access"}:
        expected = _configured_api_token(container)
        if not expected:
            _log_auth_failure(request, detail="auth_required", profile=profile, expected_token_configured=False)
            raise HTTPException(status_code=401, detail="auth_required")
        provided = _extract_token(request)
        if not hmac.compare_digest(provided, expected):
            _log_auth_failure(request, detail="auth_required", profile=profile, expected_token_configured=True)
            raise HTTPException(status_code=401, detail="auth_required")
        authenticated = True

    elif profile.auth_mode == "access":
        if not profile.default_principal_fallback_allowed:
            _log_auth_failure(request, detail="auth_required", profile=profile, expected_token_configured=False)
            raise HTTPException(status_code=401, detail="auth_required")

    principal_id = _resolved_principal_id(request, container=container, authenticated=authenticated)
    if not principal_id:
        _log_auth_failure(request, detail="principal_required", profile=profile, expected_token_configured=bool(_configured_api_token(container)))
        raise HTTPException(status_code=401, detail="principal_required")
    operator_id = ""
    if authenticated:
        operator_id = _authorized_operator_id(
            container,
            principal_id=principal_id,
            operator_id=_requested_operator_id(request),
        )
    context = RequestContext(
        principal_id=principal_id,
        authenticated=authenticated,
        auth_source="api_token" if authenticated else "anonymous",
        operator_id=operator_id,
        operator_authorized=bool(operator_id),
    )
    setattr(request.state, "ea_request_context", context)
    return context


def require_operator_context(context: RequestContext = Depends(get_request_context)) -> None:
    if not is_operator_context(context):
        raise HTTPException(status_code=403, detail="operator_scope_required")


def resolve_principal_id(requested_principal_id: str | None, context: RequestContext) -> str:
    requested = str(requested_principal_id or "").strip()
    if requested and requested != context.principal_id:
        raise HTTPException(status_code=403, detail="principal_scope_mismatch")
    return context.principal_id
