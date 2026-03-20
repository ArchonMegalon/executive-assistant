from __future__ import annotations

from fastapi import Depends, FastAPI

from app.api.dependencies import require_request_auth
from app.api.errors import install_error_handlers
from app.api.threadpool_compat import inline_sync_handlers_enabled, install_inline_threadpool_compat
from app.container import build_container
from app.settings import get_settings, validate_startup_settings


def create_app() -> FastAPI:
    s = get_settings()
    validate_startup_settings(s)
    if inline_sync_handlers_enabled():
        install_inline_threadpool_compat()
    from app.api.routes.channels import router as channels_router
    from app.api.routes.connectors import router as connectors_router
    from app.api.routes.delivery import router as delivery_router
    from app.api.routes.evidence import router as evidence_router
    from app.api.routes.google_oauth import router as google_oauth_router
    from app.api.routes.health import router as health_router
    from app.api.routes.human import router as human_router
    from app.api.routes.landing import router as landing_router
    from app.api.routes.memory import router as memory_router
    from app.api.routes.observations import router as observations_router
    from app.api.routes.plans import router as plans_router
    from app.api.routes.policy import router as policy_router
    from app.api.routes.providers import router as providers_router
    from app.api.routes.responses import router as responses_router
    from app.api.routes.rewrite import router as rewrite_router
    from app.api.routes.skills import router as skills_router
    from app.api.routes.task_contracts import router as task_contracts_router
    from app.api.routes.tools import router as tools_router

    app = FastAPI(title=s.app_name, version=s.app_version)
    install_error_handlers(app)
    app.state.container = build_container(settings=s)
    app.include_router(landing_router)
    app.include_router(health_router)
    auth_dependency = [Depends(require_request_auth)]
    app.include_router(channels_router, dependencies=auth_dependency)
    app.include_router(human_router, dependencies=auth_dependency)
    app.include_router(memory_router, dependencies=auth_dependency)
    app.include_router(evidence_router, dependencies=auth_dependency)
    app.include_router(observations_router, dependencies=auth_dependency)
    app.include_router(delivery_router, dependencies=auth_dependency)
    app.include_router(connectors_router, dependencies=auth_dependency)
    app.include_router(google_oauth_router)
    app.include_router(policy_router, dependencies=auth_dependency)
    app.include_router(providers_router, dependencies=auth_dependency)
    app.include_router(plans_router, dependencies=auth_dependency)
    app.include_router(rewrite_router, dependencies=auth_dependency)
    app.include_router(skills_router, dependencies=auth_dependency)
    app.include_router(task_contracts_router, dependencies=auth_dependency)
    app.include_router(tools_router, dependencies=auth_dependency)
    app.include_router(responses_router, dependencies=auth_dependency)
    return app
