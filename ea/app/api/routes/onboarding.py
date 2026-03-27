from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from app.api.dependencies import RequestContext, get_container, get_request_context, resolve_principal_id
from app.container import AppContainer
from app.product.service import build_product_service
from app.services.google_oauth import (
    complete_google_oauth_callback,
    GOOGLE_PROVIDER_KEY,
)
from app.services.registration_email import send_registration_email

router = APIRouter(prefix="/v1/onboarding", tags=["onboarding"])
register_router = APIRouter(prefix="/v1/register", tags=["registration"])


def _registration_secret(container: AppContainer) -> str:
    runtime_mode = str(getattr(getattr(container.settings, "runtime", None), "mode", "dev") or "dev").strip().lower()
    api_token = str(getattr(getattr(container.settings, "auth", None), "api_token", "") or "").strip()
    default_principal = str(getattr(getattr(container.settings, "auth", None), "default_principal_id", "") or "").strip()
    return f"register:{runtime_mode}:{api_token or default_principal or 'local-user'}"


def _urlsafe_b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _urlsafe_b64decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(f"{value}{padding}")


def _sign_registration_payload(*, container: AppContainer, payload: dict[str, object]) -> str:
    encoded = _urlsafe_b64encode(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8"))
    signature = hmac.new(
        _registration_secret(container).encode("utf-8"),
        encoded.encode("utf-8"),
        hashlib.sha256,
    ).digest()
    return f"{encoded}.{_urlsafe_b64encode(signature)}"


def _verify_registration_payload(*, container: AppContainer, token: str) -> dict[str, object] | None:
    encoded, dot, provided_signature = str(token or "").partition(".")
    if not encoded or not dot or not provided_signature:
        return None
    expected_signature = _urlsafe_b64encode(
        hmac.new(
            _registration_secret(container).encode("utf-8"),
            encoded.encode("utf-8"),
            hashlib.sha256,
        ).digest()
    )
    if not hmac.compare_digest(provided_signature, expected_signature):
        return None
    try:
        payload = json.loads(_urlsafe_b64decode(encoded).decode("utf-8"))
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    expires_at = int(payload.get("expires_at") or 0)
    if expires_at <= int(time.time()):
        return None
    return payload


def _registration_principal_id(email: str) -> str:
    normalized = str(email or "").strip().lower()
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]
    return f"user-{digest}"


def _workspace_name_from_email(email: str) -> str:
    local = str(email or "").strip().split("@", 1)[0].replace(".", " ").replace("_", " ").replace("-", " ").strip()
    return " ".join(part.capitalize() for part in local.split() if part) or "Personal Workspace"


def _registration_base_url(request: Request) -> str:
    explicit = str(os.environ.get("EA_PUBLIC_APP_BASE_URL") or "").strip().rstrip("/")
    if explicit:
        return explicit
    redirect_uri = str(os.environ.get("EA_GOOGLE_OAUTH_REDIRECT_URI") or "").strip()
    if redirect_uri:
        parsed = urlparse(redirect_uri)
        if parsed.scheme and parsed.netloc:
            return f"{parsed.scheme}://{parsed.netloc}"
    return str(request.base_url).rstrip("/")


class RegisterStartIn(BaseModel):
    email: str = Field(min_length=3, max_length=320)


class RegisterStartOut(BaseModel):
    email: str
    verification_token: str
    verification_code: str = ""
    magic_link_url: str
    expires_at: int
    workspace_name: str
    suggested_timezone: str = "UTC"
    suggested_language: str = "en"
    email_delivery_status: str = ""
    email_delivery_provider: str = ""
    email_delivery_id: str = ""
    email_delivery_error: str = ""


class RegisterVerifyIn(BaseModel):
    verification_token: str = Field(min_length=1)
    verification_code: str = Field(default="", max_length=12)
    workspace_name: str = Field(default="", max_length=200)
    timezone: str = Field(default="", max_length=80)
    language: str = Field(default="", max_length=80)
    scope_bundle: str = Field(default="core", max_length=50)


class RegisterVerifyOut(BaseModel):
    model_config = ConfigDict(extra="allow")

    principal_id: str = ""
    status: str = ""
    workspace: dict[str, object] = Field(default_factory=dict)
    selected_channels: list[str] = Field(default_factory=list)
    privacy: dict[str, object] = Field(default_factory=dict)
    assistant_modes: list[dict[str, object]] = Field(default_factory=list)
    featured_domains: list[dict[str, object]] = Field(default_factory=list)
    storage_posture: dict[str, object] = Field(default_factory=dict)
    channels: dict[str, object] = Field(default_factory=dict)
    brief_preview: dict[str, object] = Field(default_factory=dict)
    next_step: str = ""
    onboarding_id: str = ""
    access_url: str = ""
    access_token: str = ""
    access_expires_at: str = ""
    google_start: dict[str, object] = Field(default_factory=dict)


class OnboardingStartIn(BaseModel):
    principal_id: str | None = Field(default=None, min_length=1, max_length=200)
    workspace_name: str = Field(min_length=1, max_length=200)
    workspace_mode: str = Field(default="personal", min_length=1, max_length=50)
    region: str = Field(default="", max_length=80)
    language: str = Field(default="", max_length=80)
    timezone: str = Field(default="", max_length=80)
    selected_channels: list[str] = Field(default_factory=list)


class OnboardingGoogleStartIn(BaseModel):
    principal_id: str | None = Field(default=None, min_length=1, max_length=200)
    scope_bundle: str = Field(default="core", min_length=1, max_length=50)


class OnboardingTelegramStartIn(BaseModel):
    principal_id: str | None = Field(default=None, min_length=1, max_length=200)
    telegram_ref: str = Field(default="", max_length=200)
    identity_mode: str = Field(default="login_widget", min_length=1, max_length=80)
    history_mode: str = Field(default="future_only", min_length=1, max_length=80)
    assistant_surfaces: list[str] = Field(default_factory=list)


class OnboardingTelegramBotIn(BaseModel):
    principal_id: str | None = Field(default=None, min_length=1, max_length=200)
    bot_handle: str = Field(min_length=1, max_length=200)
    install_surfaces: list[str] = Field(default_factory=list)
    default_chat_ref: str = Field(default="", max_length=200)


class OnboardingWhatsappBusinessIn(BaseModel):
    principal_id: str | None = Field(default=None, min_length=1, max_length=200)
    phone_number: str = Field(min_length=1, max_length=80)
    business_name: str = Field(default="", max_length=200)
    import_history_now: bool = Field(default=False)


class OnboardingWhatsappExportIn(BaseModel):
    principal_id: str | None = Field(default=None, min_length=1, max_length=200)
    export_label: str = Field(min_length=1, max_length=200)
    selected_chat_labels: list[str] = Field(default_factory=list)
    include_media: bool = Field(default=False)


class OnboardingWhatsappExportAckIn(BaseModel):
    principal_id: str | None = Field(default=None, min_length=1, max_length=200)
    binding_id: str = Field(min_length=1, max_length=200)
    imported_message_count: int = Field(default=0, ge=0)
    status: str = Field(default="imported", min_length=1, max_length=80)


class OnboardingFinalizeIn(BaseModel):
    principal_id: str | None = Field(default=None, min_length=1, max_length=200)
    retention_mode: str = Field(default="full_bodies", min_length=1, max_length=80)
    metadata_only_channels: list[str] = Field(default_factory=list)
    allow_drafts: bool = Field(default=False)
    allow_action_suggestions: bool = Field(default=True)
    allow_auto_briefs: bool = Field(default=False)


class OnboardingEnvelopeOut(BaseModel):
    model_config = ConfigDict(extra="allow")

    principal_id: str = ""
    status: str = ""
    workspace: dict[str, object] = Field(default_factory=dict)
    selected_channels: list[str] = Field(default_factory=list)
    privacy: dict[str, object] = Field(default_factory=dict)
    assistant_modes: list[dict[str, object]] = Field(default_factory=list)
    featured_domains: list[dict[str, object]] = Field(default_factory=list)
    storage_posture: dict[str, object] = Field(default_factory=dict)
    channels: dict[str, object] = Field(default_factory=dict)
    brief_preview: dict[str, object] = Field(default_factory=dict)
    next_step: str = ""
    onboarding_id: str = ""


class OnboardingStartOut(OnboardingEnvelopeOut):
    pass


class OnboardingGoogleStartOut(OnboardingEnvelopeOut):
    google_start: dict[str, object] = Field(default_factory=dict)


class OnboardingTelegramStartOut(OnboardingEnvelopeOut):
    telegram_start: dict[str, object] = Field(default_factory=dict)


class OnboardingTelegramBotOut(OnboardingEnvelopeOut):
    telegram_bot: dict[str, object] = Field(default_factory=dict)


class OnboardingWhatsappBusinessOut(OnboardingEnvelopeOut):
    whatsapp_business: dict[str, object] = Field(default_factory=dict)


class OnboardingWhatsappExportOut(OnboardingEnvelopeOut):
    whatsapp_export: dict[str, object] = Field(default_factory=dict)


class OnboardingWhatsappExportAckOut(OnboardingEnvelopeOut):
    whatsapp_export: dict[str, object] = Field(default_factory=dict)


class OnboardingCallbackOut(BaseModel):
    provider_key: str
    principal_id: str
    binding_id: str
    connector_binding_id: str
    google_email: str
    google_subject: str
    google_hosted_domain: str
    granted_scopes: list[str]
    consent_stage: str
    workspace_mode: str
    token_status: str
    last_refresh_at: str
    reauth_required_reason: str


def _google_callback_payload(account) -> dict[str, object]:
    return {
        "provider_key": GOOGLE_PROVIDER_KEY,
        "principal_id": account.binding.principal_id,
        "binding_id": account.binding.binding_id,
        "connector_binding_id": account.connector_binding.binding_id if account.connector_binding is not None else "",
        "google_email": account.google_email,
        "google_subject": account.google_subject,
        "google_hosted_domain": account.google_hosted_domain,
        "granted_scopes": list(account.granted_scopes),
        "consent_stage": account.consent_stage,
        "workspace_mode": account.workspace_mode,
        "token_status": account.token_status,
        "last_refresh_at": account.last_refresh_at,
        "reauth_required_reason": account.reauth_required_reason,
    }


def _complete_onboarding_google_callback(
    code: str = Query(..., min_length=1),
    state: str = Query(..., min_length=1),
    container: AppContainer = Depends(get_container),
) -> dict[str, object]:
    try:
        account = complete_google_oauth_callback(container=container, code=code, state=state)
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _google_callback_payload(account)


@router.get("/google/callback", response_model=OnboardingCallbackOut)
def onboarding_google_callback_get(
    code: str = Query(..., min_length=1),
    state: str = Query(..., min_length=1),
    container: AppContainer = Depends(get_container),
) -> dict[str, object]:
    return _complete_onboarding_google_callback(code=code, state=state, container=container)


@router.post("/google/callback", response_model=OnboardingCallbackOut)
def onboarding_google_callback_post(
    code: str = Query(..., min_length=1),
    state: str = Query(..., min_length=1),
    container: AppContainer = Depends(get_container),
) -> dict[str, object]:
    return _complete_onboarding_google_callback(code=code, state=state, container=container)


@register_router.post("/start", response_model=RegisterStartOut)
def register_start(
    body: RegisterStartIn,
    container: AppContainer = Depends(get_container),
    request: Request = None,
) -> RegisterStartOut:
    product = build_product_service(container)
    email = str(body.email or "").strip().lower()
    if "@" not in email or "." not in email.rsplit("@", 1)[-1]:
        raise HTTPException(status_code=400, detail="registration_email_invalid")
    expires_at = int(time.time()) + 15 * 60
    verification_code = f"{secrets.randbelow(1_000_000):06d}"
    verification_token = _sign_registration_payload(
        container=container,
        payload={
            "token_kind": "register_challenge",
            "email": email,
            "verification_code": verification_code,
            "expires_at": expires_at,
        },
    )
    runtime_mode = str(getattr(getattr(container.settings, "runtime", None), "mode", "dev") or "dev").strip().lower()
    magic_link_url = f"/register?token={verification_token}&code={verification_code}"
    email_delivery_status = ""
    email_delivery_provider = ""
    email_delivery_id = ""
    email_delivery_error = ""
    if str(os.environ.get("EMAILIT_API_KEY") or "").strip():
        try:
            receipt = send_registration_email(
                recipient_email=email,
                verification_code=verification_code,
                magic_link_url=f"{_registration_base_url(request)}{magic_link_url}",
                expires_at=expires_at,
            )
            email_delivery_status = "sent"
            email_delivery_provider = receipt.provider
            email_delivery_id = receipt.message_id
            product.record_surface_event(
                principal_id=_registration_principal_id(email),
                event_type="registration_email_sent",
                surface="register_start",
                actor=email,
                metadata={"email": email},
            )
        except RuntimeError as exc:
            email_delivery_status = "failed"
            email_delivery_error = str(exc) or "registration_email_send_failed"
            product.record_surface_event(
                principal_id=_registration_principal_id(email),
                event_type="registration_email_failed",
                surface="register_start",
                actor=email,
                metadata={"email": email, "error": email_delivery_error},
            )
    return RegisterStartOut(
        email=email,
        verification_token=verification_token,
        verification_code="" if runtime_mode == "prod" else verification_code,
        magic_link_url=magic_link_url,
        expires_at=expires_at,
        workspace_name=_workspace_name_from_email(email),
        suggested_timezone="Europe/Vienna",
        suggested_language="en",
        email_delivery_status=email_delivery_status,
        email_delivery_provider=email_delivery_provider,
        email_delivery_id=email_delivery_id,
        email_delivery_error=email_delivery_error,
    )


@register_router.post("/verify", response_model=RegisterVerifyOut)
def register_verify(
    body: RegisterVerifyIn,
    container: AppContainer = Depends(get_container),
) -> dict[str, object]:
    payload = _verify_registration_payload(container=container, token=body.verification_token)
    if payload is None or str(payload.get("token_kind") or "").strip() != "register_challenge":
        raise HTTPException(status_code=400, detail="registration_verification_invalid")
    expected_code = str(payload.get("verification_code") or "").strip()
    provided_code = str(body.verification_code or "").strip()
    if not provided_code or provided_code != expected_code:
        raise HTTPException(status_code=400, detail="registration_verification_code_invalid")
    email = str(payload.get("email") or "").strip().lower()
    principal_id = _registration_principal_id(email)
    workspace_name = str(body.workspace_name or "").strip() or _workspace_name_from_email(email)
    language = str(body.language or "").strip() or "en"
    timezone = str(body.timezone or "").strip() or "Europe/Vienna"
    status = container.onboarding.start_workspace(
        principal_id=principal_id,
        workspace_name=workspace_name,
        workspace_mode="personal",
        region="",
        language=language,
        timezone=timezone,
        selected_channels=("google",),
    )
    google_start: dict[str, object] = {}
    try:
        google_status = container.onboarding.start_google(
            principal_id=principal_id,
            scope_bundle=str(body.scope_bundle or "core").strip() or "core",
        )
        google_start = dict(google_status.get("google_start") or {})
        status = google_status
    except RuntimeError as exc:
        google_start = {"error": str(exc or "google_oauth_not_ready")}
    access = build_product_service(container).issue_workspace_access_session(
        principal_id=principal_id,
        email=email,
        role="principal",
        display_name=workspace_name,
        source_kind="register",
    )
    return {
        **status,
        "google_start": google_start,
        "access_url": str(access.get("access_url") or "").strip(),
        "access_token": str(access.get("access_token") or "").strip(),
        "access_expires_at": str(access.get("expires_at") or "").strip(),
    }


@router.post("/start", response_model=OnboardingStartOut)
def onboarding_start(
    body: OnboardingStartIn,
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> dict[str, object]:
    principal_id = resolve_principal_id(body.principal_id, context)
    return container.onboarding.start_workspace(
        principal_id=principal_id,
        workspace_name=body.workspace_name,
        workspace_mode=body.workspace_mode,
        region=body.region,
        language=body.language,
        timezone=body.timezone,
        selected_channels=tuple(body.selected_channels),
    )


@router.get("/status", response_model=OnboardingStartOut)
def onboarding_status(
    principal_id: str | None = None,
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> dict[str, object]:
    resolved = resolve_principal_id(principal_id, context)
    return container.onboarding.status(principal_id=resolved)


@router.post("/google/start", response_model=OnboardingGoogleStartOut)
def onboarding_google_start(
    body: OnboardingGoogleStartIn,
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> dict[str, object]:
    principal_id = resolve_principal_id(body.principal_id, context)
    return container.onboarding.start_google(
        principal_id=principal_id,
        scope_bundle=body.scope_bundle,
    )


@router.post("/telegram/start", response_model=OnboardingTelegramStartOut)
def onboarding_telegram_start(
    body: OnboardingTelegramStartIn,
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> dict[str, object]:
    principal_id = resolve_principal_id(body.principal_id, context)
    return container.onboarding.start_telegram(
        principal_id=principal_id,
        telegram_ref=body.telegram_ref,
        identity_mode=body.identity_mode,
        history_mode=body.history_mode,
        assistant_surfaces=tuple(body.assistant_surfaces),
    )


@router.post("/telegram/link-bot", response_model=OnboardingTelegramBotOut)
def onboarding_telegram_link_bot(
    body: OnboardingTelegramBotIn,
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> dict[str, object]:
    principal_id = resolve_principal_id(body.principal_id, context)
    return container.onboarding.link_telegram_bot(
        principal_id=principal_id,
        bot_handle=body.bot_handle,
        install_surfaces=tuple(body.install_surfaces),
        default_chat_ref=body.default_chat_ref,
    )


@router.post("/whatsapp/start-business", response_model=OnboardingWhatsappBusinessOut)
def onboarding_whatsapp_start_business(
    body: OnboardingWhatsappBusinessIn,
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> dict[str, object]:
    principal_id = resolve_principal_id(body.principal_id, context)
    return container.onboarding.start_whatsapp_business(
        principal_id=principal_id,
        phone_number=body.phone_number,
        business_name=body.business_name,
        import_history_now=body.import_history_now,
    )


@router.post("/whatsapp/import-export", response_model=OnboardingWhatsappExportOut)
def onboarding_whatsapp_import_export(
    body: OnboardingWhatsappExportIn,
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> dict[str, object]:
    principal_id = resolve_principal_id(body.principal_id, context)
    return container.onboarding.import_whatsapp_export(
        principal_id=principal_id,
        export_label=body.export_label,
        selected_chat_labels=tuple(body.selected_chat_labels),
        include_media=body.include_media,
    )


@router.post("/whatsapp/import-export/ack", response_model=OnboardingWhatsappExportAckOut)
def onboarding_whatsapp_import_export_ack(
    body: OnboardingWhatsappExportAckIn,
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> dict[str, object]:
    principal_id = resolve_principal_id(body.principal_id, context)
    return container.onboarding.acknowledge_whatsapp_export_import(
        principal_id=principal_id,
        binding_id=body.binding_id,
        imported_message_count=body.imported_message_count,
        status=body.status,
    )


@router.post("/finalize", response_model=OnboardingStartOut)
def onboarding_finalize(
    body: OnboardingFinalizeIn,
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> dict[str, object]:
    principal_id = resolve_principal_id(body.principal_id, context)
    return container.onboarding.finalize(
        principal_id=principal_id,
        retention_mode=body.retention_mode,
        metadata_only_channels=tuple(body.metadata_only_channels),
        allow_drafts=body.allow_drafts,
        allow_action_suggestions=body.allow_action_suggestions,
        allow_auto_briefs=body.allow_auto_briefs,
    )
