from __future__ import annotations

import json
import queue
import threading
import time
import uuid
from dataclasses import dataclass
from typing import Any, Callable, Iterable

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from starlette.responses import Response

from app.api.dependencies import RequestContext, get_container, get_request_context
from app.domain.models import ToolInvocationRequest
from app.services.tool_execution_common import ToolExecutionError
from app.services.responses_upstream import (
    DEFAULT_PUBLIC_MODEL,
    ResponsesUpstreamError,
    UpstreamResult,
    _provider_health_report,
    _provider_order,
    generate_text,
    list_response_models,
)


router = APIRouter(tags=["responses"])
models_router = APIRouter(prefix="/v1/models", tags=["responses"])
responses_item_router = APIRouter(prefix="/v1/responses", tags=["responses"])
codex_router = APIRouter(prefix="/v1/codex", tags=["responses"])
STREAM_HEARTBEAT_SECONDS = 10.0
_SUPPORTED_INPUT_PART_TYPES = {"input_text", "text", "output_text"}


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

_CODEx_PROFILES = (
    {
        "profile": "core",
        "lane": "hard",
        "model": "ea-coder-hard",
        "provider_hint_order": ("onemin",),
        "review_required": True,
        "needs_review": True,
        "risk_labels": ["high_impact", "code_change"],
        "merge_policy": "require_review",
    },
    {
        "profile": "easy",
        "lane": "fast",
        "model": "ea-coder-fast",
        "provider_hint_order": ("magixai",),
        "review_required": False,
        "needs_review": False,
        "risk_labels": ["low_impact", "assist"],
        "merge_policy": "auto",
    },
    {
        "profile": "audit",
        "lane": "audit",
        "model": "ea-audit-jury",
        "provider_hint_order": ("chatplayground",),
        "review_required": True,
        "needs_review": True,
        "risk_labels": ["publish", "high_risk", "multi_view"],
        "merge_policy": "require_review",
    },
)


class _ResponsesCreateRequest(BaseModel):
    model: str | None = None
    input: Any | None = None
    instructions: str | None = None
    metadata: dict[str, object] | None = None
    max_output_tokens: int | None = None
    stream: bool = False
    tools: list[dict[str, object]] | None = None
    tool_choice: Any | None = None
    parallel_tool_calls: bool | None = None
    reasoning: Any | None = None
    store: bool | None = None
    include: list[str] | None = None
    service_tier: str | None = None
    prompt_cache_key: str | None = None

    model_config = ConfigDict(extra="forbid")


class _ModelObject(BaseModel):
    id: str
    object: str = "model"
    created: int = 0
    owned_by: str

    model_config = ConfigDict(extra="forbid")


class _ModelListObject(BaseModel):
    object: str = "list"
    data: list[_ModelObject]

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


class _ResponseInputItemsListObject(BaseModel):
    object: str = "list"
    response_id: str
    data: list[dict[str, object]]

    model_config = ConfigDict(extra="forbid")


_RESPONSES_CREATE_REQUEST_SCHEMA = _ResponsesCreateRequest.model_json_schema()


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
        if part_type in {"text", "output_text"}:
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


def _accepted_client_fields(payload: _ResponsesCreateRequest) -> list[str]:
    accepted: list[str] = []
    if payload.tools:
        accepted.append("tools")
    if payload.tool_choice is not None:
        accepted.append("tool_choice")
    if payload.parallel_tool_calls is not None:
        accepted.append("parallel_tool_calls")
    if payload.reasoning is not None:
        accepted.append("reasoning")
    if payload.store is not None:
        accepted.append("store")
    if payload.include:
        accepted.append("include")
    if payload.service_tier:
        accepted.append("service_tier")
    if payload.prompt_cache_key:
        accepted.append("prompt_cache_key")
    return accepted


def _should_store_response(payload: _ResponsesCreateRequest) -> bool:
    # Keep OpenAI-compatible default behavior (`store=true` by default), but
    # respect explicit opt-out from clients that do not want retrieval state.
    return payload.store is not False


def _codex_profile(profile: str) -> dict[str, object]:
    for item in _CODEx_PROFILES:
        if item["profile"] == profile:
            return dict(item)
    return {
        "profile": profile,
        "lane": "default",
        "model": DEFAULT_PUBLIC_MODEL,
        "provider_hint_order": tuple(_provider_order()) if profile else (),
        "review_required": False,
        "needs_review": False,
    }


def _normalize_payload_for_profile(payload: dict[str, object], *, profile: str) -> dict[str, object]:
    profile_config = _codex_profile(profile)
    normalized = dict(payload)
    normalized["model"] = str(profile_config["model"])
    return normalized


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
    chatplayground_audit_callback: Callable[..., Any] | None = None,
    chatplayground_audit_callback_only: bool = False,
    chatplayground_audit_principal_id: str = "",
) -> UpstreamResult:
    try:
        return generate_text(
            prompt=prompt,
            messages=messages,
            requested_model=requested_model,
            max_output_tokens=max_output_tokens,
            chatplayground_audit_callback=chatplayground_audit_callback,
            chatplayground_audit_callback_only=chatplayground_audit_callback_only,
            chatplayground_audit_principal_id=chatplayground_audit_principal_id,
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


def _run_response(
    request_payload: dict[str, object],
    *,
    context: RequestContext,
    container: object | None = None,
    codex_profile: str | None = None,
) -> Response:
    request, parsed_input = _parse_create_request(request_payload)
    model = _requested_model(request) or DEFAULT_PUBLIC_MODEL
    profile_config: dict[str, object] | None = None
    if codex_profile:
        profile_config = _codex_profile(codex_profile)
        codex_model = profile_config.get("model")
        if isinstance(codex_model, str) and codex_model:
            model = codex_model

    requested_model = _requested_model(request)
    is_audit_profile = codex_profile == "audit"
    is_audit_model = requested_model in {"ea-audit", "ea-audit-jury"}
    audit_profile_or_model = is_audit_profile or is_audit_model
    chatplayground_audit_callback = None
    if audit_profile_or_model:
        def _chatplayground_audit_callback(**kwargs: Any) -> Any:
            prompt = str(kwargs.get("prompt") or "").strip()
            if not prompt:
                raise RuntimeError("chatplayground_audit_prompt_required")
            tool_execution = getattr(container, "tool_execution", None)
            if tool_execution is None:
                raise RuntimeError("chatplayground_tool_execution_unavailable")
            invocation = ToolInvocationRequest(
                session_id=f"codex-audit:{uuid.uuid4().hex}",
                step_id=f"codex-audit-step:{uuid.uuid4().hex}",
                tool_name="browseract.chatplayground_audit",
                action_kind="chatplayground_audit",
                payload_json=dict(kwargs),
                context_json={"principal_id": context.principal_id},
            )
            try:
                result = tool_execution.execute_invocation(invocation)
            except ToolExecutionError as exc:
                raise RuntimeError(str(exc)) from exc
            return result.output_json

        chatplayground_audit_callback = _chatplayground_audit_callback
        if container is None:
            chatplayground_audit_callback = None

    max_output_tokens = _requested_max_output_tokens(request)
    metadata = _metadata(request)
    stream = bool(request.stream)
    instructions = request.instructions.strip() if isinstance(request.instructions, str) else None
    accepted_client_fields = _accepted_client_fields(request)

    messages: list[dict[str, str]] = []
    if instructions:
        _append_message(messages, role="system", content=instructions)
    for item in parsed_input.messages:
        _append_message(messages, role=item.get("role"), content=item.get("content"))

    created_at = _now_unix()
    response_id = "resp_" + uuid.uuid4().hex[:24]
    item_id = "msg_" + uuid.uuid4().hex[:24]

    response_metadata = {
        **metadata,
        "principal_id": context.principal_id,
    }
    if accepted_client_fields:
        response_metadata["accepted_client_fields"] = accepted_client_fields
    if codex_profile:
        response_metadata.update(
            {
                "codex_profile": codex_profile,
                "codex_lane": profile_config.get("lane") if profile_config else None,
                "codex_review_required": bool(profile_config.get("review_required")) if isinstance(profile_config, dict) else None,
                "codex_needs_review": bool(profile_config.get("needs_review")) if isinstance(profile_config, dict) else None,
                "codex_risk_labels": list(profile_config.get("risk_labels", [])) if isinstance(profile_config, dict) else None,
                "codex_merge_policy": profile_config.get("merge_policy") if isinstance(profile_config, dict) else None,
                "codex_provider_hint_order": list(profile_config.get("provider_hint_order", []))
                if isinstance(profile_config, dict)
                else None,
            }
        )

    if not stream:
        result = _generate_upstream_text(
            prompt=parsed_input.prompt,
            messages=messages,
            requested_model=model,
            max_output_tokens=max_output_tokens,
            chatplayground_audit_callback=chatplayground_audit_callback,
            chatplayground_audit_callback_only=audit_profile_or_model,
            chatplayground_audit_principal_id=context.principal_id,
        )
        final_metadata = {
            **response_metadata,
            "upstream_provider": result.provider_key,
            "upstream_model": result.model,
            "provider_backend": result.provider_backend,
            "provider_account_name": result.provider_account_name,
            "provider_key_slot": result.provider_key_slot,
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
        if _should_store_response(request):
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
            metadata=response_metadata,
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
                    chatplayground_audit_callback=chatplayground_audit_callback,
                    chatplayground_audit_callback_only=audit_profile_or_model,
                    chatplayground_audit_principal_id=context.principal_id,
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
                metadata=response_metadata,
                instructions=instructions,
                input_items=parsed_input.input_items,
                failure_message=failure_message,
            )
            if _should_store_response(request):
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
                metadata=response_metadata,
                instructions=instructions,
                input_items=parsed_input.input_items,
                failure_message=failure_message,
            )
            if _should_store_response(request):
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
            **response_metadata,
            "upstream_provider": result.provider_key,
            "upstream_model": result.model,
            "provider_backend": result.provider_backend,
            "provider_account_name": result.provider_account_name,
            "provider_key_slot": result.provider_key_slot,
            "upstream_fallback_reason": result.fallback_reason,
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
        if _should_store_response(request):
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


@models_router.get("", response_model=_ModelListObject)
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


@responses_item_router.get("/{response_id}", response_model=_ResponseObject)
def get_response(
    response_id: str,
    *,
    context: RequestContext = Depends(get_request_context),
) -> Response:
    stored = _load_response(response_id=response_id, principal_id=context.principal_id)
    return JSONResponse(stored.response)


@responses_item_router.get("/{response_id}/input_items", response_model=_ResponseInputItemsListObject)
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


@responses_item_router.post(
    "",
    response_model=_ResponseObject,
    responses={
        200: {
            "description": "Returns JSON when stream=false, SSE when stream=true.",
            "content": {
                "text/event-stream": {
                    "schema": {
                        "type": "string",
                        "example": "event: response.created\\ndata: {\"type\":\"response.created\"}\\n\\ndata: [DONE]\\n\\n",
                    }
                }
            },
        }
    },
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {
                "application/json": {
                    "schema": _RESPONSES_CREATE_REQUEST_SCHEMA,
                }
            },
        }
    },
)
def create_response(
    payload: dict[str, object],
    *,
    context: RequestContext = Depends(get_request_context),
) -> Response:
    return _run_response(payload, context=context)


@codex_router.post(
    "/core",
    response_model=_ResponseObject,
    responses={
        200: {
            "description": "Returns JSON when stream=false, SSE when stream=true.",
            "content": {
                "text/event-stream": {
                    "schema": {
                        "type": "string",
                        "example": "event: response.created\\ndata: {\"type\":\"response.created\"}\\n\\ndata: [DONE]\\n\\n",
                    }
                }
            },
        }
    },
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {
                "application/json": {
                    "schema": _RESPONSES_CREATE_REQUEST_SCHEMA,
                }
            },
        }
    },
)
def create_codex_core(
    payload: dict[str, object],
    *,
    context: RequestContext = Depends(get_request_context),
) -> Response:
    normalized = _normalize_payload_for_profile(payload, profile="core")
    return _run_response(normalized, context=context, codex_profile="core")


@codex_router.post(
    "/easy",
    response_model=_ResponseObject,
    responses={
        200: {
            "description": "Returns JSON when stream=false, SSE when stream=true.",
            "content": {
                "text/event-stream": {
                    "schema": {
                        "type": "string",
                        "example": "event: response.created\\ndata: {\"type\":\"response.created\"}\\n\\ndata: [DONE]\\n\\n",
                    }
                }
            },
        }
    },
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {
                "application/json": {
                    "schema": _RESPONSES_CREATE_REQUEST_SCHEMA,
                }
            },
        }
    },
)
def create_codex_easy(
    payload: dict[str, object],
    *,
    context: RequestContext = Depends(get_request_context),
) -> Response:
    normalized = _normalize_payload_for_profile(payload, profile="easy")
    return _run_response(normalized, context=context, codex_profile="easy")


@codex_router.post(
    "/audit",
    response_model=_ResponseObject,
    responses={
        200: {
            "description": "Returns JSON when stream=false, SSE when stream=true.",
            "content": {
                "text/event-stream": {
                    "schema": {
                        "type": "string",
                        "example": "event: response.created\\ndata: {\"type\":\"response.created\"}\\n\\ndata: [DONE]\\n\\n",
                    }
                }
            },
        }
    },
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {
                "application/json": {
                    "schema": _RESPONSES_CREATE_REQUEST_SCHEMA,
                }
            },
        }
    },
)
def create_codex_audit(
    payload: dict[str, object],
    *,
    context: RequestContext = Depends(get_request_context),
    container: AppContainer = Depends(get_container),
) -> Response:
    normalized = _normalize_payload_for_profile(payload, profile="audit")
    return _run_response(normalized, context=context, container=container, codex_profile="audit")


@codex_router.get("/profiles")
def list_codex_profiles() -> Response:
    return JSONResponse(
        {
            "profiles": [
                {**profile, "provider_hint_order": list(profile["provider_hint_order"])}
                for profile in _CODEx_PROFILES
            ],
            "provider_health": _provider_health_report(),
        }
    )


router.include_router(models_router)
router.include_router(responses_item_router)
router.include_router(codex_router)
