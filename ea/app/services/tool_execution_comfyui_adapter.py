from __future__ import annotations

import os
import time
import uuid
from typing import Any
from urllib.parse import urlencode

from app.domain.models import ToolDefinition, ToolInvocationRequest, ToolInvocationResult
from app.services.tool_execution_common import ToolExecutionError


def _preview_text(text: str, *, limit: int = 280) -> str:
    cleaned = " ".join(str(text or "").split()).strip()
    return cleaned[:limit]


def _extract_text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        for key in ("prompt", "text", "source_text", "normalized_text", "generation_instruction", "instructions"):
            text = _extract_text(value.get(key))
            if text:
                return text
        return ""
    if isinstance(value, (list, tuple)):
        parts = [_extract_text(item) for item in value]
        return "\n".join(part for part in parts if part).strip()
    return str(value).strip()


def _bool_flag(value: object, *, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    lowered = str(value or "").strip().lower()
    if not lowered:
        return default
    if lowered in {"1", "true", "yes", "on"}:
        return True
    if lowered in {"0", "false", "no", "off"}:
        return False
    return default


def _int_env(name: str, default: int) -> int:
    try:
        return int(str(os.environ.get(name) or "").strip() or default)
    except Exception:
        return default


def _parse_size(value: object) -> tuple[int, int] | None:
    text = str(value or "").strip().lower().replace("×", "x")
    if not text or "x" not in text:
        return None
    width_text, height_text = text.split("x", 1)
    try:
        width = max(1, int(width_text))
        height = max(1, int(height_text))
    except Exception:
        return None
    return width, height


def _get_comfyui_url() -> str:
    return str(os.environ.get("COMFYUI_URL") or "http://localhost:8188").strip().rstrip("/")


def _comfyui_headers() -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    client_id = str(
        os.environ.get("COMFYUI_CF_ACCESS_CLIENT_ID")
        or os.environ.get("CF_ACCESS_CLIENT_ID")
        or ""
    ).strip()
    client_secret = str(
        os.environ.get("COMFYUI_CF_ACCESS_CLIENT_SECRET")
        or os.environ.get("CF_ACCESS_CLIENT_SECRET")
        or ""
    ).strip()
    if client_id and client_secret:
        headers["CF-Access-Client-Id"] = client_id
        headers["CF-Access-Client-Secret"] = client_secret
    return headers


def _mime_type_for_filename(filename: str) -> str:
    lowered = str(filename or "").strip().lower()
    if lowered.endswith(".jpg") or lowered.endswith(".jpeg"):
        return "image/jpeg"
    if lowered.endswith(".webp"):
        return "image/webp"
    return "image/png"


def _call_comfyui(prompt: str, *, width: int = 1024, height: int = 1408, steps: int = 4) -> dict[str, Any]:
    import requests

    url = _get_comfyui_url()
    if not url:
        raise ToolExecutionError("comfyui_url_missing")

    workflow = {
        "3": {
            "inputs": {
                "seed": 0,
                "steps": steps,
                "cfg": 1.0,
                "sampler_name": "euler",
                "scheduler": "sgm_uniform",
                "denoise": 1.0,
                "model": ["4", 0],
                "positive": ["6", 0],
                "negative": ["7", 0],
                "latent_image": ["5", 0],
            },
            "class_type": "KSampler",
        },
        "4": {
            "inputs": {
                "ckpt_name": "sdxl_lightning_4step.safetensors",
            },
            "class_type": "CheckpointLoaderSimple",
        },
        "5": {
            "inputs": {
                "width": width,
                "height": height,
                "batch_size": 1,
            },
            "class_type": "EmptyLatentImage",
        },
        "6": {
            "inputs": {
                "text": prompt,
                "clip": ["4", 1],
            },
            "class_type": "CLIPTextEncode",
        },
        "7": {
            "inputs": {
                "text": "blurry, low quality, text, watermark, ugly",
                "clip": ["4", 1],
            },
            "class_type": "CLIPTextEncode",
        },
        "8": {
            "inputs": {
                "samples": ["3", 0],
                "vae": ["4", 2],
            },
            "class_type": "VAEDecode",
        },
        "9": {
            "inputs": {
                "filename_prefix": "ea_comfyui",
                "images": ["8", 0],
            },
            "class_type": "SaveImage",
        },
    }

    try:
        response = requests.post(
            f"{url}/prompt",
            json={"prompt": workflow},
            headers=_comfyui_headers(),
            timeout=(
                _int_env("COMFYUI_CONNECT_TIMEOUT_SECONDS", 10),
                _int_env("COMFYUI_READ_TIMEOUT_SECONDS", 120),
            ),
        )
        response.raise_for_status()
        payload = response.json()
    except requests.exceptions.RequestException as exc:
        raise ToolExecutionError(f"comfyui_connection_failed:{str(exc)[:200]}") from exc
    except ValueError as exc:
        raise ToolExecutionError("comfyui_invalid_json") from exc
    if not isinstance(payload, dict):
        raise ToolExecutionError("comfyui_invalid_payload")
    return payload


def _wait_for_generation(prompt_id: str) -> dict[str, Any]:
    import requests

    url = _get_comfyui_url()
    if not url:
        raise ToolExecutionError("comfyui_url_missing")

    poll_attempts = _int_env("COMFYUI_POLL_ATTEMPTS", 60)
    poll_interval = max(0.1, float(str(os.environ.get("COMFYUI_POLL_INTERVAL_SECONDS") or "1").strip() or "1"))

    for _ in range(poll_attempts):
        try:
            response = requests.get(
                f"{url}/history/{prompt_id}",
                headers=_comfyui_headers(),
                timeout=(
                    _int_env("COMFYUI_CONNECT_TIMEOUT_SECONDS", 10),
                    _int_env("COMFYUI_HISTORY_TIMEOUT_SECONDS", 30),
                ),
            )
            response.raise_for_status()
            history = response.json()
        except requests.exceptions.RequestException:
            time.sleep(poll_interval)
            continue
        except ValueError:
            time.sleep(poll_interval)
            continue

        if not isinstance(history, dict):
            time.sleep(poll_interval)
            continue
        if prompt_id in history:
            result = history[prompt_id]
            if not isinstance(result, dict):
                time.sleep(poll_interval)
                continue
            status = result.get("status", {})
            if isinstance(status, dict) and status.get("completed"):
                return result
        time.sleep(poll_interval)

    raise ToolExecutionError("comfyui_generation_timeout")


def _first_image_info(outputs: object) -> dict[str, Any]:
    if not isinstance(outputs, dict):
        return {}
    for node_output in outputs.values():
        if not isinstance(node_output, dict):
            continue
        images = node_output.get("images")
        if not isinstance(images, list):
            continue
        for image in images:
            if isinstance(image, dict) and str(image.get("filename") or "").strip():
                return dict(image)
    return {}


def _build_asset_url(image_info: dict[str, Any]) -> str:
    url = _get_comfyui_url()
    if not url:
        raise ToolExecutionError("comfyui_url_missing")
    filename = str(image_info.get("filename") or "").strip()
    if not filename:
        raise ToolExecutionError("comfyui_image_filename_missing")
    query = {"filename": filename}
    subfolder = str(image_info.get("subfolder") or "").strip()
    image_type = str(image_info.get("type") or "output").strip() or "output"
    if subfolder:
        query["subfolder"] = subfolder
    if image_type:
        query["type"] = image_type
    return f"{url}/view?{urlencode(query)}"


class ComfyUIToolAdapter:
    def _default_width(self) -> int:
        return _int_env("COMFYUI_WIDTH", 1024)

    def _default_height(self) -> int:
        return _int_env("COMFYUI_HEIGHT", 1408)

    def _default_steps(self) -> int:
        return _int_env("COMFYUI_STEPS", 4)

    def _fallback_to_onemin_enabled(self) -> bool:
        return _bool_flag(os.environ.get("COMFYUI_FALLBACK_TO_ONEMIN"), default=True)

    def _should_fallback(self, exc: ToolExecutionError) -> bool:
        detail = str(exc or "").strip()
        return bool(detail) and detail.startswith("comfyui_")

    def _dimensions(self, payload: dict[str, Any]) -> tuple[int, int]:
        width = int(payload.get("width") or self._default_width())
        height = int(payload.get("height") or self._default_height())
        parsed_size = _parse_size(payload.get("size"))
        if parsed_size is not None:
            width, height = parsed_size
        return width, height

    def _execute_primary(self, request: ToolInvocationRequest, definition: ToolDefinition) -> ToolInvocationResult:
        payload = dict(request.payload_json or {})
        prompt = self._build_prompt(payload)
        width, height = self._dimensions(payload)
        steps = int(payload.get("steps") or self._default_steps())

        result = _call_comfyui(prompt, width=width, height=height, steps=steps)
        prompt_id = str(result.get("prompt_id") or "").strip()
        if not prompt_id:
            raise ToolExecutionError("comfyui_no_prompt_id")

        generation_result = _wait_for_generation(prompt_id)
        outputs = generation_result.get("outputs", {})
        image_info = _first_image_info(outputs)
        if not image_info:
            raise ToolExecutionError("comfyui_no_image_output")

        filename = str(image_info.get("filename") or "").strip()
        subfolder = str(image_info.get("subfolder") or "").strip()
        image_type = str(image_info.get("type") or "output").strip() or "output"
        asset_url = _build_asset_url(image_info)
        mime_type = _mime_type_for_filename(filename)
        action_kind = str(request.action_kind or "image.generate").strip() or "image.generate"

        return ToolInvocationResult(
            tool_name=definition.tool_name,
            action_kind=action_kind,
            target_ref=f"comfyui:{uuid.uuid4()}",
            output_json={
                "image_url": asset_url,
                "asset_urls": [asset_url],
                "filename": filename,
                "subfolder": subfolder,
                "type": image_type,
                "mime_type": mime_type,
                "width": width,
                "height": height,
                "provider_backend": "comfyui",
                "provider_account_name": "comfyui",
                "provider_key_slot": "",
                "preview_text": _preview_text(prompt),
            },
            receipt_json={
                "handler_key": definition.tool_name,
                "invocation_contract": "tool.v1",
                "provider_key": "comfyui",
                "provider_backend": "comfyui",
                "tool_version": definition.version,
                "prompt_id": prompt_id,
            },
            model_name=str(os.environ.get("COMFYUI_MODEL_NAME") or "SDXL-Lightning-4step").strip() or "SDXL-Lightning-4step",
            tokens_in=0,
            tokens_out=0,
            cost_usd=0.0,
        )

    def _fallback_to_onemin(self, request: ToolInvocationRequest, definition: ToolDefinition) -> ToolInvocationResult:
        from app.domain.models import ToolDefinition as DomainToolDefinition
        from app.services.tool_execution_onemin_adapter import OneminToolAdapter

        payload = dict(request.payload_json or {})
        if not str(payload.get("size") or "").strip():
            width = payload.get("width")
            height = payload.get("height")
            if width is not None and height is not None:
                payload["size"] = f"{int(width)}x{int(height)}"
        fallback_definition = DomainToolDefinition(
            tool_name="provider.onemin.image_generate",
            version=definition.version,
            input_schema_json=dict(definition.input_schema_json or {}),
            output_schema_json=dict(definition.output_schema_json or {}),
            policy_json=dict(definition.policy_json or {}),
            allowed_channels=tuple(definition.allowed_channels or ()),
            approval_default=str(definition.approval_default or "none"),
            enabled=bool(definition.enabled),
            updated_at=str(definition.updated_at or ""),
        )
        fallback_request = ToolInvocationRequest(
            session_id=request.session_id,
            step_id=request.step_id,
            tool_name="provider.onemin.image_generate",
            action_kind=request.action_kind,
            payload_json=payload,
            context_json=dict(request.context_json or {}),
        )
        return OneminToolAdapter().execute_image_generate(fallback_request, fallback_definition)

    def execute_image_generate(self, request: ToolInvocationRequest, definition: ToolDefinition) -> ToolInvocationResult:
        try:
            return self._execute_primary(request, definition)
        except ToolExecutionError as exc:
            if not self._fallback_to_onemin_enabled() or not self._should_fallback(exc):
                raise
            return self._fallback_to_onemin(request, definition)

    def _build_prompt(self, payload: dict[str, Any]) -> str:
        prompt = _extract_text(payload.get("prompt") or payload.get("source_text") or payload.get("text"))
        if not prompt:
            raise ToolExecutionError("prompt_required:provider.comfyui.image_generate")
        return prompt
