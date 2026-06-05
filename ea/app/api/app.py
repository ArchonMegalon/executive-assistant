from __future__ import annotations

from fastapi import APIRouter, Depends, FastAPI

from app.api.dependencies import require_request_auth
from app.api.errors import install_error_handlers
from app.api.threadpool_compat import inline_sync_handlers_enabled, install_inline_threadpool_compat
from app.container import build_container
from app.settings import get_settings, validate_startup_settings


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
    public_documents_router: APIRouter,
    landing_setup_router: APIRouter,
    landing_actions_router: APIRouter,
    landing_channel_router: APIRouter,
    landing_objects_router: APIRouter,
    landing_workspace_router: APIRouter,
    landing_router: APIRouter,
    fliplink_public_router: APIRouter,
    health_router: APIRouter,
    register_router: APIRouter,
) -> None:
    app.include_router(public_documents_router)
    app.include_router(landing_setup_router)
    app.include_router(landing_actions_router)
    app.include_router(landing_channel_router)
    app.include_router(landing_objects_router)
    app.include_router(landing_workspace_router)
    app.include_router(landing_router)
    app.include_router(fliplink_public_router)
    if settings.public_results_enabled:
        from app.api.routes.public_results import router as public_results_router

        app.include_router(public_results_router)
    if settings.public_tours_enabled:
        from app.api.routes.public_tours import router as public_tours_router

        app.include_router(public_tours_router)
    if settings.public_memorials_enabled:
        from app.api.routes.public_memorials import router as public_memorials_router

        app.include_router(public_memorials_router)
    app.include_router(health_router)
    app.include_router(register_router)


def _include_authenticated_routes(
    app: FastAPI,
    *,
    auth_dependency: list,
    onboarding_router: APIRouter,
    images_router: APIRouter,
    google_oauth_router: APIRouter,
    product_api_delivery_router: APIRouter,
    product_api_workspace_router: APIRouter,
    product_api_router: APIRouter,
    fliplink_authenticated_router: APIRouter,
    runtime_router: APIRouter,
) -> None:
    app.include_router(onboarding_router, dependencies=auth_dependency)
    app.include_router(images_router, dependencies=auth_dependency)
    app.include_router(google_oauth_router)
    app.include_router(product_api_delivery_router, dependencies=auth_dependency)
    app.include_router(product_api_workspace_router, dependencies=auth_dependency)
    app.include_router(product_api_router, dependencies=auth_dependency)
    app.include_router(fliplink_authenticated_router, dependencies=auth_dependency)
    app.include_router(runtime_router, dependencies=auth_dependency)


def _include_legacy_authenticated_routes(
    app: FastAPI,
    *,
    auth_dependency: list,
    channels_router: APIRouter,
    human_router: APIRouter,
    memory_router: APIRouter,
    evidence_router: APIRouter,
    observations_router: APIRouter,
    delivery_router: APIRouter,
    connectors_router: APIRouter,
    policy_router: APIRouter,
    providers_router: APIRouter,
    ltd_runtime_router: APIRouter,
    plans_router: APIRouter,
    rewrite_router: APIRouter,
    skills_router: APIRouter,
    task_contracts_router: APIRouter,
    tools_router: APIRouter,
    responses_router: APIRouter,
) -> None:
    app.include_router(channels_router, dependencies=auth_dependency)
    app.include_router(human_router, dependencies=auth_dependency)
    app.include_router(memory_router, dependencies=auth_dependency)
    app.include_router(evidence_router, dependencies=auth_dependency)
    app.include_router(observations_router, dependencies=auth_dependency)
    app.include_router(delivery_router, dependencies=auth_dependency)
    app.include_router(connectors_router, dependencies=auth_dependency)
    app.include_router(policy_router, dependencies=auth_dependency)
    app.include_router(providers_router, dependencies=auth_dependency)
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
    from app.api.routes.channels import router as channels_router
    from app.api.routes.connectors import router as connectors_router
    from app.api.routes.delivery import router as delivery_router
    from app.api.routes.evidence import router as evidence_router
    from app.api.routes.fliplink_integration import authenticated_router as fliplink_authenticated_router
    from app.api.routes.fliplink_integration import public_router as fliplink_public_router
    from app.api.routes.google_oauth import router as google_oauth_router
    from app.api.routes.health import router as health_router
    from app.api.routes.images import router as images_router
    from app.api.routes.landing_actions import router as landing_actions_router
    from app.api.routes.landing_channel import router as landing_channel_router
    from app.api.routes.public_documents import router as public_documents_router
    from app.api.routes.human import router as human_router
    from app.api.routes.landing import router as landing_router
    from app.api.routes.landing_objects import router as landing_objects_router
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

    app = FastAPI(title=s.app_name, version=s.app_version, docs_url="/api/docs", redoc_url="/api/redoc")
    install_error_handlers(app)
    app.state.container = build_container(settings=s)
    if s.legacy_runtime_surfaces_enabled:
        app.router.on_startup.append(_prewarm_provider_health_cache)
    _include_public_routes(
        app,
        settings=s,
        public_documents_router=public_documents_router,
        landing_setup_router=landing_setup_router,
        landing_actions_router=landing_actions_router,
        landing_channel_router=landing_channel_router,
        landing_objects_router=landing_objects_router,
        landing_workspace_router=landing_workspace_router,
        landing_router=landing_router,
        fliplink_public_router=fliplink_public_router,
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
        product_api_delivery_router=product_api_delivery_router,
        product_api_workspace_router=product_api_workspace_router,
        product_api_router=product_api_router,
        fliplink_authenticated_router=fliplink_authenticated_router,
        runtime_router=runtime_router,
    )
    if s.legacy_runtime_surfaces_enabled:
        from app.api.routes.responses import router as responses_router

        _include_legacy_authenticated_routes(
            app,
            auth_dependency=auth_dependency,
            channels_router=channels_router,
            human_router=human_router,
            memory_router=memory_router,
            evidence_router=evidence_router,
            observations_router=observations_router,
            delivery_router=delivery_router,
            connectors_router=connectors_router,
            policy_router=policy_router,
            providers_router=providers_router,
            ltd_runtime_router=ltd_runtime_router,
            plans_router=plans_router,
            rewrite_router=rewrite_router,
            skills_router=skills_router,
            task_contracts_router=task_contracts_router,
            tools_router=tools_router,
            responses_router=responses_router,
        )
    return app
