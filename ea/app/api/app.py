from __future__ import annotations

import os
import re
from collections.abc import Awaitable, Callable

from fastapi import APIRouter, Depends, FastAPI, Request
from starlette.responses import Response

from app.api.dependencies import require_request_auth
from app.api.errors import install_error_handlers
from app.api.public_http import api_docs_enabled, install_public_http_hardening
from app.api.threadpool_compat import inline_sync_handlers_enabled, install_inline_threadpool_compat
from app.container import build_container
from app.settings import get_settings, validate_startup_settings
from app.api.routes.property_surface_boundary import install_property_surface_boundary


_SOURCE_REVISION_PATTERN = re.compile(r"[0-9a-f]{40}")


def _validated_source_revision(value: object) -> str | None:
    text = str(value or "")
    return text if _SOURCE_REVISION_PATTERN.fullmatch(text) else None


def install_source_revision_header(app: FastAPI) -> None:
    source_revision = _validated_source_revision(os.getenv("EA_SOURCE_REVISION"))
    if source_revision is None:
        return

    @app.middleware("http")
    async def add_source_revision_header(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        response = await call_next(request)
        response.headers["X-EA-Source-Revision"] = source_revision
        return response


async def _prewarm_provider_health_cache() -> None:
    try:
        from app.api.routes.responses import prewarm_provider_health_snapshot_cache

        await prewarm_provider_health_snapshot_cache(lightweight=True)
    except Exception:
        return


def _include_public_routes(
    app: FastAPI,
    *,
    settings,
    audiobook_player_router: APIRouter,
    public_documents_router: APIRouter,
    landing_access_router: APIRouter,
    landing_setup_router: APIRouter,
    landing_actions_router: APIRouter,
    landing_channel_router: APIRouter,
    landing_objects_router: APIRouter,
    landing_workspace_router: APIRouter,
    landing_public_router: APIRouter,
    landing_console_router: APIRouter,
    landing_property_router: APIRouter,
    landing_archive_router: APIRouter,
    fliplink_public_router: APIRouter,
    hedy_meeting_review_router: APIRouter,
    health_router: APIRouter,
    register_router: APIRouter,
) -> None:
    app.include_router(audiobook_player_router)
    app.include_router(public_documents_router)
    app.include_router(landing_access_router)
    app.include_router(landing_setup_router)
    app.include_router(landing_actions_router)
    app.include_router(landing_channel_router)
    app.include_router(landing_objects_router)
    app.include_router(landing_workspace_router)
    app.include_router(landing_public_router)
    app.include_router(landing_console_router)
    app.include_router(landing_property_router)
    app.include_router(fliplink_public_router)
    app.include_router(hedy_meeting_review_router)
    if settings.public_results_enabled:
        from app.api.routes.public_results import router as public_results_router

        app.include_router(public_results_router)
    if settings.public_tours_enabled:
        from app.api.routes.public_tours import router as public_tours_router

        app.include_router(public_tours_router)
    if settings.public_memorials_enabled:
        from app.api.routes.public_memorial_conversation import router as public_memorial_conversation_router
        from app.api.routes.public_memorial_contributions import router as public_memorial_contributions_router
        from app.api.routes.public_memorial_operator import router as public_memorial_operator_router
        from app.api.routes.public_memorial_runtime import router as public_memorial_runtime_router
        from app.api.routes.public_memorial_share import router as public_memorial_share_router
        from app.api.routes.public_memorial_surface import router as public_memorial_surface_router

        app.include_router(public_memorial_surface_router)
        app.include_router(public_memorial_share_router)
        app.include_router(public_memorial_contributions_router)
        app.include_router(public_memorial_conversation_router)
        app.include_router(public_memorial_runtime_router)
        app.include_router(public_memorial_operator_router)
    app.include_router(health_router)
    app.include_router(register_router)
    app.include_router(landing_archive_router)


def _include_authenticated_routes(
    app: FastAPI,
    *,
    auth_dependency: list,
    onboarding_router: APIRouter,
    images_router: APIRouter,
    google_oauth_router: APIRouter,
    providers_router: APIRouter,
    governed_spatial_render_router: APIRouter,
    product_api_delivery_router: APIRouter,
    product_api_workspace_router: APIRouter,
    product_api_router: APIRouter,
    fliplink_authenticated_router: APIRouter,
    human_router: APIRouter,
    runtime_router: APIRouter,
    admin_outreach_router: APIRouter,
    internal_sendr_webhook_router: APIRouter,
) -> None:
    app.include_router(onboarding_router, dependencies=auth_dependency)
    app.include_router(images_router, dependencies=auth_dependency)
    app.include_router(google_oauth_router)
    app.include_router(providers_router, dependencies=auth_dependency)
    app.include_router(governed_spatial_render_router, dependencies=auth_dependency)
    app.include_router(product_api_delivery_router, dependencies=auth_dependency)
    app.include_router(product_api_workspace_router, dependencies=auth_dependency)
    app.include_router(product_api_router, dependencies=auth_dependency)
    app.include_router(fliplink_authenticated_router, dependencies=auth_dependency)
    app.include_router(human_router, dependencies=auth_dependency)
    app.include_router(runtime_router, dependencies=auth_dependency)
    app.include_router(admin_outreach_router, dependencies=auth_dependency)
    app.include_router(internal_sendr_webhook_router, dependencies=auth_dependency)


def _include_legacy_authenticated_routes(
    app: FastAPI,
    *,
    auth_dependency: list,
    channels_router: APIRouter,
    memory_router: APIRouter,
    evidence_router: APIRouter,
    observations_router: APIRouter,
    delivery_router: APIRouter,
    connectors_router: APIRouter,
    policy_router: APIRouter,
    ltd_runtime_router: APIRouter,
    plans_router: APIRouter,
    rewrite_router: APIRouter,
    skills_router: APIRouter,
    task_contracts_router: APIRouter,
    tools_router: APIRouter,
    responses_router: APIRouter,
) -> None:
    app.include_router(channels_router, dependencies=auth_dependency)
    app.include_router(memory_router, dependencies=auth_dependency)
    app.include_router(evidence_router, dependencies=auth_dependency)
    app.include_router(observations_router, dependencies=auth_dependency)
    app.include_router(delivery_router, dependencies=auth_dependency)
    app.include_router(connectors_router, dependencies=auth_dependency)
    app.include_router(policy_router, dependencies=auth_dependency)
    app.include_router(ltd_runtime_router, dependencies=auth_dependency)
    app.include_router(plans_router, dependencies=auth_dependency)
    app.include_router(rewrite_router, dependencies=auth_dependency)
    app.include_router(skills_router, dependencies=auth_dependency)
    app.include_router(task_contracts_router, dependencies=auth_dependency)
    app.include_router(tools_router, dependencies=auth_dependency)
    app.include_router(responses_router, dependencies=auth_dependency)


def create_app() -> FastAPI:
    s = get_settings()
    validate_startup_settings(s)
    if inline_sync_handlers_enabled():
        install_inline_threadpool_compat()
    from app.api.routes.audiobook_player import router as audiobook_player_router
    from app.api.routes.admin_outreach import router as admin_outreach_router
    from app.api.routes.channels import router as channels_router
    from app.api.routes.connectors import router as connectors_router
    from app.api.routes.delivery import router as delivery_router
    from app.api.routes.evidence import router as evidence_router
    from app.api.routes.fliplink_integration import authenticated_router as fliplink_authenticated_router
    from app.api.routes.fliplink_integration import public_router as fliplink_public_router
    from app.api.routes.google_oauth import router as google_oauth_router
    from app.api.routes.governed_spatial_render import router as governed_spatial_render_router
    from app.api.routes.hedy_meeting_review_intake import router as hedy_meeting_review_router
    from app.api.routes.health import router as health_router
    from app.api.routes.images import router as images_router
    from app.api.routes.internal_sendr_webhook import router as internal_sendr_webhook_router
    from app.api.routes.landing_access import router as landing_access_router
    from app.api.routes.landing_actions import router as landing_actions_router
    from app.api.routes.landing_channel import router as landing_channel_router
    from app.api.routes.public_documents import router as public_documents_router
    from app.api.routes.human import router as human_router
    from app.api.routes.landing_console import router as landing_console_router
    from app.api.routes.landing_objects import router as landing_objects_router
    from app.api.routes.landing_property import router as landing_property_router
    from app.api.routes.landing_public import archive_router as landing_archive_router
    from app.api.routes.landing_public import router as landing_public_router
    from app.api.routes.landing_setup import router as landing_setup_router
    from app.api.routes.landing_workspace import router as landing_workspace_router
    from app.api.routes.ltd_runtime import router as ltd_runtime_router
    from app.api.routes.memory import router as memory_router
    from app.api.routes.observations import router as observations_router
    from app.api.routes.onboarding import register_router, router as onboarding_router
    from app.api.routes.plans import router as plans_router
    from app.api.routes.policy import router as policy_router
    from app.api.routes.providers import router as providers_router
    from app.api.routes.product_api import router as product_api_router
    from app.api.routes.product_api_delivery import router as product_api_delivery_router
    from app.api.routes.product_api_workspace import router as product_api_workspace_router
    from app.api.routes.rewrite import router as rewrite_router
    from app.api.routes.runtime import router as runtime_router
    from app.api.routes.skills import router as skills_router
    from app.api.routes.task_contracts import router as task_contracts_router
    from app.api.routes.tools import router as tools_router

    expose_api_docs = api_docs_enabled(runtime_mode=s.runtime_mode)
    app = FastAPI(
        title=s.app_name,
        version=s.app_version,
        docs_url="/api/docs" if expose_api_docs else None,
        redoc_url="/api/redoc" if expose_api_docs else None,
        openapi_url="/openapi.json" if expose_api_docs else None,
    )
    install_source_revision_header(app)
    install_error_handlers(app)
    install_property_surface_boundary(app)
    install_public_http_hardening(app, settings=s)
    app.state.container = build_container(settings=s)
    app.router.on_startup.append(_prewarm_provider_health_cache)
    _include_public_routes(
        app,
        settings=s,
        audiobook_player_router=audiobook_player_router,
        public_documents_router=public_documents_router,
        landing_access_router=landing_access_router,
        landing_setup_router=landing_setup_router,
        landing_actions_router=landing_actions_router,
        landing_channel_router=landing_channel_router,
        landing_objects_router=landing_objects_router,
        landing_workspace_router=landing_workspace_router,
        landing_public_router=landing_public_router,
        landing_console_router=landing_console_router,
        landing_property_router=landing_property_router,
        landing_archive_router=landing_archive_router,
        fliplink_public_router=fliplink_public_router,
        hedy_meeting_review_router=hedy_meeting_review_router,
        health_router=health_router,
        register_router=register_router,
    )
    auth_dependency = [Depends(require_request_auth)]
    _include_authenticated_routes(
        app,
        auth_dependency=auth_dependency,
        onboarding_router=onboarding_router,
        images_router=images_router,
        google_oauth_router=google_oauth_router,
        providers_router=providers_router,
        governed_spatial_render_router=governed_spatial_render_router,
        product_api_delivery_router=product_api_delivery_router,
        product_api_workspace_router=product_api_workspace_router,
        product_api_router=product_api_router,
        fliplink_authenticated_router=fliplink_authenticated_router,
        human_router=human_router,
        runtime_router=runtime_router,
        admin_outreach_router=admin_outreach_router,
        internal_sendr_webhook_router=internal_sendr_webhook_router,
    )
    from app.api.routes.responses import router as responses_router

    if s.legacy_runtime_surfaces_enabled:
        _include_legacy_authenticated_routes(
            app,
            auth_dependency=auth_dependency,
            channels_router=channels_router,
            memory_router=memory_router,
            evidence_router=evidence_router,
            observations_router=observations_router,
            delivery_router=delivery_router,
            connectors_router=connectors_router,
            policy_router=policy_router,
            ltd_runtime_router=ltd_runtime_router,
            plans_router=plans_router,
            rewrite_router=rewrite_router,
            skills_router=skills_router,
            task_contracts_router=task_contracts_router,
            tools_router=tools_router,
            responses_router=responses_router,
        )
    return app
