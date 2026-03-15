from __future__ import annotations

import json
import queue
import threading
import time
import uuid
from dataclasses import dataclass
from typing import Any, Iterable

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from starlette.responses import Response

from app.api.dependencies import RequestContext, get_request_context
from app.services.responses_upstream import (
    DEFAULT_PUBLIC_MODEL,
    ResponsesUpstreamError,
    UpstreamResult,
    _provider_health_report,
    generate_text,
    list_response_models,
)


router = APIRouter(tags=["responses"])
models_router = APIRouter(prefix="/v1/models", tags=["responses"])
responses_item_router = APIRouter(prefix="/v1/responses", tags=["responses"])
STREAM_HEARTBEAT_SECONDS = 10.0
_SUPPORTED_INPUT_PART_TYPES = {"input_text", "text"}


@dataclass(frozen=True)
class _ParsedResponseInput:
    messages: list[dict[str, str]]
    input_items: list[dict[str, object]]
    prompt: str


@dataclass(frozen=True)
class _StoredResponse:
    response: dict[str, object]
    input_items: list[dict[str, object]]
    principal_id: str


_RESPONSE_STORE: dict[str, _StoredResponse] = {}
_RESPONSE_STORE_LOCK = threading.Lock()


class _ResponsesCreateRequest(BaseModel):
    model: str | None = None
    input: Any | None = None
    instructions: str | None = None
    metadata: dict[str, object] | None = None
    max_output_tokens: int | None = None
    stream: bool = False

    model_config = ConfigDict(extra="forbid")


class _ResponseUsage(BaseModel):
    input_tokens: int
    output_tokens: int
    total_tokens: int


class _ResponseOutputTextPart(BaseModel):
    type: str = "output_text"
    text: str
    annotations: list[dict[str, object]] = Field(default_factory=list)


class _ResponseOutputMessage(BaseModel):
    id: str
    type: str = "message"
    status: str
    role: str = "assistant"
    content: list[_ResponseOutputTextPart]


class _ResponseObject(BaseModel):
    id: str
    object: str = "response"
    created_at: int
    status: str
    completed_at: int | None = None
    error: dict[str, object] | None = None
    incomplete_details: dict[str, object] | None = None
    instructions: str | None = None
    input: list[dict[str, object]]
    max_output_tokens: int | None = None
    model: str
    output: list[_ResponseOutputMessage]
    usage: _ResponseUsage
    metadata: dict[str, object]
    output_text: str = ""

    model_config = ConfigDict(extra="forbid")


def _now_unix() -> int:
    return int(time.time())


def _json_dumps(payload: object) -> str:
    return json.dumps(payload, ensure_ascii=True, separators=(",", ":"))


def _sse_event(*, event: str, sequence: int, data: dict[str, object]) -> str:
    event_data = dict(data)
    event_data["sequence_number"] = sequence
    return f"event: {event}\ndata: {_json_dumps(event_data)}\n\n"


def _sse_done() -> str:
    return "data: [DONE]\n\n"


def _sse_comment(comment: str = "keep-alive") -> str:
    return f": {comment}\n\n"


def _extract_text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float, bool)):
        return str(value)
    return ""


def _normalize_message_role(role: object) -> str:
    lowered = str(role or "").strip().lower()
    if lowered in {"developer", "system"}:
        return "system"
    if lowered == "assistant":
        return "assistant"
    return "user"


def _append_message(messages: list[dict[str, str]], *, role: object, content: object) -> None:
    cleaned = str(content or "").strip()
    if not cleaned:
        return
    normalized_role = _normalize_message_role(role)
    if messages and messages[-1]["role"] == normalized_role:
        messages[-1]["content"] = f"{messages[-1]['content']}\n\n{cleaned}".strip()
        return
    messages.append({"role": normalized_role, "content": cleaned})


def _parse_input_parts(content: object, *, item_context: str) -> list[dict[str, object]]:
    parts: list[dict[str, object]] = []
    if isinstance(content, str):
        cleaned = content.strip()
        if cleaned:
            parts.append({"type": "input_text", "text": cleaned})
        return parts

    if not isinstance(content, list):
        raise HTTPException(
            status_code=400,
            detail=f"unsupported_input_content:{item_context}",
        )

    for index, entry in enumerate(content):
        if isinstance(entry, str):
            cleaned = entry.strip()
            if cleaned:
                parts.append({"type": "input_text", "text": cleaned})
            continue
        if not isinstance(entry, dict):
            raise HTTPException(
                status_code=400,
                detail=f"unsupported_input_content:{item_context}[{index}]",
            )

        part_type = str(entry.get("type") or "").strip().lower()
        if part_type == "text":
            part_type = "input_text"
        if part_type not in _SUPPORTED_INPUT_PART_TYPES:
            raise HTTPException(
                status_code=400,
                detail=f"unsupported_input_part_type:{item_context}:{part_type}",
            )

        text = _extract_text(entry.get("text"))
        if text.strip():
            parts.append({"type": "input_text", "text": text.strip()})

    return parts


def _parse_input_payload(raw_input: object | None) -> _ParsedResponseInput:
    messages: list[dict[str, str]] = []
    input_items: list[dict[str, object]] = []
    prompt_parts: list[str] = []

    if isinstance(raw_input, str):
        cleaned = raw_input.strip()
        if cleaned:
            _append_message(messages, role="user", content=cleaned)
            input_items.append({"type": "input_text", "text": cleaned})
            prompt_parts.append(cleaned)
        return _ParsedResponseInput(
            messages=messages,
            input_items=input_items,
            prompt="\n\n".join(prompt_parts).strip(),
        )

    if not isinstance(raw_input, list):
        raise HTTPException(status_code=400, detail="input_invalid")

    for index, item in enumerate(raw_input):
        item_key = f"{index}"

        if isinstance(item, str):
            cleaned = item.strip()
            if cleaned:
                _append_message(messages, role="user", content=cleaned)
                input_items.append({"type": "input_text", "text": cleaned})
                prompt_parts.append(cleaned)
            continue

        if not isinstance(item, dict):
            raise HTTPException(status_code=400, detail=f"unsupported_input_item:{item_key}")

        if item.get("type") == "message":
            role = _normalize_message_role(item.get("role"))
            parts = _parse_input_parts(item.get("content"), item_context=f"message[{item_key}].content")
            if not parts:
                continue
            text = "\n\n".join(part["text"] for part in parts if str(part.get("text") or "").strip())
            _append_message(messages, role=role, content=text)
            input_items.append({"type": "message", "role": role, "content": parts})
            prompt_parts.append(text)
            continue

        if "type" in item and str(item.get("type") or "").strip().lower() in {"input_text", "text"}:
            text = _extract_text(item.get("text"))
            cleaned = text.strip()
            if not cleaned:
                continue
            _append_message(messages, role="user", content=cleaned)
            input_items.append({"type": "input_text", "text": cleaned})
            prompt_parts.append(cleaned)
            continue

        if "role" in item or "content" in item:
            role = _normalize_message_role(item.get("role"))
            parts = _parse_input_parts(item.get("content"), item_context=f"item[{item_key}].content")
            if not parts:
                continue
            text = "\n\n".join(part["text"] for part in parts if str(part.get("text") or "").strip())
            _append_message(messages, role=role, content=text)
            input_items.append({"type": "message", "role": role, "content": parts})
            prompt_parts.append(text)
            continue

        raise HTTPException(status_code=400, detail=f"unsupported_input_item:{item_key}")

    return _ParsedResponseInput(
        messages=messages,
        input_items=input_items,
        prompt="\n\n".join(prompt_parts).strip(),
    )


def _parse_create_request(payload: dict[str, object]) -> tuple[_ResponsesCreateRequest, _ParsedResponseInput]:
    try:
        request = _ResponsesCreateRequest.model_validate(payload)
    except ValidationError as exc:
        extra_fields = [
            ".".join(str(part) for part in error.get("loc", ()))
            for error in exc.errors()
            if error.get("type") == "extra_forbidden"
        ]
        if extra_fields:
            raise HTTPException(status_code=400, detail=f"unsupported_fields:{','.join(extra_fields)}") from exc
        raise HTTPException(status_code=400, detail="invalid_request") from exc

    parsed_input = _parse_input_payload(request.input)

    if not parsed_input.messages and not parsed_input.prompt:
        raise HTTPException(status_code=400, detail="input_required")

    return request, parsed_input


def _metadata(payload: _ResponsesCreateRequest) -> dict[str, object]:
    raw = payload.metadata
    if isinstance(raw, dict):
        return {str(k): v for k, v in raw.items()}
    return {}


def _requested_model(payload: _ResponsesCreateRequest) -> str:
    model = payload.model
    if isinstance(model, str):
        return model.strip()
    return ""


def _requested_max_output_tokens(payload: _ResponsesCreateRequest) -> int | None:
    raw = payload.max_output_tokens
    if raw is None:
        return None
    try:
        value = int(raw)
    except Exception:
        raise HTTPException(status_code=400, detail="max_output_tokens_invalid")
    if value <= 0:
        raise HTTPException(status_code=400, detail="max_output_tokens_invalid")
    return value


def _response_object(
    *,
    response_id: str,
    model: str,
    created_at: int,
    status: str,
    output: list[_ResponseOutputMessage] | None = None,
    output_text: str = "",
    tokens_in: int = 0,
    tokens_out: int = 0,
    max_output_tokens: int | None = None,
    metadata: dict[str, object] | None = None,
    instructions: str | None = None,
    error: dict[str, object] | None = None,
    incomplete_details: dict[str, object] | None = None,
    input_items: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    completed_at = created_at if status == "completed" else None
    usage = _ResponseUsage(
        input_tokens=int(tokens_in or 0),
        output_tokens=int(tokens_out or 0),
        total_tokens=int((tokens_in or 0) + (tokens_out or 0)),
    )
    response_obj = _ResponseObject(
        id=response_id,
        created_at=created_at,
        status=status,
        completed_at=completed_at,
        error=error,
        incomplete_details=incomplete_details,
        instructions=instructions,
        input=list(input_items or []),
        max_output_tokens=max_output_tokens,
        model=model or "",
        output=list(output or []),
        usage=usage,
        metadata=dict(metadata or {}),
        output_text=output_text,
    )
    return response_obj.model_dump(mode="json")


def _message_item(*, item_id: str, text: str, status: str) -> _ResponseOutputMessage:
    return _ResponseOutputMessage(
        id=item_id,
        status=status,
        content=[_ResponseOutputTextPart(text=text)],
    )


def _store_response(
    *,
    response_id: str,
    response_obj: dict[str, object],
    input_items: list[dict[str, object]],
    principal_id: str,
) -> None:
    with _RESPONSE_STORE_LOCK:
        _RESPONSE_STORE[response_id] = _StoredResponse(
            response=dict(response_obj),
            input_items=[dict(item) for item in input_items],
            principal_id=principal_id,
        )


def _load_response(
    *,
    response_id: str,
    principal_id: str,
) -> _StoredResponse:
    with _RESPONSE_STORE_LOCK:
        stored = _RESPONSE_STORE.get(response_id)
    if stored is None:
        raise HTTPException(status_code=404, detail="response_not_found")
    if stored.principal_id != principal_id:
        raise HTTPException(status_code=403, detail="principal_scope_mismatch")
    return stored


def _generate_upstream_text(
    *,
    prompt: str,
    messages: list[dict[str, str]] | None = None,
    requested_model: str,
    max_output_tokens: int | None = None,
) -> UpstreamResult:
    try:
        return generate_text(
            prompt=prompt,
            messages=messages,
            requested_model=requested_model,
            max_output_tokens=max_output_tokens,
        )
    except ResponsesUpstreamError as exc:
        raise HTTPException(status_code=502, detail=f"upstream_unavailable:{exc}") from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"upstream_unavailable:{exc}") from exc


def _build_failed_response(
    *,
    response_id: str,
    created_at: int,
    model: str,
    requested_max_output_tokens: int | None,
    metadata: dict[str, object],
    instructions: str | None,
    input_items: list[dict[str, object]],
    failure_message: str,
) -> dict[str, object]:
    return _response_object(
        response_id=response_id,
        model=model,
        created_at=created_at,
        status="failed",
        output=[],
        output_text="",
        tokens_in=0,
        tokens_out=0,
        max_output_tokens=requested_max_output_tokens,
        metadata=metadata,
        instructions=instructions,
        input_items=input_items,
        error={"code": "upstream_unavailable", "message": failure_message},
        incomplete_details={"type": "error", "reason": failure_message},
    )


def _error_event_payload(message: str) -> dict[str, object]:
    return {
        "error": {
            "code": "upstream_unavailable",
            "message": message,
            "param": None,
        },
    }


@models_router.get("", response_model=None)
def list_models(request: Request) -> Response:
    return JSONResponse(
        {
            "object": "list",
            "data": list_response_models(),
        }
    )


@responses_item_router.get("/_provider_health", response_model=None)
def get_provider_health(
    *,
    context: RequestContext = Depends(get_request_context),
) -> Response:
    return JSONResponse(_provider_health_report())


@responses_item_router.get("/{response_id}", response_model=None)
def get_response(
    response_id: str,
    *,
    context: RequestContext = Depends(get_request_context),
) -> Response:
    stored = _load_response(response_id=response_id, principal_id=context.principal_id)
    return JSONResponse(stored.response)


@responses_item_router.get("/{response_id}/input_items", response_model=None)
def get_response_input_items(
    response_id: str,
    *,
    context: RequestContext = Depends(get_request_context),
) -> Response:
    stored = _load_response(response_id=response_id, principal_id=context.principal_id)
    return JSONResponse(
        {
            "object": "list",
            "response_id": response_id,
            "data": [dict(item) for item in stored.input_items],
        }
    )


@responses_item_router.post("", response_model=None)
def create_response(
    payload: dict[str, object],
    *,
    context: RequestContext = Depends(get_request_context),
) -> Response:
    request, parsed_input = _parse_create_request(payload)
    model = _requested_model(request) or DEFAULT_PUBLIC_MODEL
    max_output_tokens = _requested_max_output_tokens(request)
    metadata = _metadata(request)
    stream = bool(request.stream)
    instructions = request.instructions.strip() if isinstance(request.instructions, str) else None

    messages: list[dict[str, str]] = []
    if instructions:
        _append_message(messages, role="system", content=instructions)
    for item in parsed_input.messages:
        _append_message(messages, role=item.get("role"), content=item.get("content"))

    created_at = _now_unix()
    response_id = "resp_" + uuid.uuid4().hex[:24]
    item_id = "msg_" + uuid.uuid4().hex[:24]

    metadata = {
        **metadata,
        "principal_id": context.principal_id,
    }

    if not stream:
        result = _generate_upstream_text(
            prompt=parsed_input.prompt,
            messages=messages,
            requested_model=model,
            max_output_tokens=max_output_tokens,
        )
        final_metadata = {
            **metadata,
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
            metadata=final_metadata,
            instructions=instructions,
            input_items=parsed_input.input_items,
        )
        _store_response(
            response_id=response_id,
            response_obj=response_obj,
            input_items=parsed_input.input_items,
            principal_id=context.principal_id,
        )
        return JSONResponse(response_obj)

    def _iter_stream() -> Iterable[str]:
        sequence = 0

        def _next_sequence() -> int:
            nonlocal sequence
            sequence += 1
            return sequence

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
            instructions=instructions,
            input_items=parsed_input.input_items,
        )
        yield _sse_event(
            event="response.created",
            sequence=_next_sequence(),
            data={"type": "response.created", "response": in_progress_obj},
        )
        yield _sse_event(
            event="response.in_progress",
            sequence=_next_sequence(),
            data={"type": "response.in_progress", "response": in_progress_obj},
        )

        empty_item = _message_item(item_id=item_id, text="", status="in_progress")
        yield _sse_event(
            event="response.output_item.added",
            sequence=_next_sequence(),
            data={
                "type": "response.output_item.added",
                "output_index": 0,
                "item": empty_item.model_dump(mode="json"),
            },
        )
        yield _sse_event(
            event="response.content_part.added",
            sequence=_next_sequence(),
            data={
                "type": "response.content_part.added",
                "output_index": 0,
                "item_id": item_id,
                "content_index": 0,
                "part": {"type": "output_text", "text": "", "annotations": []},
            },
        )

        result_queue: queue.Queue[tuple[str, object]] = queue.Queue(maxsize=1)

        def _run_upstream() -> None:
            try:
                result = _generate_upstream_text(
                    prompt=parsed_input.prompt,
                    messages=messages,
                    requested_model=model,
                    max_output_tokens=max_output_tokens,
                )
                result_queue.put(("result", result))
            except Exception as exc:
                result_queue.put(("error", exc))

        worker = threading.Thread(target=_run_upstream, daemon=True)
        worker.start()

        state: tuple[str, object] | None = None
        while state is None:
            try:
                state = result_queue.get(timeout=STREAM_HEARTBEAT_SECONDS)
            except queue.Empty:
                yield _sse_comment()

        status, result_payload = state
        if status != "result":
            failure = result_payload if isinstance(result_payload, Exception) else RuntimeError(str(result_payload))
            failure_message = str(failure)[:500]
            failed_obj = _build_failed_response(
                response_id=response_id,
                created_at=created_at,
                model=model,
                requested_max_output_tokens=max_output_tokens,
                metadata=metadata,
                instructions=instructions,
                input_items=parsed_input.input_items,
                failure_message=failure_message,
            )
            _store_response(
                response_id=response_id,
                response_obj=failed_obj,
                input_items=parsed_input.input_items,
                principal_id=context.principal_id,
            )
            yield _sse_event(
                event="response.failed",
                sequence=_next_sequence(),
                data={
                    "type": "response.failed",
                    "response": failed_obj,
                },
            )
            yield _sse_event(
                event="error",
                sequence=_next_sequence(),
                data=_error_event_payload(failure_message),
            )
            yield _sse_done()
            return

        if not isinstance(result_payload, UpstreamResult):
            failure_message = "invalid_upstream_result"
            failed_obj = _build_failed_response(
                response_id=response_id,
                created_at=created_at,
                model=model,
                requested_max_output_tokens=max_output_tokens,
                metadata=metadata,
                instructions=instructions,
                input_items=parsed_input.input_items,
                failure_message=failure_message,
            )
            _store_response(
                response_id=response_id,
                response_obj=failed_obj,
                input_items=parsed_input.input_items,
                principal_id=context.principal_id,
            )
            yield _sse_event(
                event="response.failed",
                sequence=_next_sequence(),
                data={
                    "type": "response.failed",
                    "response": failed_obj,
                },
            )
            yield _sse_event(
                event="error",
                sequence=_next_sequence(),
                data=_error_event_payload(failure_message),
            )
            yield _sse_done()
            return

        result = result_payload

        stream_metadata = {
            **metadata,
            "upstream_provider": result.provider_key,
            "upstream_model": result.model,
        }
        text = result.text

        chunk_size = 120
        for start in range(0, len(text), chunk_size):
            delta = text[start : start + chunk_size]
            yield _sse_event(
                event="response.output_text.delta",
                sequence=_next_sequence(),
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
            sequence=_next_sequence(),
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
            sequence=_next_sequence(),
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
            sequence=_next_sequence(),
            data={
                "type": "response.output_item.done",
                "output_index": 0,
                "item": final_item.model_dump(mode="json"),
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
            instructions=instructions,
            input_items=parsed_input.input_items,
        )
        _store_response(
            response_id=response_id,
            response_obj=completed_obj,
            input_items=parsed_input.input_items,
            principal_id=context.principal_id,
        )

        yield _sse_event(
            event="response.completed",
            sequence=_next_sequence(),
            data={
                "type": "response.completed",
                "response": completed_obj,
            },
        )
        yield _sse_event(
            event="response.done",
            sequence=_next_sequence(),
            data={
                "type": "response.done",
                "response": completed_obj,
            },
        )
        yield _sse_done()

    return StreamingResponse(_iter_stream(), media_type="text/event-stream")


router.include_router(models_router)
router.include_router(responses_item_router)
