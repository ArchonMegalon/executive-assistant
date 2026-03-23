from __future__ import annotations

import json
import uuid
from typing import Any

from app.domain.models import ToolDefinition, ToolInvocationRequest, ToolInvocationResult
from app.services.tool_execution_common import ToolExecutionError


def _preview_text(text: str, *, limit: int = 280) -> str:
    cleaned = " ".join(str(text or "").split()).strip()
    return cleaned[:limit]


def _strip_fences(text: str) -> str:
    raw = str(text or "").strip()
    if raw.startswith("```"):
        raw = raw.removeprefix("```json").removeprefix("```").strip()
    if raw.endswith("```"):
        raw = raw[:-3].strip()
    return raw


def _parse_structured(text: str) -> tuple[str, dict[str, Any], str]:
    cleaned = _strip_fences(text)
    try:
        loaded = json.loads(cleaned)
    except Exception:
        return cleaned, {}, "text/plain"
    if isinstance(loaded, dict):
        return json.dumps(loaded, indent=2, ensure_ascii=True), loaded, "application/json"
    return json.dumps(loaded, indent=2, ensure_ascii=True), {"result": loaded}, "application/json"


def _extract_text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        for key in ("text", "prompt", "source_text", "normalized_text", "generation_instruction", "instructions", "goal"):
            text = _extract_text(value.get(key))
            if text:
                return text
        return ""
    if isinstance(value, (list, tuple)):
        parts = [_extract_text(item) for item in value]
        return "\n".join(part for part in parts if part).strip()
    return str(value).strip()


class MagixaiToolAdapter:
    def _default_model(self) -> str:
        from app.services import responses_upstream as upstream

        return next(iter(upstream._magicx_lane_models()), "mx-best")

    def _build_prompt(self, payload: dict[str, Any]) -> str:
        prompt = _extract_text(payload.get("prompt") or payload.get("source_text") or payload.get("normalized_text"))
        if not prompt:
            raise ToolExecutionError("prompt_required:provider.magixai.structured_generate")
        instructions = _extract_text(payload.get("generation_instruction") or payload.get("instructions"))
        goal = _extract_text(payload.get("goal"))
        context_pack = payload.get("context_pack")
        response_schema_json = payload.get("response_schema_json")
        parts: list[str] = []
        if instructions:
            parts.append(instructions)
        if goal:
            parts.append(f"Goal: {goal}")
        if isinstance(response_schema_json, dict) and response_schema_json:
            parts.append("Return JSON matching this schema:\n" + json.dumps(response_schema_json, ensure_ascii=True))
        if isinstance(context_pack, dict) and context_pack:
            parts.append("Context:\n" + json.dumps(context_pack, ensure_ascii=True))
        parts.append(prompt)
        return "\n\n".join(part for part in parts if part).strip()

    def _call_text(
        self,
        *,
        prompt: str,
        model: str,
        lane: str,
    ):
        from app.services import responses_upstream as upstream

        config = upstream._provider_configs().get("magixai")
        if config is None or not config.api_keys:
            raise ToolExecutionError("magixai_missing_api_key")
        try:
            return upstream._call_magicx(
                config,
                prompt=prompt,
                messages=None,
                model=model,
                max_output_tokens=None,
                lane=lane,
            )
        except upstream.ResponsesUpstreamError as exc:
            raise ToolExecutionError(f"magixai_failed:{str(exc)[:400]}") from exc

    def execute_structured_generate(self, request: ToolInvocationRequest, definition: ToolDefinition) -> ToolInvocationResult:
        payload = dict(request.payload_json or {})
        prompt = self._build_prompt(payload)
        lane = str(payload.get("lane") or payload.get("brain_profile") or "easy").strip().lower() or "easy"
        model = str(payload.get("model") or self._default_model()).strip() or self._default_model()
        result = self._call_text(prompt=prompt, model=model, lane=lane)
        normalized_text, structured_output_json, mime_type = _parse_structured(result.text)
        action_kind = str(request.action_kind or "content.generate") or "content.generate"
        return ToolInvocationResult(
            tool_name=definition.tool_name,
            action_kind=action_kind,
            target_ref=f"magixai:{uuid.uuid4()}",
            output_json={
                "normalized_text": normalized_text,
                "structured_output_json": structured_output_json,
                "preview_text": _preview_text(normalized_text),
                "mime_type": mime_type,
                "model": result.model,
                "provider_backend": result.provider_backend or "aimagicx",
                "provider_account_name": result.provider_account_name,
                "provider_key_slot": result.provider_key_slot,
                "tool_name": definition.tool_name,
                "action_kind": action_kind,
            },
            receipt_json={
                "handler_key": definition.tool_name,
                "invocation_contract": "tool.v1",
                "provider_key": "magixai",
                "provider_backend": result.provider_backend or "aimagicx",
                "provider_account_name": result.provider_account_name,
                "provider_key_slot": result.provider_key_slot,
                "model": result.model,
                "tool_version": definition.version,
            },
            model_name=result.model,
            tokens_in=int(result.tokens_in or 0),
            tokens_out=int(result.tokens_out or 0),
            cost_usd=0.0,
        )
