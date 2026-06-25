from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.api.routes import landing_deps as deps
from app.api.routes import landing_console_support as support

router = APIRouter(tags=["landing-console"])


@router.get("/app", response_class=HTMLResponse)
def app_root(request: Request) -> RedirectResponse:
    return support.app_root(request=request)


@router.get("/app/{section}", response_class=HTMLResponse)
def app_shell(
    section: str,
    request: Request,
    container: deps.AppContainer = Depends(deps.get_container),
    context: deps.RequestContext = Depends(deps.get_request_context),
    run_id: str = Query(default=""),
) -> HTMLResponse:
    return support.app_shell(section=section, request=request, container=container, context=context, run_id=run_id)


@router.get("/admin", response_class=HTMLResponse)
def admin_root(_: None = Depends(deps.require_operator_context)) -> RedirectResponse:
    return support.admin_root()


@router.get("/admin/{section}", response_class=HTMLResponse)
def admin_shell(
    section: str,
    request: Request,
    container: deps.AppContainer = Depends(deps.get_container),
    context: deps.RequestContext = Depends(deps.get_request_context),
    _: None = Depends(deps.require_operator_context),
) -> HTMLResponse:
    return support.admin_shell(section=section, request=request, container=container, context=context)


@router.get("/setup")
def legacy_setup_redirect() -> RedirectResponse:
    return support.legacy_setup_redirect()


@router.get("/privacy")
def legacy_privacy_redirect() -> RedirectResponse:
    return support.legacy_privacy_redirect()


@router.get("/demo/brief")
def legacy_brief_redirect() -> RedirectResponse:
    return support.legacy_brief_redirect()


@router.get("/channels/google")
def legacy_google_channel_redirect() -> RedirectResponse:
    return support.legacy_google_channel_redirect()


@router.get("/channels/telegram")
def legacy_telegram_channel_redirect() -> RedirectResponse:
    return support.legacy_telegram_channel_redirect()


@router.get("/channels/whatsapp")
def legacy_whatsapp_channel_redirect() -> RedirectResponse:
    return support.legacy_whatsapp_channel_redirect()


@router.get("/app/commitments/candidates/{candidate_id}", response_class=HTMLResponse)
def commitment_candidate_review(
    candidate_id: str,
    request: Request,
    container: deps.AppContainer = Depends(deps.get_container),
    context: deps.RequestContext = Depends(deps.get_request_context),
) -> HTMLResponse:
    return support.commitment_candidate_review(candidate_id=candidate_id, request=request, container=container, context=context)
