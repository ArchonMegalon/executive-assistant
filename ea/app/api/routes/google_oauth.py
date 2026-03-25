from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.api.dependencies import RequestContext, get_container, get_request_context, resolve_principal_id, require_request_auth
from app.container import AppContainer
from app.services.google_oauth import (
    GOOGLE_PROVIDER_KEY,
    GoogleGmailSmokeResult,
    GoogleOAuthAccount,
    build_google_oauth_start,
    complete_google_oauth_callback,
    disconnect_google_account,
    list_google_accounts,
    run_google_gmail_smoke_test,
    upgrade_google_oauth_scope,
)

router = APIRouter(prefix="/v1/providers/google", tags=["providers-google"])


class GoogleOAuthStartIn(BaseModel):
    principal_id: str | None = Field(default=None, min_length=1, max_length=200)
    scope_bundle: str = Field(default="send", min_length=1, max_length=50)


class GoogleOAuthStartOut(BaseModel):
    provider_key: str
    principal_id: str
    scope_bundle: str
    requested_scopes: list[str]
    auth_url: str
    state: str


class GoogleOAuthAccountOut(BaseModel):
    binding_id: str
    provider_key: str
    principal_id: str
    google_email: str
    google_subject: str
    google_hosted_domain: str
    granted_scopes: list[str]
    consent_stage: str
    workspace_mode: str
    token_status: str
    last_refresh_at: str
    reauth_required_reason: str
    connector_binding_id: str


class GoogleOAuthCallbackOut(GoogleOAuthAccountOut):
    pass


class GoogleGmailSmokeTestOut(BaseModel):
    binding_id: str
    provider_key: str
    principal_id: str
    sender_email: str
    recipient_email: str | None
    rfc822_message_id: str
    gmail_message_id: str
    sent_at: str


class GoogleOAuthDisconnectIn(BaseModel):
    principal_id: str | None = Field(default=None, min_length=1, max_length=200)


class GoogleGmailSmokeTestIn(BaseModel):
    principal_id: str | None = Field(default=None, min_length=1, max_length=200)
    recipient_email: str | None = Field(default=None, max_length=320)


def _account_out(account: GoogleOAuthAccount) -> GoogleOAuthAccountOut:
    return GoogleOAuthAccountOut(
        binding_id=account.binding.binding_id,
        provider_key=account.binding.provider_key,
        principal_id=account.binding.principal_id,
        google_email=account.google_email,
        google_subject=account.google_subject,
        google_hosted_domain=account.google_hosted_domain,
        granted_scopes=list(account.granted_scopes),
        consent_stage=account.consent_stage,
        workspace_mode=account.workspace_mode,
        token_status=account.token_status,
        last_refresh_at=account.last_refresh_at,
        reauth_required_reason=account.reauth_required_reason,
        connector_binding_id=account.connector_binding.binding_id if account.connector_binding is not None else "",
    )


@router.post("/oauth/start", dependencies=[Depends(require_request_auth)])
def google_oauth_start(
    body: GoogleOAuthStartIn,
    context: RequestContext = Depends(get_request_context),
) -> GoogleOAuthStartOut:
    principal_id = resolve_principal_id(body.principal_id, context)
    try:
        packet = build_google_oauth_start(principal_id=principal_id, scope_bundle=body.scope_bundle)
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return GoogleOAuthStartOut(
        provider_key=GOOGLE_PROVIDER_KEY,
        principal_id=packet.principal_id,
        scope_bundle=packet.scope_bundle,
        requested_scopes=list(packet.requested_scopes),
        auth_url=packet.auth_url,
        state=packet.state,
    )


@router.get("/oauth/callback")
def google_oauth_callback(
    code: str = Query(..., min_length=1),
    state: str = Query(..., min_length=1),
    container: AppContainer = Depends(get_container),
) -> GoogleOAuthCallbackOut:
    try:
        account = complete_google_oauth_callback(container=container, code=code, state=state)
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _account_out(account)


@router.post("/oauth/upgrade-scope", dependencies=[Depends(require_request_auth)])
def google_oauth_upgrade_scope(
    body: GoogleOAuthStartIn,
    context: RequestContext = Depends(get_request_context),
) -> GoogleOAuthStartOut:
    principal_id = resolve_principal_id(body.principal_id, context)
    try:
        packet = upgrade_google_oauth_scope(principal_id=principal_id, scope_bundle=body.scope_bundle)
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return GoogleOAuthStartOut(
        provider_key=GOOGLE_PROVIDER_KEY,
        principal_id=packet.principal_id,
        scope_bundle=packet.scope_bundle,
        requested_scopes=list(packet.requested_scopes),
        auth_url=packet.auth_url,
        state=packet.state,
    )


@router.post("/oauth/disconnect", dependencies=[Depends(require_request_auth)])
def google_oauth_disconnect(
    body: GoogleOAuthDisconnectIn,
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> GoogleOAuthAccountOut:
    principal_id = resolve_principal_id(body.principal_id, context)
    try:
        binding = disconnect_google_account(container=container, principal_id=principal_id)
    except RuntimeError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    accounts = list_google_accounts(container=container, principal_id=principal_id)
    for account in accounts:
        if account.binding.binding_id == binding.binding_id:
            return _account_out(account)
    raise HTTPException(status_code=404, detail="google_oauth_binding_not_found")


@router.get("/accounts", dependencies=[Depends(require_request_auth)])
def google_oauth_accounts(
    principal_id: str | None = Query(default=None, min_length=1),
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> list[GoogleOAuthAccountOut]:
    resolved_principal = resolve_principal_id(principal_id, context)
    return [_account_out(account) for account in list_google_accounts(container=container, principal_id=resolved_principal)]


@router.post("/gmail/smoke-test", dependencies=[Depends(require_request_auth)])
def google_gmail_smoke_test(
    body: GoogleGmailSmokeTestIn,
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> GoogleGmailSmokeTestOut:
    principal_id = resolve_principal_id(body.principal_id, context)
    try:
        result = run_google_gmail_smoke_test(
            container=container,
            principal_id=principal_id,
            recipient_email=body.recipient_email,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return GoogleGmailSmokeTestOut(
        binding_id=result.binding.binding_id,
        provider_key=result.binding.provider_key,
        principal_id=result.binding.principal_id,
        sender_email=result.sender_email,
        recipient_email=result.recipient_email,
        rfc822_message_id=result.rfc822_message_id,
        gmail_message_id=result.gmail_message_id,
        sent_at=result.sent_at,
    )
