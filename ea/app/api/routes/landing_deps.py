from __future__ import annotations

from fastapi import Request

from app.api.dependencies import (
    RequestContext,
    get_cloudflare_access_identity,
    get_container,
    get_request_context,
    require_operator_context,
)
from app.container import AppContainer
from app.services.cloudflare_access import CloudflareAccessIdentity

__all__ = [
    "AppContainer",
    "CloudflareAccessIdentity",
    "Request",
    "RequestContext",
    "get_cloudflare_access_identity",
    "get_container",
    "get_request_context",
    "require_operator_context",
]
