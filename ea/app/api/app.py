from __future__ import annotations

from fastapi import FastAPI

from app.api.routes.channels import router as channels_router
from app.api.routes.delivery import router as delivery_router
from app.api.routes.health import router as health_router
from app.api.routes.observations import router as observations_router
from app.api.routes.policy import router as policy_router
from app.api.routes.rewrite import router as rewrite_router
from app.settings import get_settings


def create_app() -> FastAPI:
    s = get_settings()
    app = FastAPI(title=s.app_name, version="0.1.0")
    app.include_router(health_router)
    app.include_router(channels_router)
    app.include_router(observations_router)
    app.include_router(delivery_router)
    app.include_router(policy_router)
    app.include_router(rewrite_router)
    return app
