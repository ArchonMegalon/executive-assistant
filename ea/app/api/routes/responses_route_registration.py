from __future__ import annotations

from typing import Any, Callable

from fastapi import Depends, Request
from fastapi.routing import APIRouter
from starlette.responses import Response


def register_model_routes(
    *,
    models_router: APIRouter,
    list_models: Callable[..., Response],
    model_list_response_model: type[Any],
) -> None:
    models_router.add_api_route(
        "",
        list_models,
        methods=["GET"],
        response_model=model_list_response_model,
    )


def register_response_item_routes(
    *,
    responses_item_router: APIRouter,
    get_provider_health: Callable[..., Response],
    get_response: Callable[..., Response],
    get_response_input_items: Callable[..., Response],
    create_response: Callable[..., Response],
    response_object_model: type[Any],
    response_input_items_list_model: type[Any],
    streaming_route_responses: dict[int, dict[str, object]],
    request_openapi_extra: dict[str, object],
) -> None:
    responses_item_router.add_api_route(
        "/_provider_health",
        get_provider_health,
        methods=["GET"],
        response_model=None,
    )
    responses_item_router.add_api_route(
        "/{response_id}",
        get_response,
        methods=["GET"],
        response_model=response_object_model,
    )
    responses_item_router.add_api_route(
        "/{response_id}/input_items",
        get_response_input_items,
        methods=["GET"],
        response_model=response_input_items_list_model,
    )
    responses_item_router.add_api_route(
        "",
        create_response,
        methods=["POST"],
        response_model=response_object_model,
        responses=streaming_route_responses,
        openapi_extra=request_openapi_extra,
    )


def build_profiled_codex_route(
    *,
    profile: str,
    route_name: str,
    run_profiled_codex_response: Callable[..., Any],
    get_request_context: Callable[..., Any],
    get_container: Callable[..., Any],
) -> Callable[..., Any]:
    async def _route(
        payload: dict[str, object],
        *,
        request: Request,
        context: Any = Depends(get_request_context),
        container: object = Depends(get_container),
    ) -> Response:
        return await run_profiled_codex_response(
            payload,
            request=request,
            context=context,
            container=container,
            profile=profile,
        )

    _route.__name__ = route_name
    _route.__qualname__ = route_name
    return _route


def register_profiled_codex_routes(
    *,
    codex_router: APIRouter,
    route_specs: tuple[tuple[str, str, str, dict[int, dict[str, object]]], ...],
    run_profiled_codex_response: Callable[..., Any],
    get_request_context: Callable[..., Any],
    get_container: Callable[..., Any],
    response_object_model: type[Any],
    request_openapi_extra: dict[str, object],
    module_globals: dict[str, Any],
) -> None:
    for path, profile, route_name, route_responses in route_specs:
        route = build_profiled_codex_route(
            profile=profile,
            route_name=route_name,
            run_profiled_codex_response=run_profiled_codex_response,
            get_request_context=get_request_context,
            get_container=get_container,
        )
        module_globals[route_name] = route
        codex_router.add_api_route(
            path,
            route,
            methods=["POST"],
            response_model=response_object_model,
            responses=route_responses,
            openapi_extra=request_openapi_extra,
        )


def register_codex_metadata_routes(
    *,
    codex_router: APIRouter,
    list_codex_profiles: Callable[..., Response],
    get_codex_status: Callable[..., Response],
) -> None:
    codex_router.add_api_route(
        "/profiles",
        list_codex_profiles,
        methods=["GET"],
    )
    codex_router.add_api_route(
        "/status",
        get_codex_status,
        methods=["GET"],
    )
