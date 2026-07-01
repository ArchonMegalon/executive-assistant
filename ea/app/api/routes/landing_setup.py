from __future__ import annotations

import os
import urllib.parse

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.api.dependencies import CloudflareAccessIdentity, get_cloudflare_access_identity, get_container
from app.api.routes.landing_browser import (
    _browser_form_context,
    _form_value,
    _form_values,
    _normalize_browser_return_to,
)
from app.api.routes.landing_content import PUBLIC_NAV
from app.api.routes.landing_shared_support import _workspace_plan
from app.api.routes.landing_public_support import _render_public_template
from app.api.routes.landing_view_models import channel_cards as _channel_cards
from app.api.routes.landing_view_models import humanize as _humanize
from app.container import AppContainer
from app.product.service import build_product_service
from app.services.public_branding import request_brand
from app.services.public_request import public_base_url
from app.services.public_urls import propertyquarry_public_base_url
from app.services.google_oauth import (
    browser_google_oauth_redirect_uri,
    complete_google_oauth_callback,
    google_bundle_supports_workspace_sync,
    read_google_oauth_state,
    read_google_oauth_state_unchecked,
)
from app.services.proactive_ooda_telegram_approval import resume_latest_telegram_gmail_draft_after_google_connect

router = APIRouter(tags=["landing"])


def _propertyquarry_public_base_url() -> str:
    return propertyquarry_public_base_url()


def _public_app_base_url(request: Request) -> str:
    return public_base_url(
        request,
        explicit_base_url=str(os.environ.get("EA_PUBLIC_APP_BASE_URL") or ""),
        redirect_uri=str(os.environ.get("EA_GOOGLE_OAUTH_REDIRECT_URI") or ""),
    )


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
    granted_scopes: tuple[str, ...] | list[str] = (),
) -> dict[str, object]:
    if not google_bundle_supports_workspace_sync(scopes=tuple(granted_scopes)):
        return {"status": "identity_only"}
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
    if status == "identity_only":
        return "Google account linking is complete. No Gmail or Calendar sync was requested for this workspace."
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


def _render_google_oauth_callback_failure(
    request: Request,
    *,
    detail: str,
    status_code: int,
) -> HTMLResponse:
    response = _render_public_template(
        request,
        "channel_detail.html",
        page_title="Google connection needs attention",
        public_nav=PUBLIC_NAV,
        current_nav="integrations",
        access_identity=None,
        principal_id="",
        channel_title="Google connection",
        channel_eyebrow="Google",
        channel={
            "status": "needs_attention",
            "detail": detail or "Google connection could not be completed on this host.",
            "capabilities": [],
            "limitations": [],
        },
        detail_points=(
            "The OAuth callback did not complete cleanly.",
            "Retry the consent flow from the latest setup page if this was an expired or cancelled sign-in.",
        ),
        body_points=(
            "PropertyQuarry keeps the browser callback fail-closed and should show the real blocker instead of a blank gateway error.",
            "If this persists, check the Google OAuth credentials, redirect URI, and provider availability for propertyquarry.com.",
        ),
    )
    response.status_code = status_code
    return response


def _google_oauth_denial_detail(
    *,
    error: str,
    error_description: str = "",
    state_payload: dict[str, object] | None = None,
) -> str:
    normalized_error = str(error or "").strip()
    detail = str(error_description or normalized_error or "google_oauth_denied").strip()
    if normalized_error != "access_denied":
        return detail
    payload = dict(state_payload or {})
    if str(payload.get("oauth_lane") or "").strip() == "google_location_history":
        return (
            "Google denied the Data Portability consent. "
            "Typical causes are: the account is not allowed as an OAuth test user, "
            "the Data Portability scope is not approved for this client, or the consent was cancelled."
        )
    expected_google_email = str(payload.get("expected_google_email") or "").strip().lower()
    account_detail = f" for {expected_google_email}" if "@" in expected_google_email else ""
    oauth_project_id = str(payload.get("oauth_client_project_id") or "").strip()
    oauth_project_number = str(payload.get("oauth_client_project_number") or "").strip()
    project_detail = ""
    if oauth_project_id and oauth_project_number:
        project_detail = f" OAuth project: {oauth_project_id} ({oauth_project_number})."
    elif oauth_project_id:
        project_detail = f" OAuth project: {oauth_project_id}."
    elif oauth_project_number:
        project_detail = f" OAuth project number: {oauth_project_number}."
    action_detail = (
        f" Add {expected_google_email} under Google Auth Platform > Audience > Test users, "
        "or publish/verify the OAuth app, then retry the Full Workspace link."
        if "@" in expected_google_email
        else " Add the selected Google account under Google Auth Platform > Audience > Test users, "
        "or publish/verify the OAuth app, then retry the Full Workspace link."
    )
    google_detail = f" Google said: {detail}." if detail else ""
    return (
        f"Google denied OAuth access{account_detail}. "
        f"{google_detail} "
        "If the consent screen says the app is still being tested, add this account as a Google OAuth test user "
        f"for myexternalbrain.com or publish the OAuth app after Google verification, then retry the Full Workspace link."
        f"{project_detail}{action_detail}"
    )


def _record_google_oauth_denial_observation(
    *,
    container: AppContainer,
    state_payload: dict[str, object],
    error: str,
    error_description: str,
) -> None:
    principal_id = str(state_payload.get("principal_id") or "").strip()
    if not principal_id:
        return
    normalized_error = str(error or "").strip()
    expected_google_email = str(state_payload.get("expected_google_email") or "").strip().lower()
    denial_reason = (
        "oauth_test_user_or_verification_required" if normalized_error == "access_denied" else "google_oauth_denied"
    )
    try:
        build_product_service(container).record_surface_event(
            principal_id=principal_id,
            event_type="google_oauth_access_denied",
            surface="google_oauth_browser_callback",
            actor=expected_google_email or principal_id,
            metadata={
                "error": normalized_error,
                "error_description": str(error_description or "").strip(),
                "denial_reason": denial_reason,
                "expected_google_email": expected_google_email,
                "scope_bundle": str(state_payload.get("scope_bundle") or "").strip(),
                "oauth_client_project_id": str(state_payload.get("oauth_client_project_id") or "").strip(),
                "oauth_client_project_number": str(state_payload.get("oauth_client_project_number") or "").strip(),
                "raw_google_code_received": False,
            },
        )
    except Exception:
        pass


@router.post("/setup/start")
async def setup_start(
    request: Request,
    container: AppContainer = Depends(get_container),
    access_identity: CloudflareAccessIdentity | None = Depends(get_cloudflare_access_identity),
) -> RedirectResponse:
    form_data = urllib.parse.parse_qs((await request.body()).decode("utf-8", errors="ignore"), keep_blank_values=True)
    principal_id = _browser_form_context(form_data=form_data, container=container, access_identity=access_identity)
    workspace_name = _form_value(form_data, "workspace_name", "PropertyQuarry Workspace")
    container.onboarding.start_workspace(
        principal_id=principal_id,
        workspace_name=workspace_name,
        workspace_mode=_form_value(form_data, "workspace_mode", "personal"),
        region=_form_value(form_data, "region", ""),
        language=_form_value(form_data, "language", ""),
        timezone=_form_value(form_data, "timezone", ""),
        selected_channels=_form_values(form_data, "selected_channels"),
    )
    if request_brand(request)["key"] == "ea":
        target = "/app/today?activation=workspace_created"
        if access_identity is not None:
            return RedirectResponse(target, status_code=303)
        access = build_product_service(container).issue_workspace_access_session(
            principal_id=principal_id,
            email=str(getattr(access_identity, "email", "") or "").strip().lower(),
            role="principal",
            display_name=workspace_name,
            source_kind="browser_setup",
            default_target=target,
        )
        return RedirectResponse(str(access.get("access_url") or target), status_code=303)
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
    return RedirectResponse("/app/properties", status_code=303)


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
        scope_bundle=_form_value(form_data, "scope_bundle", "identity"),
        redirect_uri_override=browser_google_oauth_redirect_uri(public_base_url=_public_app_base_url(request)),
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
        selected_channels_label=", ".join(result.get("selected_channels") or []) or "Google sign-in recommended",
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
    code: str = "",
    state: str = "",
    error: str = "",
    error_description: str = "",
    container: AppContainer = Depends(get_container),
) -> HTMLResponse | RedirectResponse:
    if str(error or "").strip():
        try:
            state_payload = read_google_oauth_state(state) if str(state or "").strip() else {}
        except Exception:
            state_payload = {}
        _record_google_oauth_denial_observation(
            container=container,
            state_payload=state_payload,
            error=error,
            error_description=error_description,
        )
        detail = _google_oauth_denial_detail(
            error=error,
            error_description=error_description,
            state_payload=state_payload,
        )
        return _render_google_oauth_callback_failure(request, detail=detail, status_code=400)
    if not str(code or "").strip() or not str(state or "").strip():
        return _render_google_oauth_callback_failure(
            request,
            detail="Google did not return a valid OAuth code and state.",
            status_code=400,
        )
    try:
        state_payload = read_google_oauth_state(state)
        product = build_product_service(container)
        if str(state_payload.get("oauth_lane") or "").strip() == "google_location_history":
            connected = product.complete_google_location_history_connect(code=code, state=state)
            try:
                sync_result = product.sync_google_location_history_portability(
                    principal_id=str(connected.get("principal_id") or "").strip(),
                    actor=str(connected.get("google_email") or connected.get("principal_id") or "google_location_history").strip(),
                )
            except Exception as exc:
                sync_result = {"state": "FAILED", "error": str(exc or "google_location_history_sync_failed")}
            return _render_public_template(
                request,
                "channel_detail.html",
                page_title="Google Location History connected",
                public_nav=PUBLIC_NAV,
                current_nav="integrations",
                access_identity=None,
                principal_id=str(connected.get("principal_id") or "").strip(),
                channel_title="Google Location History",
                channel_eyebrow="Google",
                channel={
                    "status": "connected",
                    "detail": (
                        "Location History connected. "
                        f"Initial sync state: {str(sync_result.get('state') or 'UNKNOWN').strip()}."
                    ),
                    "capabilities": [
                        "Maps Timeline export",
                        "Pocket recording location matching",
                        "Hospital/place search for archived audio",
                    ],
                    "limitations": [],
                },
                detail_points=(
                    f"Connected account: {str(connected.get('google_email') or '').strip()}",
                    f"Initial archive job: {str(sync_result.get('archive_job_id') or '').strip() or 'none'}",
                    f"Imported locations this pass: {int(sync_result.get('imported_total') or 0)}",
                ),
                body_points=(
                    "EA will continue using this lane for automatic Pocket/Timeline matching.",
                    "You can close this page.",
                ),
            )
        account = complete_google_oauth_callback(container=container, code=code, state=state)
    except RuntimeError as exc:
        detail = str(exc or "google_oauth_callback_failed")
        if detail == "google_oauth_state_expired" and str(state or "").strip():
            try:
                expired_state = read_google_oauth_state_unchecked(state)
            except Exception:
                expired_state = {}
            return_to = _normalize_browser_return_to(str(expired_state.get("return_to") or ""), default="")
            if return_to:
                separator = "&" if "?" in return_to else "?"
                return RedirectResponse(
                    f"{return_to}{separator}google_error=google_oauth_state_expired",
                    status_code=303,
                )
        return _render_google_oauth_callback_failure(request, detail=detail, status_code=400)
    except Exception as exc:
        return _render_google_oauth_callback_failure(request, detail=str(exc or "google_oauth_callback_failed"), status_code=502)
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
    if str(account.consent_stage or "").strip().lower() != "identity":
        try:
            resume_latest_telegram_gmail_draft_after_google_connect(
                container=container,
                principal_id=account.binding.principal_id,
            )
        except Exception:
            pass
    sync_result = _google_post_connect_sync(
        container=container,
        principal_id=account.binding.principal_id,
        actor=str(account.google_email or account.binding.principal_id or "google_oauth").strip(),
        granted_scopes=account.granted_scopes,
    )
    browser_source = str(state_payload.get("browser_source") or "").strip()
    return_to = _normalize_browser_return_to(str(state_payload.get("return_to") or ""), default="")
    if browser_source == "sign_in":
        onboarding_status = container.onboarding.status(principal_id=account.binding.principal_id)
        workspace_name = str(dict(onboarding_status.get("workspace") or {}).get("name") or "").strip() or str(
            account.google_email or account.binding.principal_id or "PropertyQuarry"
        ).strip()
        access = product.issue_workspace_access_session(
            principal_id=account.binding.principal_id,
            email=account.google_email,
            role="principal",
            display_name=workspace_name,
            source_kind="google_sign_in",
            default_target="/app/properties",
        )
        return RedirectResponse(str(access.get("access_url") or "/app/properties"), status_code=303)
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
        elif str(sync_result.get("status") or "").strip().lower() == "identity_only":
            redirect_values["sync_error"] = "google_identity_only"
        else:
            redirect_values["sync_error"] = str(sync_result.get("error") or "google_sync_failed")
        destination = _append_query_value(return_to, **redirect_values)
        return RedirectResponse(destination, status_code=303)
    register_signal_payload: dict[str, object] | None = None
    if return_to.startswith("/register"):
        register_return_to = f"{_propertyquarry_public_base_url()}{return_to}"
        register_signal_payload = {
            "return_to": register_return_to,
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
        propertyquarry_register_ready_url=f"{_propertyquarry_public_base_url()}/register?ready=1",
    )
