from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from app.api.dependencies import RequestContext, get_container, get_request_context, resolve_principal_id
from app.container import AppContainer

router = APIRouter(prefix="/v1/onboarding", tags=["onboarding"])


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


class OnboardingFinalizeIn(BaseModel):
    principal_id: str | None = Field(default=None, min_length=1, max_length=200)
    retention_mode: str = Field(default="full_bodies", min_length=1, max_length=80)
    metadata_only_channels: list[str] = Field(default_factory=list)
    allow_drafts: bool = Field(default=False)
    allow_action_suggestions: bool = Field(default=True)
    allow_auto_briefs: bool = Field(default=False)


@router.post("/start", response_model=None)
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


@router.get("/status", response_model=None)
def onboarding_status(
    principal_id: str | None = None,
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> dict[str, object]:
    resolved = resolve_principal_id(principal_id, context)
    return container.onboarding.status(principal_id=resolved)


@router.post("/google/start", response_model=None)
def onboarding_google_start(
    body: OnboardingGoogleStartIn,
    request: Request,
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> dict[str, object]:
    principal_id = resolve_principal_id(body.principal_id, context)
    redirect_uri = str(request.url_for("google_oauth_browser_callback"))
    return container.onboarding.start_google(
        principal_id=principal_id,
        scope_bundle=body.scope_bundle,
        redirect_uri_override=redirect_uri,
    )


@router.post("/telegram/start", response_model=None)
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


@router.post("/telegram/link-bot", response_model=None)
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


@router.post("/whatsapp/start-business", response_model=None)
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


@router.post("/whatsapp/import-export", response_model=None)
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


@router.post("/finalize", response_model=None)
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
