from __future__ import annotations

from typing import Any, Awaitable, Callable

from starlette.responses import Response


def build_run_profiled_codex_response(
    *,
    normalize_payload_for_profile: Callable[..., dict[str, object]],
    run_response_in_executor: Callable[..., Awaitable[Response]],
    preferred_onemin_labels_from_request: Callable[[Any], tuple[str, ...]],
) -> Callable[..., Awaitable[Response]]:
    async def run_profiled_codex_response(
        payload: dict[str, object],
        *,
        request: Any,
        context: Any,
        container: object,
        profile: str,
    ) -> Response:
        normalized = normalize_payload_for_profile(
            payload,
            profile=profile,
            container=container,
            principal_id=context.principal_id,
        )
        return await run_response_in_executor(
            normalized,
            context=context,
            container=container,
            codex_profile=profile,
            preferred_onemin_labels=preferred_onemin_labels_from_request(request),
        )

    run_profiled_codex_response.__name__ = "run_profiled_codex_response"
    run_profiled_codex_response.__qualname__ = "run_profiled_codex_response"
    return run_profiled_codex_response
