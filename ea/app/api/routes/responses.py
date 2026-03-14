from __future__ import annotations

import json
import time
import uuid
from typing import Any, Iterable

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from starlette.responses import Response

from app.api.dependencies import RequestContext, get_request_context
from app.services.responses_upstream import (
    DEFAULT_PUBLIC_MODEL,
    ResponsesUpstreamError,
    UpstreamResult,
    generate_text,
    list_response_models,
)


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


def _requested_max_output_tokens(payload: dict[str, object]) -> int | None:
    raw = payload.get("max_output_tokens")
    if raw is None:
        return None
    try:
        value = int(raw)
    except Exception:
        return None
    if value <= 0:
        return None
    return value


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
    max_output_tokens: int | None = None,
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
        "max_output_tokens": max_output_tokens,
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


def _generate_upstream_text(*, prompt: str, requested_model: str, max_output_tokens: int | None = None) -> UpstreamResult:
    try:
        return generate_text(
            prompt=prompt,
            requested_model=requested_model,
            max_output_tokens=max_output_tokens,
        )
    except ResponsesUpstreamError as exc:
        raise HTTPException(status_code=502, detail=f"upstream_unavailable:{exc}") from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"upstream_unavailable:{exc}") from exc


@router.get("/v1/models", response_model=None)
def list_models(request: Request) -> Response:
    return JSONResponse(
        {
            "object": "list",
            "data": list_response_models(),
        }
    )


@router.post("/v1/responses", response_model=None)
def create_response(
    payload: dict[str, object],
    *,
    context: RequestContext = Depends(get_request_context),
) -> Response:
    prompt = _input_text(payload)
    if not prompt:
        raise HTTPException(status_code=400, detail="input_required")
    instructions = _instructions_text(payload)
    if instructions:
        prompt = f"{instructions}\n\n{prompt}".strip()
    model = _requested_model(payload) or DEFAULT_PUBLIC_MODEL
    max_output_tokens = _requested_max_output_tokens(payload)
    metadata = _metadata(payload)
    stream = bool(payload.get("stream"))

    created_at = _now_unix()
    response_id = "resp_" + uuid.uuid4().hex[:24]
    item_id = "msg_" + uuid.uuid4().hex[:24]

    if not stream:
        result = _generate_upstream_text(
            prompt=prompt,
            requested_model=model,
            max_output_tokens=max_output_tokens,
        )
        metadata = {
            **metadata,
            "principal_id": context.principal_id,
            "upstream_provider": result.provider_key,
            "upstream_model": result.model,
        }
        text = result.text
        message = _message_item(item_id=item_id, text=text, status="completed")
        response_obj = _response_object(
            response_id=response_id,
            model=model,
            created_at=created_at,
            status="completed",
            output=[message],
            output_text=text,
            tokens_in=result.tokens_in,
            tokens_out=result.tokens_out,
            max_output_tokens=max_output_tokens,
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
            max_output_tokens=max_output_tokens,
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
            result = _generate_upstream_text(
                prompt=prompt,
                requested_model=model,
                max_output_tokens=max_output_tokens,
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
        stream_metadata = {
            **metadata,
            "principal_id": context.principal_id,
            "upstream_provider": result.provider_key,
            "upstream_model": result.model,
        }
        text = result.text

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
            tokens_in=result.tokens_in,
            tokens_out=result.tokens_out,
            max_output_tokens=max_output_tokens,
            metadata=stream_metadata,
        )
        yield _sse_event(event="response.completed", data={"type": "response.completed", "response": completed_obj})

    return StreamingResponse(_iter_stream(), media_type="text/event-stream")
