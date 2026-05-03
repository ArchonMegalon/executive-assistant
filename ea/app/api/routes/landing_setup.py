from __future__ import annotations

import os
import urllib.parse

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.api.dependencies import CloudflareAccessIdentity, get_cloudflare_access_identity, get_container
from app.api.routes.landing import (
    PUBLIC_NAV,
    _browser_form_context,
    _channel_cards,
    _form_value,
    _form_values,
    _humanize,
    _normalize_browser_return_to,
    _render_public_template,
    _workspace_plan,
)
from app.container import AppContainer
from app.product.service import build_product_service
from app.services.google_oauth import complete_google_oauth_callback, read_google_oauth_state

router = APIRouter(tags=["landing"])


def _public_app_base_url(request: Request) -> str:
    explicit = str(os.environ.get("EA_PUBLIC_APP_BASE_URL") or "").strip().rstrip("/")
    if explicit:
        return explicit
    redirect_uri = str(os.environ.get("EA_GOOGLE_OAUTH_REDIRECT_URI") or "").strip()
    if redirect_uri:
        parsed = urllib.parse.urlparse(redirect_uri)
        if parsed.scheme and parsed.netloc:
            return f"{parsed.scheme}://{parsed.netloc}"
    forwarded = str(request.headers.get("x-forwarded-host") or "").strip()
    forwarded_proto = str(request.headers.get("x-forwarded-proto") or "").strip() or request.url.scheme
    if forwarded:
        return f"{forwarded_proto}://{forwarded}"
    return str(request.base_url).rstrip("/")


def _append_query_value(path: str, **values: str) -> str:
    parsed = urllib.parse.urlparse(path)
    query = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
    for key, value in values.items():
        normalized = str(value or "").strip()
        if normalized:
            query.append((key, normalized))
    updated = urllib.parse.urlencode(query)
    return urllib.parse.urlunparse(parsed._replace(query=updated))


def _google_post_connect_sync(
    *,
    container: AppContainer,
    principal_id: str,
    actor: str,
) -> dict[str, object]:
    product = build_product_service(container)
    try:
        result = product.sync_google_workspace_signals(
            principal_id=principal_id,
            actor=actor,
            email_limit=5,
            calendar_limit=5,
        )
    except Exception as exc:
        return {"status": "failed", "error": str(exc or "google_sync_failed")}
    return {
        "status": "completed",
        "processed_total": int(result.get("total") or 0),
        "synced_total": int(result.get("synced_total") or 0),
        "deduplicated_total": int(result.get("deduplicated_total") or 0),
        "suppressed_total": int(result.get("suppressed_total") or 0),
    }


def _google_sync_detail(sync_result: dict[str, object]) -> str:
    status = str(sync_result.get("status") or "").strip().lower()
    if status != "completed":
        error = str(sync_result.get("error") or "").strip()
        return f"Google is connected, but the first signal sync needs attention: {error or 'google_sync_failed'}."
    processed_total = int(sync_result.get("processed_total") or 0)
    synced_total = int(sync_result.get("synced_total") or 0)
    deduplicated_total = int(sync_result.get("deduplicated_total") or 0)
    suppressed_total = int(sync_result.get("suppressed_total") or 0)
    if processed_total or suppressed_total:
        return (
            f"First signal sync finished. Processed {processed_total} item"
            f"{'' if processed_total == 1 else 's'}, staged {synced_total}, "
            f"deduplicated {deduplicated_total}, suppressed {suppressed_total}."
        )
    return "First signal sync finished. No recent Gmail or Calendar signals were staged yet."


@router.post("/setup/start")
async def setup_start(
    request: Request,
    container: AppContainer = Depends(get_container),
    access_identity: CloudflareAccessIdentity | None = Depends(get_cloudflare_access_identity),
) -> RedirectResponse:
    form_data = urllib.parse.parse_qs((await request.body()).decode("utf-8", errors="ignore"), keep_blank_values=True)
    principal_id = _browser_form_context(form_data=form_data, container=container, access_identity=access_identity)
    container.onboarding.start_workspace(
        principal_id=principal_id,
        workspace_name=_form_value(form_data, "workspace_name", "Executive Workspace"),
        workspace_mode=_form_value(form_data, "workspace_mode", "personal"),
        region=_form_value(form_data, "region", ""),
        language=_form_value(form_data, "language", ""),
        timezone=_form_value(form_data, "timezone", ""),
        selected_channels=_form_values(form_data, "selected_channels"),
    )
    return RedirectResponse("/register", status_code=303)


@router.post("/setup/telegram")
async def setup_telegram(
    request: Request,
    container: AppContainer = Depends(get_container),
    access_identity: CloudflareAccessIdentity | None = Depends(get_cloudflare_access_identity),
) -> RedirectResponse:
    form_data = urllib.parse.parse_qs((await request.body()).decode("utf-8", errors="ignore"), keep_blank_values=True)
    principal_id = _browser_form_context(form_data=form_data, container=container, access_identity=access_identity)
    if not _workspace_plan(container, principal_id=principal_id).entitlements.messaging_channels_enabled:
        return RedirectResponse("/pricing", status_code=303)
    container.onboarding.start_telegram(
        principal_id=principal_id,
        telegram_ref=_form_value(form_data, "telegram_ref", ""),
        identity_mode=_form_value(form_data, "identity_mode", "login_widget"),
        history_mode=_form_value(form_data, "history_mode", "future_only"),
        assistant_surfaces=_form_values(form_data, "assistant_surfaces"),
    )
    return RedirectResponse("/register", status_code=303)


@router.post("/setup/telegram/link-bot")
async def setup_telegram_link_bot(
    request: Request,
    container: AppContainer = Depends(get_container),
    access_identity: CloudflareAccessIdentity | None = Depends(get_cloudflare_access_identity),
) -> RedirectResponse:
    form_data = urllib.parse.parse_qs((await request.body()).decode("utf-8", errors="ignore"), keep_blank_values=True)
    principal_id = _browser_form_context(form_data=form_data, container=container, access_identity=access_identity)
    if not _workspace_plan(container, principal_id=principal_id).entitlements.messaging_channels_enabled:
        return RedirectResponse("/pricing", status_code=303)
    container.onboarding.link_telegram_bot(
        principal_id=principal_id,
        bot_handle=_form_value(form_data, "bot_handle", ""),
        install_surfaces=_form_values(form_data, "install_surfaces"),
        default_chat_ref=_form_value(form_data, "default_chat_ref", ""),
    )
    return RedirectResponse("/register", status_code=303)


@router.post("/setup/whatsapp/business")
async def setup_whatsapp_business(
    request: Request,
    container: AppContainer = Depends(get_container),
    access_identity: CloudflareAccessIdentity | None = Depends(get_cloudflare_access_identity),
) -> RedirectResponse:
    form_data = urllib.parse.parse_qs((await request.body()).decode("utf-8", errors="ignore"), keep_blank_values=True)
    principal_id = _browser_form_context(form_data=form_data, container=container, access_identity=access_identity)
    if not _workspace_plan(container, principal_id=principal_id).entitlements.messaging_channels_enabled:
        return RedirectResponse("/pricing", status_code=303)
    container.onboarding.start_whatsapp_business(
        principal_id=principal_id,
        phone_number=_form_value(form_data, "phone_number", ""),
        business_name=_form_value(form_data, "business_name", ""),
        import_history_now=_form_value(form_data, "import_history_now", "").lower() == "true",
    )
    return RedirectResponse("/register", status_code=303)


@router.post("/setup/whatsapp/export")
async def setup_whatsapp_export(
    request: Request,
    container: AppContainer = Depends(get_container),
    access_identity: CloudflareAccessIdentity | None = Depends(get_cloudflare_access_identity),
) -> RedirectResponse:
    form_data = urllib.parse.parse_qs((await request.body()).decode("utf-8", errors="ignore"), keep_blank_values=True)
    principal_id = _browser_form_context(form_data=form_data, container=container, access_identity=access_identity)
    if not _workspace_plan(container, principal_id=principal_id).entitlements.messaging_channels_enabled:
        return RedirectResponse("/pricing", status_code=303)
    chats = tuple(chunk.strip() for chunk in _form_value(form_data, "selected_chat_labels_csv", "").split(",") if chunk.strip())
    container.onboarding.import_whatsapp_export(
        principal_id=principal_id,
        export_label=_form_value(form_data, "export_label", ""),
        selected_chat_labels=chats,
        include_media=_form_value(form_data, "include_media", "").lower() == "true",
    )
    return RedirectResponse("/register", status_code=303)


@router.post("/setup/finalize")
async def setup_finalize(
    request: Request,
    container: AppContainer = Depends(get_container),
    access_identity: CloudflareAccessIdentity | None = Depends(get_cloudflare_access_identity),
) -> RedirectResponse:
    form_data = urllib.parse.parse_qs((await request.body()).decode("utf-8", errors="ignore"), keep_blank_values=True)
    principal_id = _browser_form_context(form_data=form_data, container=container, access_identity=access_identity)
    container.onboarding.finalize(
        principal_id=principal_id,
        retention_mode=_form_value(form_data, "retention_mode", "full_bodies"),
        metadata_only_channels=_form_values(form_data, "metadata_only_channels"),
        allow_drafts=_form_value(form_data, "allow_drafts", "").lower() == "true",
        allow_action_suggestions=_form_value(form_data, "allow_action_suggestions", "").lower() == "true",
        allow_auto_briefs=_form_value(form_data, "allow_auto_briefs", "").lower() == "true",
        auto_brief_cadence=_form_value(form_data, "auto_brief_cadence", "daily_morning"),
        auto_brief_delivery_time_local=_form_value(form_data, "auto_brief_delivery_time_local", "08:00"),
        auto_brief_quiet_hours_start=_form_value(form_data, "auto_brief_quiet_hours_start", "20:00"),
        auto_brief_quiet_hours_end=_form_value(form_data, "auto_brief_quiet_hours_end", "07:00"),
        auto_brief_recipient_email=_form_value(form_data, "auto_brief_recipient_email", ""),
        auto_brief_delivery_channel=_form_value(form_data, "auto_brief_delivery_channel", "email"),
    )
    return RedirectResponse("/app/today", status_code=303)


@router.post("/google/connect", response_model=None)
async def google_connect_browser(
    request: Request,
    container: AppContainer = Depends(get_container),
    access_identity: CloudflareAccessIdentity | None = Depends(get_cloudflare_access_identity),
) -> RedirectResponse | HTMLResponse:
    form_data = urllib.parse.parse_qs((await request.body()).decode("utf-8", errors="ignore"), keep_blank_values=True)
    principal_id = _browser_form_context(form_data=form_data, container=container, access_identity=access_identity)
    return_to = _normalize_browser_return_to(_form_value(form_data, "return_to", "/get-started"), default="/get-started")
    result = container.onboarding.start_google(
        principal_id=principal_id,
        scope_bundle=_form_value(form_data, "scope_bundle", "core"),
        redirect_uri_override=f"{_public_app_base_url(request)}/google/callback",
        return_to=return_to,
        browser_source="public_setup",
    )
    google_start = dict(result.get("google_start") or {})
    if bool(google_start.get("ready")) and str(google_start.get("auth_url") or "").strip():
        return RedirectResponse(str(google_start["auth_url"]), status_code=303)
    return _render_public_template(
        request,
        "channel_detail.html",
        page_title="Google onboarding status",
        public_nav=PUBLIC_NAV,
        current_nav="integrations",
        access_identity=access_identity,
        principal_id=principal_id,
        status=result,
        workspace=dict(result.get("workspace") or {}),
        channels=dict(result.get("channels") or {}),
        channel_cards=_channel_cards(dict(result.get("channels") or {})),
        selected_channels_label=", ".join(result.get("selected_channels") or []) or "Google Core recommended",
        workspace_mode_label=_humanize(str(dict(result.get("workspace") or {}).get("mode") or "personal")),
        brief_headline=str(dict(result.get("brief_preview") or {}).get("headline") or "Turn your channels into a prioritized day."),
        first_brief_items=[],
        suggested_actions=[],
        trust_notes=[],
        top_contacts=[],
        top_themes=[],
        channel_title="Google onboarding",
        channel_eyebrow="Google",
        channel={"status": google_start.get("detail") or "not_ready", "detail": google_start.get("detail") or "Google onboarding could not start.", "capabilities": [], "limitations": []},
        detail_points=("Google consent could not start on this host.",),
        body_points=("Check OAuth credentials, redirect URI, and provider configuration.",),
    )


@router.get("/google/callback", response_class=HTMLResponse, response_model=None, name="google_oauth_browser_callback")
def google_oauth_browser_callback(
    request: Request,
    code: str,
    state: str,
    container: AppContainer = Depends(get_container),
) -> HTMLResponse | RedirectResponse:
    try:
        state_payload = read_google_oauth_state(state)
        account = complete_google_oauth_callback(container=container, code=code, state=state)
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    product = build_product_service(container)
    product.record_surface_event(
        principal_id=account.binding.principal_id,
        event_type="google_account_connected",
        surface="google_oauth_browser_callback",
        actor=str(account.google_email or account.binding.principal_id or "google_oauth").strip(),
        metadata={
            "binding_id": str(account.binding.binding_id or "").strip(),
            "google_email": str(account.google_email or "").strip(),
            "google_subject": str(account.google_subject or "").strip(),
        },
    )
    sync_result = _google_post_connect_sync(
        container=container,
        principal_id=account.binding.principal_id,
        actor=str(account.google_email or account.binding.principal_id or "google_oauth").strip(),
    )
    browser_source = str(state_payload.get("browser_source") or "").strip()
    return_to = _normalize_browser_return_to(str(state_payload.get("return_to") or ""), default="")
    if browser_source == "settings_google" and return_to:
        redirect_values = {
            "account_status": "account_connected",
            "account_email": account.google_email,
        }
        if str(sync_result.get("status") or "").strip().lower() == "completed":
            redirect_values.update(
                {
                    "sync_status": "completed",
                    "sync_processed_total": str(int(sync_result.get("processed_total") or 0)),
                    "sync_synced_total": str(int(sync_result.get("synced_total") or 0)),
                    "sync_deduplicated_total": str(int(sync_result.get("deduplicated_total") or 0)),
                    "sync_suppressed_total": str(int(sync_result.get("suppressed_total") or 0)),
                }
            )
        else:
            redirect_values["sync_error"] = str(sync_result.get("error") or "google_sync_failed")
        destination = _append_query_value(return_to, **redirect_values)
        return RedirectResponse(destination, status_code=303)
    register_signal_payload: dict[str, object] | None = None
    if return_to.startswith("/register"):
        register_signal_payload = {
            "return_to": return_to,
            "google_connected": True,
            "account_email": account.google_email,
            "sync_status": str(sync_result.get("status") or "").strip(),
            "sync_processed_total": int(sync_result.get("processed_total") or 0),
            "sync_synced_total": int(sync_result.get("synced_total") or 0),
            "sync_deduplicated_total": int(sync_result.get("deduplicated_total") or 0),
            "sync_suppressed_total": int(sync_result.get("suppressed_total") or 0),
            "sync_error": str(sync_result.get("error") or "").strip(),
        }
    return_label = "Back to setup"
    if return_to.startswith("/register"):
        return_label = "Return to registration"
    elif return_to.startswith("/get-started"):
        return_label = "Back to setup"
    elif return_to.startswith("/app/"):
        return_label = "Return to workspace"
    return _render_public_template(
        request,
        "google_connected.html",
        page_title="Google connected",
        public_nav=PUBLIC_NAV,
        current_nav="integrations",
        access_identity=None,
        principal_id=account.binding.principal_id,
        account=account,
        scopes=list(account.granted_scopes),
        return_to=return_to,
        return_label=return_label,
        sync_result=sync_result,
        sync_detail=_google_sync_detail(sync_result),
        register_signal_payload=register_signal_payload,
    )
