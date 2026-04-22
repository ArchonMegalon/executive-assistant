from __future__ import annotations

import base64
import os
import time
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.api.dependencies import RequestContext, get_container, get_request_context
from app.container import AppContainer
from app.domain.models import ToolInvocationRequest, ToolInvocationResult
from app.services.tool_execution_common import ToolExecutionError

router = APIRouter(tags=["images"])


class ImageGenerationIn(BaseModel):
    prompt: str = Field(min_length=1)
    model: str = Field(default="", max_length=200)
    n: int = Field(default=1, ge=1, le=1)
    size: str = Field(default="", max_length=32)
    quality: str = Field(default="", max_length=32)
    response_format: str = Field(default="url", max_length=32)
    width: int | None = Field(default=None, ge=1, le=4096)
    height: int | None = Field(default=None, ge=1, le=4096)
    steps: int | None = Field(default=None, ge=1, le=200)


def _comfyui_payload(body: ImageGenerationIn) -> dict[str, object]:
    payload: dict[str, object] = {"prompt": body.prompt}
    if body.size:
        payload["size"] = body.size
    if body.width is not None:
        payload["width"] = body.width
    if body.height is not None:
        payload["height"] = body.height
    if body.steps is not None:
        payload["steps"] = body.steps
    return payload


def _onemin_payload(body: ImageGenerationIn) -> dict[str, object]:
    payload: dict[str, object] = {"prompt": body.prompt, "n": body.n}
    if body.model:
        payload["model"] = body.model
    if body.size:
        payload["size"] = body.size
    if body.quality:
        payload["quality"] = body.quality
    return payload


def _execute_tool(
    *,
    container: AppContainer,
    context: RequestContext,
    tool_name: str,
    payload_json: dict[str, object],
) -> ToolInvocationResult:
    invocation = ToolInvocationRequest(
        session_id=f"image-route:{uuid.uuid4()}",
        step_id=f"image-step:{uuid.uuid4()}",
        tool_name=tool_name,
        action_kind="image.generate",
        payload_json=payload_json,
        context_json={"principal_id": context.principal_id},
    )
    return container.tool_execution.execute_invocation(invocation)


def _asset_urls(result: ToolInvocationResult) -> list[str]:
    output_json = dict(result.output_json or {})
    raw = output_json.get("asset_urls")
    urls: list[str] = []
    if isinstance(raw, list):
        urls.extend(str(item or "").strip() for item in raw if str(item or "").strip())
    for key in ("image_url", "url"):
        value = str(output_json.get(key) or "").strip()
        if value:
            urls.append(value)
    deduped: list[str] = []
    seen: set[str] = set()
    for url in urls:
        if url in seen:
            continue
        seen.add(url)
        deduped.append(url)
    return deduped


def _download_bytes(url: str) -> bytes:
    import requests

    headers: dict[str, str] = {}
    client_id = ""
    client_secret = ""
    for key in ("COMFYUI_CF_ACCESS_CLIENT_ID", "CF_ACCESS_CLIENT_ID"):
        client_id = str(os.environ.get(key) or "").strip()
        if client_id:
            break
    for key in ("COMFYUI_CF_ACCESS_CLIENT_SECRET", "CF_ACCESS_CLIENT_SECRET"):
        client_secret = str(os.environ.get(key) or "").strip()
        if client_secret:
            break
    if client_id and client_secret:
        headers["CF-Access-Client-Id"] = client_id
        headers["CF-Access-Client-Secret"] = client_secret
    try:
        response = requests.get(url, headers=headers, timeout=(10, 120))
        response.raise_for_status()
    except requests.exceptions.RequestException as exc:
        raise HTTPException(status_code=502, detail=f"image_asset_fetch_failed:{str(exc)[:200]}") from exc
    return bytes(response.content or b"")


def _response_data(*, urls: list[str], response_format: str) -> list[dict[str, Any]]:
    if response_format == "url":
        return [{"url": url} for url in urls]
    if response_format == "b64_json":
        data: list[dict[str, Any]] = []
        for url in urls:
            encoded = base64.b64encode(_download_bytes(url)).decode("ascii")
            data.append({"b64_json": encoded})
        return data
    raise HTTPException(status_code=400, detail="unsupported_response_format")


@router.post("/v1/images/generations", response_model=None)
@router.post("/images/generations", response_model=None)
@router.post("/api/v1/images/generations", response_model=None)
def create_image_generation(
    body: ImageGenerationIn,
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> dict[str, object]:
    response_format = str(body.response_format or "url").strip().lower() or "url"
    comfy_state = container.provider_registry.binding_state("comfyui", principal_id=context.principal_id)
    comfy_eligible = comfy_state is not None and comfy_state.state not in {"catalog_only", "disabled", "unconfigured"}

    primary_error = ""
    result: ToolInvocationResult | None = None
    if comfy_eligible:
        try:
            result = _execute_tool(
                container=container,
                context=context,
                tool_name="provider.comfyui.image_generate",
                payload_json=_comfyui_payload(body),
            )
        except ToolExecutionError as exc:
            primary_error = str(exc or "").strip()

    if result is None:
        try:
            result = _execute_tool(
                container=container,
                context=context,
                tool_name="provider.onemin.image_generate",
                payload_json=_onemin_payload(body),
            )
        except ToolExecutionError as exc:
            detail = str(exc or "").strip() or "image_generation_unavailable"
            if primary_error:
                detail = f"{primary_error}; {detail}"
            raise HTTPException(status_code=503, detail=detail[:500]) from exc

    urls = _asset_urls(result)
    if not urls:
        raise HTTPException(status_code=502, detail="image_generation_missing_asset_url")

    provider_key = str((result.receipt_json or {}).get("provider_key") or (result.output_json or {}).get("provider_backend") or "").strip()
    if provider_key == "1min":
        provider_key = "onemin"
    return {
        "created": int(time.time()),
        "data": _response_data(urls=urls, response_format=response_format),
        "provider": provider_key or "unknown",
        "fallback_used": bool(comfy_eligible and provider_key != "comfyui"),
        "model": str(result.model_name or ""),
    }
