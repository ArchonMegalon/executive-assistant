from __future__ import annotations

import json
import time
import uuid
from typing import Any, Iterable

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse

from app.api.dependencies import RequestContext, get_container, get_request_context
from app.container import AppContainer
from app.domain.models import ToolInvocationRequest
from app.services.tool_execution_common import ToolExecutionError


router = APIRouter(tags=["responses"])


def _now_unix() -> int:
    return int(time.time())


def _json_dumps(payload: object) -> str:
    return json.dumps(payload, ensure_ascii=True, separators=(",", ":"))


def _sse_event(*, event: str, data: dict[str, object]) -> str:
    # Responses streaming uses SSE with both an `event:` line and a `data:` JSON line.
    return f"event: {event}\ndata: {_json_dumps(data)}\n\n"


def _extract_text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float, bool)):
        return str(value)
    return ""


def _input_text(payload: dict[str, object]) -> str:
    raw = payload.get("input")
    if isinstance(raw, str):
        return raw.strip()
    if isinstance(raw, list):
        parts: list[str] = []
        for item in raw:
            if isinstance(item, str):
                cleaned = item.strip()
                if cleaned:
                    parts.append(cleaned)
                continue
            if not isinstance(item, dict):
                continue
            content = item.get("content")
            if isinstance(content, str):
                cleaned = content.strip()
                if cleaned:
                    parts.append(cleaned)
                continue
            if isinstance(content, list):
                for entry in content:
                    if isinstance(entry, str):
                        cleaned = entry.strip()
                        if cleaned:
                            parts.append(cleaned)
                        continue
                    if not isinstance(entry, dict):
                        continue
                    entry_type = str(entry.get("type") or "").strip().lower()
                    if entry_type in {"input_text", "text"}:
                        cleaned = _extract_text(entry.get("text")).strip()
                        if cleaned:
                            parts.append(cleaned)
        return "\n\n".join(parts).strip()
    return ""


def _instructions_text(payload: dict[str, object]) -> str:
    instructions = payload.get("instructions")
    if isinstance(instructions, str) and instructions.strip():
        return instructions.strip()
    return ""


def _metadata(payload: dict[str, object]) -> dict[str, object]:
    raw = payload.get("metadata")
    if isinstance(raw, dict):
        return {str(k): v for k, v in raw.items()}
    return {}


def _requested_model(payload: dict[str, object]) -> str:
    model = payload.get("model")
    if isinstance(model, str):
        return model.strip()
    return ""


def _gemini_model_hint(model: str) -> str:
    lowered = str(model or "").strip().lower()
    if not lowered:
        return ""
    # Treat explicit gemini model names as valid CLI hints; otherwise rely on EA_GEMINI_VORTEX_MODEL.
    if "gemini" in lowered:
        return str(model).strip()
    return ""


def _response_object(
    *,
    response_id: str,
    model: str,
    created_at: int,
    status: str,
    output: list[dict[str, object]] | None = None,
    output_text: str = "",
    tokens_in: int = 0,
    tokens_out: int = 0,
    metadata: dict[str, object] | None = None,
) -> dict[str, object]:
    completed_at = created_at if status == "completed" else None
    usage: dict[str, object] = {
        "input_tokens": int(tokens_in or 0),
        "output_tokens": int(tokens_out or 0),
        "total_tokens": int((tokens_in or 0) + (tokens_out or 0)),
    }
    return {
        "id": response_id,
        "object": "response",
        "created_at": created_at,
        "status": status,
        "completed_at": completed_at,
        "error": None,
        "incomplete_details": None,
        "instructions": None,
        "max_output_tokens": None,
        "model": model or "",
        "output": list(output or []),
        "parallel_tool_calls": False,
        "previous_response_id": None,
        "reasoning": None,
        "store": False,
        "temperature": None,
        "text": {"format": {"type": "text"}},
        "tool_choice": "none",
        "tools": [],
        "top_p": None,
        "truncation": "disabled",
        "usage": usage,
        "user": None,
        "metadata": dict(metadata or {}),
        # Convenience field used by some SDKs/clients.
        "output_text": output_text,
    }


def _message_item(*, item_id: str, text: str, status: str) -> dict[str, object]:
    return {
        "id": item_id,
        "type": "message",
        "status": status,
        "role": "assistant",
        "content": [
            {
                "type": "output_text",
                "text": text,
                "annotations": [],
            }
        ],
    }


def _tool_generate_text(
    *,
    container: AppContainer,
    principal_id: str,
    prompt: str,
    model_hint: str,
    response_id: str,
) -> tuple[str, int, int]:
    schema = {
        "type": "object",
        "properties": {
            "text": {"type": "string"},
        },
        "required": ["text"],
    }
    payload: dict[str, object] = {
        "source_text": prompt,
        "goal": "Generate a plain-text assistant reply for a Responses API request.",
        "response_schema_json": schema,
        "generation_instruction": (
            "Return JSON only. Provide the assistant reply in the `text` field."
        ),
    }
    if model_hint:
        payload["model"] = model_hint

    try:
        result = container.tool_execution.execute_invocation(
            ToolInvocationRequest(
                session_id=response_id,
                step_id=f"{response_id}:gemini_vortex",
                tool_name="provider.gemini_vortex.structured_generate",
                action_kind="content.generate",
                payload_json=payload,
                context_json={"principal_id": principal_id},
            )
        )
    except ToolExecutionError as exc:
        raise RuntimeError(str(exc)) from exc
    except Exception as exc:
        raise RuntimeError(f"tool_execution_failed:{exc}") from exc

    output_json = dict(result.output_json or {})
    structured = output_json.get("structured_output_json")
    if isinstance(structured, dict):
        text = str(structured.get("text") or "").strip()
        if text:
            return text, int(result.tokens_in or 0), int(result.tokens_out or 0)
    normalized = str(output_json.get("normalized_text") or "").strip()
    if normalized:
        # Best-effort fallback when the structured JSON parse did not produce the expected shape.
        return normalized, int(result.tokens_in or 0), int(result.tokens_out or 0)
    raise RuntimeError("empty_generation_result")


@router.get("/v1/models")
def list_models(request: Request) -> JSONResponse:
    # Minimal compatibility surface; Codex custom providers primarily use /v1/responses.
    return JSONResponse(
        {
            "object": "list",
            "data": [
                {
                    "id": "ea-gemini-vortex",
                    "object": "model",
                    "created": 0,
                    "owned_by": "executive-assistant",
                }
            ],
        }
    )


@router.post("/v1/responses")
def create_response(
    payload: dict[str, object],
    *,
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> JSONResponse | StreamingResponse:
    prompt = _input_text(payload)
    if not prompt:
        raise HTTPException(status_code=400, detail="input_required")
    instructions = _instructions_text(payload)
    if instructions:
        prompt = f"{instructions}\n\n{prompt}".strip()
    model = _requested_model(payload)
    model_hint = _gemini_model_hint(model)
    metadata = _metadata(payload)
    stream = bool(payload.get("stream"))

    created_at = _now_unix()
    response_id = "resp_" + uuid.uuid4().hex[:24]
    item_id = "msg_" + uuid.uuid4().hex[:24]

    if not stream:
        text, tokens_in, tokens_out = _tool_generate_text(
            container=container,
            principal_id=context.principal_id,
            prompt=prompt,
            model_hint=model_hint,
            response_id=response_id,
        )
        message = _message_item(item_id=item_id, text=text, status="completed")
        response_obj = _response_object(
            response_id=response_id,
            model=model,
            created_at=created_at,
            status="completed",
            output=[message],
            output_text=text,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            metadata=metadata,
        )
        return JSONResponse(response_obj)

    def _iter_stream() -> Iterable[str]:
        in_progress_obj = _response_object(
            response_id=response_id,
            model=model,
            created_at=created_at,
            status="in_progress",
            output=[],
            output_text="",
            tokens_in=0,
            tokens_out=0,
            metadata=metadata,
        )
        yield _sse_event(event="response.created", data={"type": "response.created", "response": in_progress_obj})
        yield _sse_event(event="response.in_progress", data={"type": "response.in_progress", "response": in_progress_obj})

        # Declare the output item before emitting deltas.
        empty_item = _message_item(item_id=item_id, text="", status="in_progress")
        yield _sse_event(
            event="response.output_item.added",
            data={
                "type": "response.output_item.added",
                "output_index": 0,
                "item": empty_item,
            },
        )
        yield _sse_event(
            event="response.content_part.added",
            data={
                "type": "response.content_part.added",
                "output_index": 0,
                "item_id": item_id,
                "content_index": 0,
                "part": {"type": "output_text", "text": "", "annotations": []},
            },
        )

        try:
            text, tokens_in, tokens_out = _tool_generate_text(
                container=container,
                principal_id=context.principal_id,
                prompt=prompt,
                model_hint=model_hint,
                response_id=response_id,
            )
        except Exception as exc:
            message = str(exc)[:500]
            yield _sse_event(
                event="error",
                data={
                    "type": "error",
                    "error": {
                        "type": "server_error",
                        "message": message,
                    },
                },
            )
            return

        chunk_size = 120
        for start in range(0, len(text), chunk_size):
            delta = text[start : start + chunk_size]
            yield _sse_event(
                event="response.output_text.delta",
                data={
                    "type": "response.output_text.delta",
                    "output_index": 0,
                    "item_id": item_id,
                    "content_index": 0,
                    "delta": delta,
                },
            )

        yield _sse_event(
            event="response.output_text.done",
            data={
                "type": "response.output_text.done",
                "output_index": 0,
                "item_id": item_id,
                "content_index": 0,
                "text": text,
            },
        )
        yield _sse_event(
            event="response.content_part.done",
            data={
                "type": "response.content_part.done",
                "output_index": 0,
                "item_id": item_id,
                "content_index": 0,
                "part": {"type": "output_text", "text": text, "annotations": []},
            },
        )

        final_item = _message_item(item_id=item_id, text=text, status="completed")
        yield _sse_event(
            event="response.output_item.done",
            data={
                "type": "response.output_item.done",
                "output_index": 0,
                "item": final_item,
            },
        )

        completed_obj = _response_object(
            response_id=response_id,
            model=model,
            created_at=created_at,
            status="completed",
            output=[final_item],
            output_text=text,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            metadata=metadata,
        )
        yield _sse_event(event="response.completed", data={"type": "response.completed", "response": completed_obj})

    return StreamingResponse(_iter_stream(), media_type="text/event-stream")

