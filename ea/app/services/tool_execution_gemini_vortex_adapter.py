from __future__ import annotations

import json
import os
import shlex
import subprocess
import uuid
from typing import Any

from app.domain.models import ToolDefinition, ToolInvocationRequest, ToolInvocationResult
from app.services.tool_execution_common import ToolExecutionError


def _env_value(name: str) -> str:
    return str(os.environ.get(name) or "").strip()


def _strip_fences(text: str) -> str:
    raw = str(text or "").strip()
    if raw.startswith("```"):
        raw = raw.removeprefix("```json").removeprefix("```").strip()
    if raw.endswith("```"):
        raw = raw[:-3].strip()
    return raw


def _preview_text(text: str, *, limit: int = 280) -> str:
    cleaned = " ".join(str(text or "").split()).strip()
    return cleaned[:limit]


class GeminiVortexToolAdapter:
    def _command_base(self) -> list[str]:
        raw = _env_value("EA_GEMINI_VORTEX_COMMAND") or "gemini"
        return shlex.split(raw)

    def _default_model(self) -> str:
        return _env_value("EA_GEMINI_VORTEX_MODEL") or "gemini-3-flash-preview"

    def _timeout_seconds(self) -> int:
        raw = _env_value("EA_GEMINI_VORTEX_TIMEOUT_SECONDS") or "180"
        try:
            return max(15, int(raw))
        except Exception:
            return 180

    def _build_prompt(self, payload: dict[str, Any]) -> str:
        source_text = str(payload.get("normalized_text") or payload.get("source_text") or "").strip()
        if not source_text:
            raise ToolExecutionError("source_text_required")
        prompt_parts: list[str] = []
        generation_instruction = str(payload.get("generation_instruction") or payload.get("instructions") or "").strip()
        if generation_instruction:
            prompt_parts.append(generation_instruction)
        goal = str(payload.get("goal") or "").strip()
        if goal:
            prompt_parts.append(f"Goal: {goal}")
        response_schema = payload.get("response_schema_json")
        if isinstance(response_schema, dict) and response_schema:
            prompt_parts.append(
                "Return JSON only. Match this schema contract as closely as possible:\n"
                + json.dumps(response_schema, ensure_ascii=True)
            )
        else:
            prompt_parts.append("Return JSON only. No markdown fences, no commentary.")
        context_pack = payload.get("context_pack")
        if isinstance(context_pack, dict) and context_pack:
            prompt_parts.append("Context pack:\n" + json.dumps(context_pack, ensure_ascii=True))
        prompt_parts.append(source_text)
        return "\n\n".join(part for part in prompt_parts if part).strip()

    def _extract_response_text(self, stdout: str) -> tuple[str, dict[str, Any], dict[str, Any]]:
        raw = str(stdout or "").strip()
        if not raw:
            raise ToolExecutionError("gemini_vortex_empty_output")
        try:
            envelope = json.loads(raw)
        except Exception:
            return raw, {}, {}
        if not isinstance(envelope, dict):
            return raw, {}, {}
        response = str(envelope.get("response") or "").strip()
        stats = envelope.get("stats") if isinstance(envelope.get("stats"), dict) else {}
        if response:
            return response, envelope, stats
        return raw, envelope, stats

    def _parse_structured(self, text: str) -> tuple[str, dict[str, Any], str]:
        cleaned = _strip_fences(text)
        try:
            loaded = json.loads(cleaned)
        except Exception:
            return cleaned, {}, "text/plain"
        if isinstance(loaded, dict):
            return json.dumps(loaded, indent=2, ensure_ascii=True), loaded, "application/json"
        return json.dumps(loaded, indent=2, ensure_ascii=True), {"result": loaded}, "application/json"

    def _token_counts(self, stats: dict[str, Any]) -> tuple[int, int]:
        total_in = 0
        total_out = 0
        models = stats.get("models")
        if not isinstance(models, dict):
            return (0, 0)
        for row in models.values():
            if not isinstance(row, dict):
                continue
            tokens = row.get("tokens")
            if not isinstance(tokens, dict):
                continue
            total_in += int(tokens.get("input") or 0)
            total_out += int(tokens.get("candidates") or tokens.get("output") or 0)
        return (total_in, total_out)

    def execute(self, request: ToolInvocationRequest, definition: ToolDefinition) -> ToolInvocationResult:
        payload = dict(request.payload_json or {})
        prompt = self._build_prompt(payload)
        model = str(payload.get("model") or self._default_model()).strip() or self._default_model()
        command = self._command_base() + [
            "-p",
            prompt,
            "--output-format",
            "json",
            "--approval-mode",
            "yolo",
        ]
        if model:
            command.extend(["-m", model])
        try:
            completed = subprocess.run(
                command,
                check=True,
                text=True,
                capture_output=True,
                timeout=self._timeout_seconds(),
            )
        except FileNotFoundError as exc:
            raise ToolExecutionError("gemini_vortex_cli_missing") from exc
        except subprocess.TimeoutExpired as exc:
            raise ToolExecutionError("gemini_vortex_timeout") from exc
        except subprocess.CalledProcessError as exc:
            detail = (exc.stderr or exc.stdout or "").strip()
            raise ToolExecutionError(f"gemini_vortex_failed:{detail[:400]}") from exc
        response_text, envelope, stats = self._extract_response_text(completed.stdout or "")
        normalized_text, structured_output_json, mime_type = self._parse_structured(response_text)
        tokens_in, tokens_out = self._token_counts(stats)
        action_kind = str(request.action_kind or "content.generate") or "content.generate"
        return ToolInvocationResult(
            tool_name=definition.tool_name,
            action_kind=action_kind,
            target_ref=f"gemini-vortex:{uuid.uuid4()}",
            output_json={
                "normalized_text": normalized_text,
                "structured_output_json": structured_output_json,
                "preview_text": _preview_text(normalized_text),
                "mime_type": mime_type,
                "model": model,
                "tool_name": definition.tool_name,
                "action_kind": action_kind,
            },
            receipt_json={
                "handler_key": definition.tool_name,
                "invocation_contract": "tool.v1",
                "model": model,
                "prompt_length": len(prompt),
                "mime_type": mime_type,
                "structured": bool(structured_output_json),
                "tool_version": definition.version,
                "response_envelope_keys": sorted(envelope.keys()) if isinstance(envelope, dict) else [],
            },
            model_name=model,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cost_usd=0.0,
        )
