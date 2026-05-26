from __future__ import annotations

import asyncio
from functools import partial
from typing import Any, Awaitable, Callable

from fastapi import Request
from starlette.responses import Response


def header_codex_profile_from_request(request: Request) -> str | None:
    header_profile = str(
        request.headers.get("X-EA-Codex-Profile") or request.headers.get("X-CodexEA-Profile") or ""
    ).strip().lower()
    if header_profile == "jury":
        header_profile = "audit"
    if header_profile == "review-light":
        header_profile = "review_light"
    if header_profile not in {"core", "core_batch", "core_rescue", "easy", "repair", "groundwork", "review_light", "survival", "audit"}:
        return None
    return header_profile


def payload_with_request_trace_metadata(payload: dict[str, object], *, request: Request) -> dict[str, object]:
    normalized_payload = dict(payload or {})
    trace_metadata = (
        dict(normalized_payload.get("metadata") or {})
        if isinstance(normalized_payload.get("metadata"), dict)
        else {}
    )
    correlation_id = str(getattr(request.state, "correlation_id", "") or "").strip()
    if correlation_id:
        trace_metadata["ea_correlation_id"] = correlation_id
    if trace_metadata:
        normalized_payload["metadata"] = trace_metadata
    return normalized_payload


def preferred_onemin_labels_from_request(request: Request) -> tuple[str, ...]:
    labels: list[str] = []
    for header_name in (
        "X-EA-Onemin-Account-Alias",
        "X-EA-Onemin-Account-Env",
        "X-EA-Onemin-Account",
        "X-EA-Onemin-Preferred-Accounts",
    ):
        raw = str(request.headers.get(header_name) or "").strip()
        if not raw:
            continue
        for part in raw.replace(";", ",").split(","):
            label = str(part or "").strip()
            if label and label not in labels:
                labels.append(label)
    return tuple(labels)


def build_run_response_in_executor(
    *,
    responses_route_executor: Any,
    run_response: Callable[..., Response],
) -> Callable[..., Awaitable[Response]]:
    async def run_response_in_executor(
        request_payload: dict[str, object],
        *,
        context: Any,
        container: object | None = None,
        codex_profile: str | None = None,
        preferred_onemin_labels: tuple[str, ...] = (),
    ) -> Response:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            responses_route_executor,
            partial(
                run_response,
                request_payload,
                context=context,
                container=container,
                codex_profile=codex_profile,
                preferred_onemin_labels=preferred_onemin_labels,
            ),
        )

    run_response_in_executor.__name__ = "run_response_in_executor"
    run_response_in_executor.__qualname__ = "run_response_in_executor"
    return run_response_in_executor
