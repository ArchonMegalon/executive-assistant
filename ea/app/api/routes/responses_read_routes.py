from __future__ import annotations

from typing import Any, Callable

from fastapi import Depends, Request
from fastapi.responses import JSONResponse
from starlette.responses import Response


def models_response_payload(
    *,
    list_response_models: Callable[[], list[dict[str, object]]],
) -> dict[str, object]:
    return {
        "object": "list",
        "data": list_response_models(),
    }


def response_read_payload(
    *,
    response_id: str,
    principal_id: str,
    container: object,
    stream_response_override: Callable[..., dict[str, object] | None],
    load_response_for_runtime: Callable[..., Any],
) -> dict[str, object]:
    override = stream_response_override(
        response_id=response_id,
        principal_id=principal_id,
    )
    if override is not None:
        return override
    stored = load_response_for_runtime(
        response_id=response_id,
        principal_id=principal_id,
        container=container,
    )
    return stored.response


def response_input_items_payload(
    *,
    response_id: str,
    stored: Any,
) -> dict[str, object]:
    return {
        "object": "list",
        "response_id": response_id,
        "data": [dict(item) for item in stored.input_items],
    }


def build_list_models_handler(
    *,
    list_response_models: Callable[[], list[dict[str, object]]],
) -> Callable[..., Response]:
    def list_models(request: Request) -> Response:
        return JSONResponse(
            models_response_payload(
                list_response_models=list_response_models,
            )
        )

    list_models.__name__ = "list_models"
    list_models.__qualname__ = "list_models"
    return list_models


def build_get_response_handler(
    *,
    get_request_context: Callable[..., Any],
    get_container: Callable[..., Any],
    stream_response_override: Callable[..., dict[str, object] | None],
    load_response_for_runtime: Callable[..., Any],
) -> Callable[..., Response]:
    def get_response(
        response_id: str,
        *,
        context: Any = Depends(get_request_context),
        container: object = Depends(get_container),
    ) -> Response:
        return JSONResponse(
            response_read_payload(
                response_id=response_id,
                principal_id=context.principal_id,
                container=container,
                stream_response_override=stream_response_override,
                load_response_for_runtime=load_response_for_runtime,
            )
        )

    get_response.__name__ = "get_response"
    get_response.__qualname__ = "get_response"
    return get_response


def build_get_response_input_items_handler(
    *,
    get_request_context: Callable[..., Any],
    get_container: Callable[..., Any],
    load_response: Callable[..., Any],
) -> Callable[..., Response]:
    def get_response_input_items(
        response_id: str,
        *,
        context: Any = Depends(get_request_context),
        container: object = Depends(get_container),
    ) -> Response:
        stored = load_response(
            response_id=response_id,
            principal_id=context.principal_id,
            container=container,
        )
        return JSONResponse(
            response_input_items_payload(
                response_id=response_id,
                stored=stored,
            )
        )

    get_response_input_items.__name__ = "get_response_input_items"
    get_response_input_items.__qualname__ = "get_response_input_items"
    return get_response_input_items
