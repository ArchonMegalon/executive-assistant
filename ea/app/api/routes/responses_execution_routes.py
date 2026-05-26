from __future__ import annotations

from typing import Any, Callable

from fastapi import Depends, Query, Request
from fastapi.responses import JSONResponse
from starlette.responses import Response


def provider_health_response_payload(
    *,
    context: Any,
    safe_provider_health: dict[str, object],
    provider_registry: dict[str, object],
    principal_identity_summary: Callable[[str], dict[str, object]],
) -> dict[str, object]:
    return {
        **safe_provider_health,
        "principal": principal_identity_summary(context.principal_id),
        "provider_registry": provider_registry,
    }


def build_get_provider_health_handler(
    *,
    get_container: Callable[..., Any],
    get_request_context: Callable[..., Any],
    is_operator_context: Callable[[Any], bool],
    provider_health_snapshot_async: Callable[..., Any],
    redacted_provider_health: Callable[..., dict[str, object]],
    provider_health_route_registry_payload: Callable[..., Any],
    principal_identity_summary: Callable[[str], dict[str, object]],
) -> Callable[..., Response]:
    async def get_provider_health(
        *,
        container: Any = Depends(get_container),
        context: Any = Depends(get_request_context),
        lightweight: bool = Query(default=False),
        wait_on_stale: bool = Query(default=False),
    ) -> Response:
        include_sensitive = is_operator_context(context)
        provider_health = await provider_health_snapshot_async(lightweight=lightweight, wait_on_stale=wait_on_stale)
        safe_provider_health = redacted_provider_health(provider_health, include_sensitive=include_sensitive)
        provider_registry = await provider_health_route_registry_payload(
            container=container,
            context=context,
            lightweight=lightweight,
            include_sensitive=include_sensitive,
            safe_provider_health=safe_provider_health,
        )
        return JSONResponse(
            provider_health_response_payload(
                context=context,
                safe_provider_health=safe_provider_health,
                provider_registry=provider_registry,
                principal_identity_summary=principal_identity_summary,
            )
        )

    get_provider_health.__name__ = "get_provider_health"
    get_provider_health.__qualname__ = "get_provider_health"
    return get_provider_health


def build_create_response_handler(
    *,
    get_request_context: Callable[..., Any],
    get_container: Callable[..., Any],
    preferred_onemin_labels_from_request: Callable[[Request], tuple[str, ...]],
    payload_with_request_trace_metadata: Callable[..., dict[str, object]],
    header_codex_profile_from_request: Callable[[Request], str | None],
    run_response_in_executor: Callable[..., Any],
) -> Callable[..., Response]:
    async def create_response(
        payload: dict[str, object],
        *,
        request: Request,
        context: Any = Depends(get_request_context),
        container: object = Depends(get_container),
    ) -> Response:
        preferred_onemin_labels = preferred_onemin_labels_from_request(request)
        normalized_payload = payload_with_request_trace_metadata(payload, request=request)
        header_profile = header_codex_profile_from_request(request)
        return await run_response_in_executor(
            normalized_payload,
            context=context,
            container=container,
            codex_profile=header_profile,
            preferred_onemin_labels=preferred_onemin_labels,
        )

    create_response.__name__ = "create_response"
    create_response.__qualname__ = "create_response"
    return create_response
