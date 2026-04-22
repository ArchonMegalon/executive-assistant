from __future__ import annotations

import json
import os
import uuid
from typing import Any

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


def _get_comfyui_url() -> str:
    return str(os.environ.get("COMFYUI_URL") or "http://localhost:8188").strip()


def _call_comfyui(prompt: str, *, width: int = 1024, height: int = 1408, steps: int = 4) -> dict[str, Any]:
    import requests
    
    url = _get_comfyui_url()
    
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
                "latent_image": ["5", 0]
            },
            "class_type": "KSampler"
        },
        "4": {
            "inputs": {
                "ckpt_name": "sdxl_lightning_4step.safetensors"
            },
            "class_type": "CheckpointLoaderSimple"
        },
        "5": {
            "inputs": {
                "width": width,
                "height": height,
                "batch_size": 1
            },
            "class_type": "EmptyLatentImage"
        },
        "6": {
            "inputs": {
                "text": prompt,
                "clip": ["4", 1]
            },
            "class_type": "CLIPTextEncode"
        },
        "7": {
            "inputs": {
                "text": "blurry, low quality, text, watermark, ugly",
                "clip": ["4", 1]
            },
            "class_type": "CLIPTextEncode"
        },
        "8": {
            "inputs": {
                "samples": ["3", 0],
                "vae": ["4", 2]
            },
            "class_type": "VAEDecode"
        },
        "9": {
            "inputs": {
                "filename_prefix": "ea_comfyui",
                "images": ["8", 0]
            },
            "class_type": "SaveImage"
        }
    }
    
    try:
        response = requests.post(f"{url}/prompt", json={"prompt": workflow}, timeout=120)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as exc:
        raise ToolExecutionError(f"comfyui_connection_failed:{str(exc)[:200]}") from exc


def _wait_for_generation(prompt_id: str) -> dict[str, Any]:
    import requests
    import time
    
    url = _get_comfyui_url()
    
    for _ in range(60):
        try:
            response = requests.get(f"{url}/history/{prompt_id}", timeout=30)
            response.raise_for_status()
            history = response.json()
            
            if prompt_id in history:
                result = history[prompt_id]
                status = result.get("status", {})
                if status.get("completed"):
                    return result
            
            time.sleep(1)
        except requests.exceptions.RequestException:
            time.sleep(1)
    
    raise ToolExecutionError("comfyui_generation_timeout")


class ComfyUIToolAdapter:
    def _default_width(self) -> int:
        try:
            return int(os.environ.get("COMFYUI_WIDTH", "1024"))
        except Exception:
            return 1024
    
    def _default_height(self) -> int:
        try:
            return int(os.environ.get("COMFYUI_HEIGHT", "1408"))
        except Exception:
            return 1408
    
    def _default_steps(self) -> int:
        try:
            return int(os.environ.get("COMFYUI_STEPS", "4"))
        except Exception:
            return 4
    
    def execute_image_generate(self, request: ToolInvocationRequest, definition: ToolDefinition) -> ToolInvocationResult:
        payload = dict(request.payload_json or {})
        prompt = self._build_prompt(payload)
        
        width = int(payload.get("width") or self._default_width())
        height = int(payload.get("height") or self._default_height())
        steps = int(payload.get("steps") or self._default_steps())
        
        result = _call_comfyui(prompt, width=width, height=height, steps=steps)
        prompt_id = result.get("prompt_id")
        
        if not prompt_id:
            raise ToolExecutionError("comfyui_no_prompt_id")
        
        generation_result = _wait_for_generation(prompt_id)
        outputs = generation_result.get("outputs", {})
        
        image_info = None
        for node_id, node_output in outputs.items():
            images = node_output.get("images", [])
            if images:
                image_info = images[0]
                break
        
        if not image_info:
            raise ToolExecutionError("comfyui_no_image_output")
        
        filename = image_info.get("filename", "")
        subfolder = image_info.get("subfolder", "")
        image_type = image_info.get("type", "output")
        
        output_dir = "/Users/elisabethgirschele/comfyui/output"
        image_path = os.path.join(output_dir, filename)
        
        if not os.path.exists(image_path):
            raise ToolExecutionError(f"comfyui_image_not_found:{image_path}")
        
        file_size = os.path.getsize(image_path)
        mime_type = "image/png"
        if filename.lower().endswith(".jpg") or filename.lower().endswith(".jpeg"):
            mime_type = "image/jpeg"
        elif filename.lower().endswith(".webp"):
            mime_type = "image/webp"
        
        return ToolInvocationResult(
            tool_name=definition.tool_name,
            action_kind=str(request.action_kind or "content.generate"),
            target_ref=f"comfyui:{uuid.uuid4()}",
            output_json={
                "image_path": image_path,
                "filename": filename,
                "subfolder": subfolder,
                "type": image_type,
                "file_size": file_size,
                "mime_type": mime_type,
                "width": width,
                "height": height,
                "preview_text": _preview_text(prompt),
            },
            receipt_json={
                "handler_key": definition.tool_name,
                "invocation_contract": "tool.v1",
                "provider_key": "comfyui",
                "tool_version": definition.version,
                "prompt_id": prompt_id,
            },
            model_name="SDXL-Lightning-4step",
            tokens_in=0,
            tokens_out=0,
            cost_usd=0.0,
        )
    
    def _build_prompt(self, payload: dict[str, Any]) -> str:
        prompt = _extract_text(payload.get("prompt") or payload.get("source_text") or payload.get("text"))
        if not prompt:
            raise ToolExecutionError("prompt_required:provider.comfyui.image_generate")
        return prompt
