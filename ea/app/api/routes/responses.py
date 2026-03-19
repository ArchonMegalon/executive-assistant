from __future__ import annotations

import json
import os
import queue
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from starlette.responses import Response

from app.api.dependencies import RequestContext, get_container, get_request_context
from app.container import AppContainer
from app.domain.models import ToolInvocationRequest
from app.services.brain_router import BrainRouterService
from app.services.tool_execution_common import ToolExecutionError
from app.services.brain_catalog import (
    DEFAULT_PUBLIC_MODEL,
    FAST_PUBLIC_MODEL,
    GROUNDWORK_PUBLIC_MODEL,
    REVIEW_LIGHT_PUBLIC_MODEL,
    SURVIVAL_PUBLIC_MODEL,
    get_brain_profile,
    list_brain_profiles,
)
from app.services.responses_upstream import (
    ResponsesUpstreamError,
    UpstreamResult,
    codex_status_report,
    _provider_health_report,
    _provider_order,
    generate_text,
    list_response_models,
    principal_identity_summary,
)
from app.services.survival_lane import SurvivalLaneService


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
    history_items: list[dict[str, object]]
    principal_id: str


class _ResponseRecordRepository:
    def store(
        self,
        *,
        response_id: str,
        response_obj: dict[str, object],
        input_items: list[dict[str, object]],
        history_items: list[dict[str, object]],
        principal_id: str,
    ) -> None:
        raise NotImplementedError

    def load(
        self,
        *,
        response_id: str,
        principal_id: str,
    ) -> _StoredResponse:
        raise NotImplementedError


class _MemoryResponseRecordRepository(_ResponseRecordRepository):
    def __init__(self) -> None:
        self._records: dict[str, _StoredResponse] = {}
        self._lock = threading.Lock()

    def store(
        self,
        *,
        response_id: str,
        response_obj: dict[str, object],
        input_items: list[dict[str, object]],
        history_items: list[dict[str, object]],
        principal_id: str,
    ) -> None:
        with self._lock:
            self._records[response_id] = _StoredResponse(
                response=dict(response_obj),
                input_items=[dict(item) for item in input_items],
                history_items=[dict(item) for item in history_items],
                principal_id=principal_id,
            )

    def load(
        self,
        *,
        response_id: str,
        principal_id: str,
    ) -> _StoredResponse:
        with self._lock:
            stored = self._records.get(response_id)
        if stored is None:
            raise HTTPException(status_code=404, detail="response_not_found")
        if stored.principal_id != principal_id:
            raise HTTPException(status_code=403, detail="principal_scope_mismatch")
        return stored


class _PostgresResponseRecordRepository(_ResponseRecordRepository):
    def __init__(self, database_url: str) -> None:
        self._database_url = str(database_url or "").strip()
        if not self._database_url:
            raise ValueError("database_url is required for Postgres response storage")
        self._ensure_schema()

    def _connect(self):  # type: ignore[no-untyped-def]
        try:
            import psycopg
        except Exception as exc:  # pragma: no cover - import guard
            raise RuntimeError("psycopg is required for postgres response storage") from exc
        return psycopg.connect(self._database_url, autocommit=True)

    def _json_value(self, value: object):  # type: ignore[no-untyped-def]
        from psycopg.types.json import Json

        return Json(value)

    def _ensure_schema(self) -> None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS response_records (
                        response_id TEXT PRIMARY KEY,
                        principal_id TEXT NOT NULL,
                        response_json JSONB NOT NULL,
                        input_items_json JSONB NOT NULL,
                        history_items_json JSONB NOT NULL,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    )
                    """
                )
                cur.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_response_records_principal_created
                    ON response_records(principal_id, created_at DESC)
                    """
                )

    def store(
        self,
        *,
        response_id: str,
        response_obj: dict[str, object],
        input_items: list[dict[str, object]],
        history_items: list[dict[str, object]],
        principal_id: str,
    ) -> None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO response_records (
                        response_id,
                        principal_id,
                        response_json,
                        input_items_json,
                        history_items_json
                    ) VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (response_id) DO UPDATE SET
                        principal_id = EXCLUDED.principal_id,
                        response_json = EXCLUDED.response_json,
                        input_items_json = EXCLUDED.input_items_json,
                        history_items_json = EXCLUDED.history_items_json,
                        updated_at = NOW()
                    """,
                    (
                        response_id,
                        principal_id,
                        self._json_value(response_obj),
                        self._json_value(input_items),
                        self._json_value(history_items),
                    ),
                )

    def load(
        self,
        *,
        response_id: str,
        principal_id: str,
    ) -> _StoredResponse:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT principal_id, response_json, input_items_json, history_items_json
                    FROM response_records
                    WHERE response_id = %s
                    """,
                    (response_id,),
                )
                row = cur.fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="response_not_found")
        stored_principal_id, response_json, input_items_json, history_items_json = row
        if str(stored_principal_id or "") != principal_id:
            raise HTTPException(status_code=403, detail="principal_scope_mismatch")
        return _StoredResponse(
            response=dict(response_json or {}),
            input_items=[dict(item) for item in list(input_items_json or []) if isinstance(item, dict)],
            history_items=[dict(item) for item in list(history_items_json or []) if isinstance(item, dict)],
            principal_id=str(stored_principal_id or ""),
        )


_RESPONSE_REPOSITORY_LOCK = threading.Lock()
_MEMORY_RESPONSE_REPOSITORY = _MemoryResponseRecordRepository()
_POSTGRES_RESPONSE_REPOSITORIES: dict[str, _PostgresResponseRecordRepository] = {}

_CODEx_PROFILES = tuple(
    {
        "profile": profile.profile,
        "lane": profile.lane,
        "model": profile.public_model,
        "provider_hint_order": profile.provider_hint_order,
        "review_required": bool(profile.review_required),
        "needs_review": bool(profile.needs_review),
        "risk_labels": list(profile.risk_labels),
        "merge_policy": str(profile.merge_policy or "auto"),
    }
    for profile in list_brain_profiles()
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
    previous_response_id: str | None = None

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


class _ResponseOutputFunctionCall(BaseModel):
    id: str
    type: str = "function_call"
    status: str
    call_id: str
    name: str
    arguments: str


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
    output: list[dict[str, object]]
    usage: _ResponseUsage
    metadata: dict[str, object]
    output_text: str = ""
    store: bool | None = None
    previous_response_id: str | None = None
    parallel_tool_calls: bool | None = None
    tool_choice: Any | None = None
    tools: list[dict[str, object]] | None = None
    reasoning: Any | None = None
    truncation: str | None = None

    model_config = ConfigDict(extra="forbid")


class _ResponseInputItemsListObject(BaseModel):
    object: str = "list"
    response_id: str
    data: list[dict[str, object]]

    model_config = ConfigDict(extra="forbid")


_RESPONSES_CREATE_REQUEST_SCHEMA = _ResponsesCreateRequest.model_json_schema()


def _responses_debug_capture_dir() -> Path | None:
    raw = str(os.environ.get("EA_RESPONSES_DEBUG_CAPTURE_DIR") or "").strip()
    if not raw:
        return None
    try:
        path = Path(raw)
        path.mkdir(parents=True, exist_ok=True)
        return path
    except Exception:
        return None


def _capture_responses_debug(*, name: str, payload: object) -> None:
    target_dir = _responses_debug_capture_dir()
    if target_dir is None:
        return
    try:
        stamp = int(time.time() * 1000)
        target = target_dir / f"{stamp}_{name}.json"
        target.write_text(json.dumps(payload, ensure_ascii=True, indent=2), encoding="utf-8")
        latest = target_dir / f"latest_{name}.json"
        latest.write_text(json.dumps(payload, ensure_ascii=True, indent=2), encoding="utf-8")
    except Exception:
        return


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


def _sse_heartbeat(*, sequence: int, response: dict[str, object]) -> str:
    heartbeat_response = dict(response)
    return _sse_event(
        event="response.in_progress",
        sequence=sequence,
        data={
            "type": "response.in_progress",
            "response": heartbeat_response,
            "heartbeat": True,
        },
    )


def _extract_text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float, bool)):
        return str(value)
    return ""


def _extract_textish(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, (str, int, float, bool)):
        return str(value).strip()
    if isinstance(value, list):
        parts = [_extract_textish(item) for item in value]
        return "\n".join(part for part in parts if part).strip()
    if isinstance(value, dict):
        preferred_keys = ("text", "content", "output", "result", "message", "answer")
        for key in preferred_keys:
            text = _extract_textish(value.get(key))
            if text:
                return text
    return ""


def _json_compact(value: object) -> str:
    try:
        return json.dumps(value, ensure_ascii=True, separators=(",", ":"))
    except Exception:
        return str(value)


def _extract_resume_fallback_text(value: object) -> str:
    if isinstance(value, (str, int, float, bool)):
        return str(value).strip()
    if isinstance(value, list):
        parts = [_extract_resume_fallback_text(item) for item in value]
        return "\n".join(part for part in parts if part).strip()
    if not isinstance(value, dict):
        return ""
    for key in ("text", "content", "output", "summary", "message", "result", "arguments"):
        text = _extract_textish(value.get(key))
        if text:
            return text
    return ""


def _normalize_passthrough_input_item(item: dict[str, object]) -> dict[str, object]:
    normalized: dict[str, object] = {}
    for key in (
        "id",
        "type",
        "call_id",
        "name",
        "status",
        "arguments",
        "output",
        "summary",
        "role",
        "content",
    ):
        if key in item:
            normalized[key] = item.get(key)
    if "type" not in normalized:
        normalized["type"] = str(item.get("type") or "").strip().lower()
    return normalized


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
            fallback_text = _extract_resume_fallback_text(entry)
            if fallback_text:
                parts.append({"type": "input_text", "text": fallback_text})
                continue
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
            if item is None:
                continue
            if isinstance(item, (int, float, bool)):
                cleaned = str(item).strip()
                if cleaned:
                    _append_message(messages, role="user", content=cleaned)
                    input_items.append({"type": "input_text", "text": cleaned})
                    prompt_parts.append(cleaned)
                continue
            # Some Responses clients include non-dict state entries during
            # resume/replay that are not actionable for this text-only facade.
            continue

        item_type = str(item.get("type") or "").strip().lower()

        if item_type == "function_call_output":
            call_id = str(item.get("call_id") or "").strip()
            output_text = _extract_textish(item.get("output"))
            if not call_id:
                raise HTTPException(status_code=400, detail=f"invalid_function_call_output:{item_key}")
            input_items.append(
                {
                    "type": "function_call_output",
                    "call_id": call_id,
                    "output": output_text,
                }
            )
            continue

        if item_type == "function_call":
            call_id = str(item.get("call_id") or "").strip()
            name = str(item.get("name") or "").strip()
            arguments = item.get("arguments")
            if not call_id or not name:
                raise HTTPException(status_code=400, detail=f"invalid_function_call:{item_key}")
            if isinstance(arguments, str):
                rendered_arguments = arguments
            else:
                rendered_arguments = _json_compact(arguments)
            input_items.append(
                {
                    "type": "function_call",
                    "call_id": call_id,
                    "name": name,
                    "arguments": rendered_arguments,
                }
            )
            continue

        if item_type == "reasoning":
            input_items.append(_normalize_passthrough_input_item(item))
            summary_text = _extract_textish(item.get("summary"))
            if summary_text:
                _append_message(messages, role="assistant", content=summary_text)
                prompt_parts.append(summary_text)
            continue

        if item_type.endswith("_call") or item_type.endswith("_call_output"):
            input_items.append(_normalize_passthrough_input_item(item))
            continue

        if item_type == "message":
            role = _normalize_message_role(item.get("role"))
            parts = _parse_input_parts(item.get("content"), item_context=f"message[{item_key}].content")
            if not parts:
                continue
            text = "\n\n".join(part["text"] for part in parts if str(part.get("text") or "").strip())
            _append_message(messages, role=role, content=text)
            input_items.append({"type": "message", "role": role, "content": parts})
            prompt_parts.append(text)
            continue

        if item_type in {"input_text", "text"}:
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

        fallback_text = _extract_resume_fallback_text(
            item.get("text")
            or item.get("content")
            or item.get("output")
            or item.get("summary")
            or item.get("arguments")
        )
        if fallback_text:
            _append_message(messages, role="user", content=fallback_text)
            input_items.append({"type": "input_text", "text": fallback_text})
            prompt_parts.append(fallback_text)
            continue

        # Some Responses clients send non-text state items during resume that
        # are not actionable for this text-only compatibility layer.
        if item_type:
            raise HTTPException(status_code=400, detail=f"unsupported_input_item:{item_key}")
        continue

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

    if not parsed_input.input_items:
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


def _brain_router(container: object | None = None) -> BrainRouterService | None:
    router = getattr(container, "brain_router", None)
    return router if isinstance(router, BrainRouterService) else None


def _provider_registry_payload(
    *,
    container: object | None = None,
    principal_id: str = "",
    provider_health: dict[str, object] | None = None,
) -> dict[str, object]:
    registry = getattr(container, "provider_registry", None)
    if registry is None or not hasattr(registry, "registry_read_model"):
        return {}
    router = _brain_router(container)
    profile_decisions = router.list_profile_decisions(principal_id=principal_id or None) if router is not None else ()
    return registry.registry_read_model(
        principal_id=principal_id or None,
        provider_health=provider_health or {},
        profile_decisions=profile_decisions,
    )


def _codex_profiles(
    *,
    container: object | None = None,
    principal_id: str = "",
) -> tuple[dict[str, object], ...]:
    router = _brain_router(container)
    if router is None:
        return _CODEx_PROFILES
    rows = []
    for profile in router.list_profile_decisions(principal_id=principal_id or None):
        rows.append(
            {
                "profile": profile.profile,
                "lane": profile.lane,
                "model": profile.public_model,
                "provider_hint_order": profile.provider_hint_order,
                "backend": profile.backend_key,
                "health_provider_key": profile.health_provider_key,
                "review_required": bool(profile.review_required),
                "needs_review": bool(profile.needs_review),
                "risk_labels": list(profile.risk_labels),
                "merge_policy": str(profile.merge_policy or "auto"),
            }
        )
    return tuple(rows or _CODEx_PROFILES)


def _codex_profile(profile: str, *, container: object | None = None, principal_id: str = "") -> dict[str, object]:
    for item in _codex_profiles(container=container, principal_id=principal_id):
        if item["profile"] == profile:
            return dict(item)
    return {
        "profile": profile,
        "lane": "default",
        "model": DEFAULT_PUBLIC_MODEL,
        "provider_hint_order": tuple(_provider_order()) if profile else (),
        "backend": "",
        "health_provider_key": "",
        "review_required": False,
        "needs_review": False,
    }


def _attach_provider_slot_state(
    profiles: list[dict[str, object]],
    *,
    provider_health: dict[str, object],
) -> list[dict[str, object]]:
    gemini = dict(((provider_health or {}).get("providers") or {}).get("gemini_vortex") or {})
    gemini_slots = [
        {
            "slot": item.get("slot"),
            "account_name": item.get("account_name"),
            "state": item.get("state"),
            "slot_owner": item.get("slot_owner"),
            "lease_holder": item.get("lease_holder"),
            "lease_holder_label": item.get("lease_holder_label"),
            "lease_holder_owner_category": item.get("lease_holder_owner_category"),
            "lease_holder_hub_user_id": item.get("lease_holder_hub_user_id"),
            "lease_holder_hub_group_id": item.get("lease_holder_hub_group_id"),
            "lease_holder_sponsor_session_id": item.get("lease_holder_sponsor_session_id"),
            "lease_expires_at": item.get("lease_expires_at"),
            "last_used_principal_id": item.get("last_used_principal_id"),
            "last_used_principal_label": item.get("last_used_principal_label"),
            "last_used_owner_category": item.get("last_used_owner_category"),
            "last_used_hub_user_id": item.get("last_used_hub_user_id"),
            "last_used_hub_group_id": item.get("last_used_hub_group_id"),
            "last_used_sponsor_session_id": item.get("last_used_sponsor_session_id"),
            "last_used_at": item.get("last_used_at"),
            "quota_posture": item.get("quota_posture"),
        }
        for item in gemini.get("slots") or []
        if isinstance(item, dict)
    ]
    if not gemini_slots:
        return profiles
    selection_mode = str(gemini.get("selection_mode") or "")
    configured_slots = int(gemini.get("configured_slots") or len(gemini_slots))
    enriched: list[dict[str, object]] = []
    for profile in profiles:
        hints = [str(item or "").strip() for item in profile.get("provider_hint_order") or [] if str(item or "").strip()]
        if "gemini_vortex" not in hints:
            enriched.append(profile)
            continue
        enriched.append(
            {
                **profile,
                "provider_slots": gemini_slots,
                "provider_slot_pool": {
                    "provider_key": "gemini_vortex",
                    "selection_mode": selection_mode,
                    "configured_slots": configured_slots,
                    "active_lease_count": int(gemini.get("active_lease_count") or 0),
                    "last_used_principal_id": gemini.get("last_used_principal_id"),
                    "last_used_principal_label": gemini.get("last_used_principal_label"),
                    "last_used_owner_category": gemini.get("last_used_owner_category"),
                    "last_used_hub_user_id": gemini.get("last_used_hub_user_id"),
                    "last_used_hub_group_id": gemini.get("last_used_hub_group_id"),
                    "last_used_sponsor_session_id": gemini.get("last_used_sponsor_session_id"),
                    "last_used_at": gemini.get("last_used_at"),
                },
            }
        )
    return enriched


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


def _requested_previous_response_id(payload: _ResponsesCreateRequest) -> str | None:
    value = str(payload.previous_response_id or "").strip()
    return value or None


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


def _browseract_binding_id(*, container: object | None, principal_id: str) -> str:
    if container is None or not principal_id:
        return ""
    tool_runtime = getattr(container, "tool_runtime", None)
    if tool_runtime is None:
        return ""
    try:
        bindings = tool_runtime.list_connector_bindings(principal_id, limit=100)
    except Exception:
        return ""
    for binding in bindings:
        connector_name = str(getattr(binding, "connector_name", "") or "").strip().lower()
        status = str(getattr(binding, "status", "") or "").strip().lower()
        if connector_name != "browseract":
            continue
        if status and status != "enabled":
            continue
        return str(getattr(binding, "binding_id", "") or "").strip()
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
    max_output_tokens: int | None = None,
    metadata: dict[str, object] | None = None,
    instructions: str | None = None,
    error: dict[str, object] | None = None,
    incomplete_details: dict[str, object] | None = None,
    input_items: list[dict[str, object]] | None = None,
    store: bool | None = None,
    previous_response_id: str | None = None,
    parallel_tool_calls: bool | None = None,
    tool_choice: Any | None = None,
    tools: list[dict[str, object]] | None = None,
    reasoning: Any | None = None,
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
        store=store,
        previous_response_id=previous_response_id,
        parallel_tool_calls=parallel_tool_calls,
        tool_choice=tool_choice,
        tools=list(tools or []) if tools is not None else None,
        reasoning=reasoning,
        truncation="disabled",
    )
    return response_obj.model_dump(mode="json")


def _message_item(*, item_id: str, text: str, status: str) -> dict[str, object]:
    return _ResponseOutputMessage(
        id=item_id,
        status=status,
        content=[_ResponseOutputTextPart(text=text)],
    ).model_dump(mode="json")


def _function_call_item(
    *,
    item_id: str,
    call_id: str,
    name: str,
    arguments: str,
    status: str,
) -> dict[str, object]:
    return _ResponseOutputFunctionCall(
        id=item_id,
        call_id=call_id,
        name=name,
        arguments=arguments,
        status=status,
    ).model_dump(mode="json")


def _container_database_url(container: object | None) -> str:
    if container is None:
        return ""
    settings = getattr(container, "settings", None)
    if settings is None:
        return ""
    direct = str(getattr(settings, "database_url", "") or "").strip()
    if direct:
        return direct
    storage = getattr(settings, "storage", None)
    if storage is None:
        return ""
    return str(getattr(storage, "database_url", "") or "").strip()


def _response_record_repository(container: object | None) -> _ResponseRecordRepository:
    backend = "memory"
    database_url = ""
    if container is not None:
        runtime_profile = getattr(container, "runtime_profile", None)
        backend = str(getattr(runtime_profile, "storage_backend", "memory") or "memory").strip().lower() or "memory"
        database_url = _container_database_url(container)
    else:
        backend = str(
            os.environ.get("EA_STORAGE_BACKEND")
            or os.environ.get("EA_LEDGER_BACKEND")
            or "memory"
        ).strip().lower() or "memory"
        database_url = str(os.environ.get("DATABASE_URL") or "").strip()

    if backend == "postgres" and database_url:
        with _RESPONSE_REPOSITORY_LOCK:
            repository = _POSTGRES_RESPONSE_REPOSITORIES.get(database_url)
            if repository is None:
                repository = _PostgresResponseRecordRepository(database_url)
                _POSTGRES_RESPONSE_REPOSITORIES[database_url] = repository
        return repository
    return _MEMORY_RESPONSE_REPOSITORY


def _store_response(
    *,
    response_id: str,
    response_obj: dict[str, object],
    input_items: list[dict[str, object]],
    history_items: list[dict[str, object]],
    principal_id: str,
    container: object | None = None,
) -> None:
    _response_record_repository(container).store(
        response_id=response_id,
        response_obj=response_obj,
        input_items=input_items,
        history_items=history_items,
        principal_id=principal_id,
    )


def _load_response(
    *,
    response_id: str,
    principal_id: str,
    container: object | None = None,
) -> _StoredResponse:
    return _response_record_repository(container).load(
        response_id=response_id,
        principal_id=principal_id,
    )


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


@dataclass(frozen=True)
class _ToolShimDecision:
    kind: str
    text: str = ""
    tool_name: str = ""
    arguments: dict[str, object] | None = None
    upstream_result: UpstreamResult | None = None


def _response_tools(payload: _ResponsesCreateRequest) -> list[dict[str, object]]:
    raw_tools = payload.tools
    if not isinstance(raw_tools, list):
        return []
    tools: list[dict[str, object]] = []
    for entry in raw_tools:
        if isinstance(entry, dict):
            tools.append(dict(entry))
    return tools


def _tool_shim_supported_tools(raw_tools: list[dict[str, object]]) -> list[dict[str, object]]:
    supported: list[dict[str, object]] = []
    for tool in raw_tools:
        tool_type = str(tool.get("type") or "").strip().lower()
        if tool_type != "function":
            continue
        name = str(tool.get("name") or "").strip()
        parameters = tool.get("parameters")
        if not name or not isinstance(parameters, dict):
            continue
        supported.append(
            {
                "name": name,
                "description": str(tool.get("description") or "").strip(),
                "parameters": parameters,
            }
        )
    return supported


def _history_items_for_request(
    *,
    previous_response_id: str | None,
    parsed_input: _ParsedResponseInput,
    principal_id: str,
    container: object | None = None,
) -> list[dict[str, object]]:
    history: list[dict[str, object]] = []
    if previous_response_id:
        stored = _load_response(
            response_id=previous_response_id,
            principal_id=principal_id,
            container=container,
        )
        history.extend(dict(item) for item in stored.history_items)
    history.extend(dict(item) for item in parsed_input.input_items)
    return history


def _tool_shim_transcript_max_chars() -> int:
    raw = str(os.environ.get("EA_TOOL_SHIM_TRANSCRIPT_MAX_CHARS") or "4000").strip() or "4000"
    try:
        return max(800, min(32000, int(raw)))
    except Exception:
        return 4000


def _tool_shim_transcript_part_max_chars() -> int:
    raw = str(os.environ.get("EA_TOOL_SHIM_TRANSCRIPT_PART_MAX_CHARS") or "1200").strip() or "1200"
    try:
        return max(200, min(8000, int(raw)))
    except Exception:
        return 1200


def _tool_shim_truncate_text(text: str, *, limit: int) -> str:
    value = str(text or "")
    if limit <= 0 or len(value) <= limit:
        return value
    if limit <= 96:
        return value[:limit]
    spacer = "\n\n[... omitted for compact audit transport ...]\n\n"
    remaining = limit - len(spacer)
    if remaining <= 32:
        return value[:limit]
    head = remaining // 2
    tail = remaining - head
    return f"{value[:head]}{spacer}{value[-tail:]}".strip()


def _history_item_to_transcript(item: dict[str, object], *, include_system: bool = True, compact: bool = False) -> str:
    item_type = str(item.get("type") or "").strip().lower()
    if item_type == "message":
        role = _normalize_message_role(item.get("role"))
        if role == "system" and not include_system:
            return ""
        content = item.get("content")
        text = ""
        if isinstance(content, list):
            text = "\n\n".join(
                _extract_textish(part.get("text"))
                for part in content
                if isinstance(part, dict) and _extract_textish(part.get("text"))
            ).strip()
        else:
            text = _extract_textish(content)
        if not text:
            return ""
        if compact:
            text = _tool_shim_truncate_text(text, limit=_tool_shim_transcript_part_max_chars())
        return f"{role.capitalize()}:\n{text}"
    if item_type == "input_text":
        text = _extract_textish(item.get("text"))
        if compact:
            text = _tool_shim_truncate_text(text, limit=_tool_shim_transcript_part_max_chars())
        return f"User:\n{text}" if text else ""
    if item_type == "function_call":
        name = str(item.get("name") or "").strip()
        call_id = str(item.get("call_id") or "").strip()
        arguments = str(item.get("arguments") or "").strip()
        if not name:
            return ""
        if compact:
            arguments = _tool_shim_truncate_text(arguments, limit=_tool_shim_transcript_part_max_chars())
        return (
            f"Assistant tool call ({call_id or 'no-call-id'})\n"
            f"Tool: {name}\n"
            f"Arguments: {arguments}"
        ).strip()
    if item_type == "function_call_output":
        call_id = str(item.get("call_id") or "").strip()
        output_text = _extract_textish(item.get("output"))
        if compact:
            output_text = _tool_shim_truncate_text(output_text, limit=_tool_shim_transcript_part_max_chars())
        return (
            f"Tool output ({call_id or 'no-call-id'}):\n{output_text}"
        ).strip()
    return ""


def _tool_shim_messages(
    *,
    instructions: str | None,
    tools: list[dict[str, object]],
    history_items: list[dict[str, object]],
    compact_for_audit: bool = False,
) -> list[dict[str, str]]:
    tool_names = {str(tool.get("name") or "").strip() for tool in tools}
    has_apply_patch = "apply_patch" in tool_names
    has_exec_command = "exec_command" in tool_names
    tool_catalog = []
    for tool in tools:
        tool_catalog.append(
            {
                "name": tool["name"],
                "description": tool["description"],
                "parameters": tool["parameters"],
            }
        )
    transcript_parts = [
        part
        for part in (
            _history_item_to_transcript(
                item,
                include_system=not compact_for_audit,
                compact=compact_for_audit,
            )
            for item in history_items
        )
        if part
    ]
    transcript = "\n\n".join(transcript_parts).strip()
    if compact_for_audit:
        transcript = _tool_shim_truncate_text(transcript, limit=_tool_shim_transcript_max_chars())
    system_parts = [
        "You are the planning/model layer behind an OpenAI Responses tool-calling shim used by Codex CLI.",
        "Decide the single next assistant action and return JSON only.",
        "Valid JSON responses:",
        '{"decision":"final","text":"..."}',
        '{"decision":"function_call","name":"TOOL_NAME","arguments":{...}}',
        "Rules:",
        "- Use at most one tool call.",
        "- Prefer a real tool call over describing future intent when inspection or execution is needed.",
        "- For coding or backlog tasks, inspect files and run commands before claiming conclusions.",
        "- Prefer the smallest single-purpose command that advances the work.",
        "- Do not emit multiline shell scripts, here-docs, or long quoted bash programs when a simple command sequence would do.",
        "- Prefer commands like pwd, ls, rg, sed -n, cat, git status, pytest <target>, or a small focused shell command.",
        "- If a command session is already running, prefer write_stdin with the existing session_id.",
        "- Do not repeat a tool call whose output is already present in the conversation; build on that output instead.",
        "- If a prior tool output already answers the question, return a final answer instead of rereading the same context.",
        "- Keep trace-style progress concise and textual; do not dump raw scripts into user-facing text.",
        "- Do not invent tool names or arguments outside the provided schemas.",
        "- Do not wrap the JSON in markdown fences.",
        "- If the work is complete, return a final answer.",
        "Available function tools:",
        _json_compact(tool_catalog),
    ]
    if has_exec_command and not has_apply_patch:
        system_parts.extend(
            [
                "Session constraint:",
                "- The apply_patch tool is not available in this session.",
                "- If a file edit is required, use exec_command with a short focused edit command.",
                "- Prefer one-line edits with sed -i, perl -0pi, or python3 -c for targeted replacements.",
                "- Use a short python heredoc only when no simpler edit command is practical.",
            ]
        )
    if instructions and not compact_for_audit:
        system_parts.extend(
            [
                "Original Codex instructions:",
                instructions,
            ]
        )
    elif compact_for_audit:
        system_parts.extend(
            [
                "Compact audit transport is enabled.",
                "- Hidden system/developer instructions are enforced outside this prompt.",
                "- Focus on the visible conversation and tool outputs below.",
            ]
        )
    user_prompt = transcript or "No prior conversation context."
    return [
        {"role": "system", "content": "\n".join(system_parts).strip()},
        {"role": "user", "content": f"Conversation so far:\n\n{user_prompt}\n\nReturn the next action as JSON only."},
    ]


def _completed_tool_call_signatures(history_items: list[dict[str, object]]) -> set[tuple[str, str]]:
    calls_by_id: dict[str, tuple[str, str]] = {}
    completed: set[tuple[str, str]] = set()
    for item in history_items:
        item_type = str(item.get("type") or "").strip().lower()
        if item_type == "function_call":
            call_id = str(item.get("call_id") or "").strip()
            name = str(item.get("name") or "").strip()
            arguments = str(item.get("arguments") or "").strip()
            if call_id and name:
                calls_by_id[call_id] = (name, arguments)
            continue
        if item_type == "function_call_output":
            call_id = str(item.get("call_id") or "").strip()
            if call_id and call_id in calls_by_id:
                completed.add(calls_by_id[call_id])
    return completed


def _extract_json_object(text: str) -> dict[str, object] | None:
    stripped = str(text or "").strip()
    if not stripped:
        return None
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if len(lines) >= 3:
            stripped = "\n".join(lines[1:-1]).strip()
    candidates: list[str] = []
    candidates.append(stripped)
    first = stripped.find("{")
    last = stripped.rfind("}")
    if first != -1 and last != -1 and last > first:
        candidates.append(stripped[first : last + 1])
    for candidate in candidates:
        try:
            payload = json.loads(candidate)
        except Exception:
            continue
        if isinstance(payload, dict):
            return payload
    return None


def _tool_call_rejection_reason(
    *,
    tool_name: str,
    arguments: dict[str, object],
    history_items: list[dict[str, object]],
    available_tools: list[dict[str, object]],
) -> str | None:
    signature = (tool_name, _json_compact(arguments))
    if signature in _completed_tool_call_signatures(history_items):
        return (
            "That exact tool call already ran and its output is already present. "
            "Use the existing output and choose a different next action or return a final answer."
        )
    if tool_name == "exec_command":
        raw_cmd = arguments.get("cmd")
        if isinstance(raw_cmd, str):
            cmd = raw_cmd.strip()
            tool_names = {str(tool.get("name") or "").strip() for tool in available_tools}
            has_apply_patch = "apply_patch" in tool_names
            edit_markers = (
                "sed -i",
                "perl -0pi",
                "python3 -c",
                "python -c",
                "python3 - <<'PY'",
                "python - <<'PY'",
            )
            is_edit_command = any(marker in cmd for marker in edit_markers)
            if not has_apply_patch and is_edit_command:
                if len(cmd) > 1400 or cmd.count("\n") > 24:
                    return (
                        "The edit command is too large. Use a shorter focused edit command "
                        "that changes only the needed lines."
                    )
                return None
            if "\n" in cmd or len(cmd) > 280:
                return (
                    "The exec_command payload is too large. Use a shorter, single-purpose command "
                    "instead of a multiline or oversized shell script."
                )
    return None


def _tool_shim_retry_payload(
    *,
    model: str,
    max_output_tokens: int | None,
    shim_messages: list[dict[str, str]],
    prior_payload: dict[str, object],
    retry_reason: str,
    chatplayground_audit_callback: Callable[..., Any] | None = None,
    chatplayground_audit_callback_only: bool = False,
    chatplayground_audit_principal_id: str = "",
) -> tuple[dict[str, object] | None, UpstreamResult]:
    retry_messages = list(shim_messages)
    retry_messages.append({"role": "assistant", "content": _json_compact(prior_payload)})
    retry_messages.append(
        {
            "role": "user",
            "content": f"{retry_reason}\nReturn a corrected next action as JSON only.",
        }
    )
    retry_result = _generate_upstream_text(
        prompt=retry_messages[-1]["content"],
        messages=retry_messages,
        requested_model=model,
        max_output_tokens=max_output_tokens,
        chatplayground_audit_callback=chatplayground_audit_callback,
        chatplayground_audit_callback_only=chatplayground_audit_callback_only,
        chatplayground_audit_principal_id=chatplayground_audit_principal_id,
    )
    return _extract_json_object(retry_result.text), retry_result


def _tool_shim_decision(
    *,
    model: str,
    max_output_tokens: int | None,
    instructions: str | None,
    tools: list[dict[str, object]],
    history_items: list[dict[str, object]],
    chatplayground_audit_callback: Callable[..., Any] | None = None,
    chatplayground_audit_callback_only: bool = False,
    chatplayground_audit_principal_id: str = "",
) -> _ToolShimDecision:
    shim_messages = _tool_shim_messages(
        instructions=instructions,
        tools=tools,
        history_items=history_items,
        compact_for_audit=chatplayground_audit_callback_only,
    )
    shim_prompt = shim_messages[-1]["content"]
    result = _generate_upstream_text(
        prompt=shim_prompt,
        messages=shim_messages,
        requested_model=model,
        max_output_tokens=max_output_tokens,
        chatplayground_audit_callback=chatplayground_audit_callback,
        chatplayground_audit_callback_only=chatplayground_audit_callback_only,
        chatplayground_audit_principal_id=chatplayground_audit_principal_id,
    )
    payload = _extract_json_object(result.text)
    if not isinstance(payload, dict):
        return _ToolShimDecision(kind="final", text=result.text, upstream_result=result)
    decision = str(payload.get("decision") or "").strip().lower()
    if decision == "function_call":
        tool_name = str(payload.get("name") or "").strip()
        arguments = payload.get("arguments")
        if tool_name and isinstance(arguments, dict):
            retry_reason = _tool_call_rejection_reason(
                tool_name=tool_name,
                arguments=arguments,
                history_items=history_items,
                available_tools=tools,
            )
            if retry_reason:
                retry_payload, retry_result = _tool_shim_retry_payload(
                    model=model,
                    max_output_tokens=max_output_tokens,
                    shim_messages=shim_messages,
                    prior_payload=payload,
                    retry_reason=retry_reason,
                    chatplayground_audit_callback=chatplayground_audit_callback,
                    chatplayground_audit_callback_only=chatplayground_audit_callback_only,
                    chatplayground_audit_principal_id=chatplayground_audit_principal_id,
                )
                if isinstance(retry_payload, dict):
                    payload = retry_payload
                    result = retry_result
                    decision = str(payload.get("decision") or "").strip().lower()
    if decision == "function_call":
        tool_name = str(payload.get("name") or "").strip()
        arguments = payload.get("arguments")
        if tool_name and isinstance(arguments, dict) and any(tool["name"] == tool_name for tool in tools):
            return _ToolShimDecision(
                kind="function_call",
                tool_name=tool_name,
                arguments=arguments,
                upstream_result=result,
            )
    final_text = _extract_textish(payload.get("text")) or result.text
    return _ToolShimDecision(kind="final", text=final_text, upstream_result=result)


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


def _survival_max_output_tokens() -> int:
    raw = str(os.environ.get("EA_SURVIVAL_MAX_OUTPUT_TOKENS") or "768").strip() or "768"
    try:
        value = int(raw)
    except Exception:
        value = 768
    return max(32, min(4096, value))


def _survival_rejected_fields(payload: _ResponsesCreateRequest) -> list[str]:
    refuse_tools = str(os.environ.get("EA_SURVIVAL_REFUSE_CLIENT_TOOLS") or "1").strip().lower() not in {"0", "false", "no", "off"}
    rejected: list[str] = []
    if refuse_tools and payload.tools:
        rejected.append("tools")
    if refuse_tools and payload.tool_choice is not None:
        rejected.append("tool_choice")
    if refuse_tools and payload.parallel_tool_calls is not None:
        rejected.append("parallel_tool_calls")
    return rejected


def _run_survival_response(
    request: _ResponsesCreateRequest,
    *,
    parsed_input: _ParsedResponseInput,
    context: RequestContext,
    container: object | None,
    codex_profile: str | None,
    profile_config: dict[str, object] | None,
    model: str,
    metadata: dict[str, object],
    history_items: list[dict[str, object]],
    previous_response_id: str | None,
) -> Response:
    if str(os.environ.get("EA_SURVIVAL_ENABLED") or "1").strip().lower() in {"0", "false", "no", "off"}:
        raise HTTPException(status_code=503, detail="survival_lane_disabled")
    if request.stream:
        raise HTTPException(status_code=400, detail="survival_stream_not_supported_yet")
    rejected_fields = _survival_rejected_fields(request)
    if rejected_fields:
        raise HTTPException(status_code=400, detail=f"survival_unsupported_fields:{','.join(rejected_fields)}")
    if request.store is False:
        raise HTTPException(status_code=400, detail="survival_requires_store")

    created_at = _now_unix()
    response_id = "resp_" + uuid.uuid4().hex[:24]
    requested_max_output_tokens = _requested_max_output_tokens(request)
    max_output_tokens = min(requested_max_output_tokens or _survival_max_output_tokens(), _survival_max_output_tokens())
    response_metadata = {
        **metadata,
        "principal_id": context.principal_id,
        "survival_lane": True,
        "survival_background": True,
        "survival_route_order": str(os.environ.get("EA_SURVIVAL_ROUTE_ORDER") or "gemini_vortex,gemini_web,chatplayground"),
    }
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
        instructions=request.instructions.strip() if isinstance(request.instructions, str) else None,
        input_items=parsed_input.input_items,
        store=True,
        previous_response_id=previous_response_id,
        parallel_tool_calls=False,
        tool_choice="none",
        tools=[],
        reasoning=request.reasoning,
    )
    _store_response(
        response_id=response_id,
        response_obj=in_progress_obj,
        input_items=parsed_input.input_items,
        history_items=history_items,
        principal_id=context.principal_id,
        container=container,
    )

    def _worker() -> None:
        service = SurvivalLaneService(
            tool_execution=getattr(container, "tool_execution", None),
            tool_runtime=getattr(container, "tool_runtime", None),
            principal_id=context.principal_id,
        )
        try:
            result = service.execute(
                instructions=request.instructions.strip() if isinstance(request.instructions, str) else None,
                history_items=history_items,
                current_input=parsed_input.prompt,
                desired_format="plain_text",
                prompt_cache_key=request.prompt_cache_key,
                previous_response_id=previous_response_id,
            )
            upstream_result = result.to_upstream_result()
            message_item = _message_item(
                item_id="msg_" + uuid.uuid4().hex[:24],
                text=result.text,
                status="completed",
            )
            completed_metadata = {
                **response_metadata,
                "survival_provider": result.provider_key,
                "survival_backend": result.provider_backend,
                "survival_cache_hit": result.cache_hit,
                "survival_attempts": [
                    {
                        "backend": item.backend,
                        "started_at": item.started_at,
                        "completed_at": item.completed_at,
                        "status": item.status,
                        "detail": item.detail,
                    }
                    for item in result.attempts
                ],
                "upstream_provider": upstream_result.provider_key,
                "upstream_model": upstream_result.model,
                "provider_backend": upstream_result.provider_backend,
            }
            completed_obj = _response_object(
                response_id=response_id,
                model=model,
                created_at=created_at,
                status="completed",
                output=[message_item],
                output_text=result.text,
                tokens_in=0,
                tokens_out=0,
                max_output_tokens=max_output_tokens,
                metadata=completed_metadata,
                instructions=request.instructions.strip() if isinstance(request.instructions, str) else None,
                input_items=parsed_input.input_items,
                store=True,
                previous_response_id=previous_response_id,
                parallel_tool_calls=False,
                tool_choice="none",
                tools=[],
                reasoning=request.reasoning,
            )
            _store_response(
                response_id=response_id,
                response_obj=completed_obj,
                input_items=parsed_input.input_items,
                history_items=[*history_items, message_item],
                principal_id=context.principal_id,
                container=container,
            )
        except Exception as exc:
            failed_obj = _response_object(
                response_id=response_id,
                model=model,
                created_at=created_at,
                status="failed",
                output=[],
                output_text="",
                tokens_in=0,
                tokens_out=0,
                max_output_tokens=max_output_tokens,
                metadata=response_metadata,
                instructions=request.instructions.strip() if isinstance(request.instructions, str) else None,
                input_items=parsed_input.input_items,
                store=True,
                previous_response_id=previous_response_id,
                parallel_tool_calls=False,
                tool_choice="none",
                tools=[],
                reasoning=request.reasoning,
                error={"code": "survival_failed", "message": str(exc)[:500]},
                incomplete_details={"type": "error", "reason": str(exc)[:500]},
            )
            _store_response(
                response_id=response_id,
                response_obj=failed_obj,
                input_items=parsed_input.input_items,
                history_items=history_items,
                principal_id=context.principal_id,
                container=container,
            )

    threading.Thread(target=_worker, daemon=True).start()
    return JSONResponse(in_progress_obj, status_code=202)


def _run_response(
    request_payload: dict[str, object],
    *,
    context: RequestContext,
    container: object | None = None,
    codex_profile: str | None = None,
) -> Response:
    _capture_responses_debug(
        name="request",
        payload={
            "principal_id": context.principal_id,
            "codex_profile": codex_profile,
            "payload": request_payload,
        },
    )
    request, parsed_input = _parse_create_request(request_payload)
    model = _requested_model(request) or DEFAULT_PUBLIC_MODEL
    profile_config: dict[str, object] | None = None
    if codex_profile:
        profile_config = _codex_profile(codex_profile, container=container, principal_id=context.principal_id)
        codex_model = profile_config.get("model")
        if isinstance(codex_model, str) and codex_model:
            model = codex_model
    else:
        router = _brain_router(container)
        if router is not None and get_brain_profile(model) is not None:
            resolved = router.resolve_profile(model, principal_id=context.principal_id)
            if resolved.public_model:
                model = resolved.public_model

    requested_model = _requested_model(request)
    is_survival_profile = codex_profile == "survival"
    is_survival_model = requested_model == SURVIVAL_PUBLIC_MODEL or model == SURVIVAL_PUBLIC_MODEL

    is_audit_profile = codex_profile == "audit"
    is_audit_model = requested_model in {"ea-audit", "ea-audit-jury"}
    is_review_light_profile = codex_profile == "review_light"
    is_review_light_model = requested_model == REVIEW_LIGHT_PUBLIC_MODEL or model == REVIEW_LIGHT_PUBLIC_MODEL
    audit_profile_or_model = is_audit_profile or is_audit_model
    chatplayground_profile_or_model = audit_profile_or_model or is_review_light_profile or is_review_light_model
    chatplayground_audit_callback = None
    if chatplayground_profile_or_model:
        browseract_binding_id = _browseract_binding_id(container=container, principal_id=context.principal_id)

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
                payload_json={
                    **dict(kwargs),
                    "binding_id": str(kwargs.get("binding_id") or browseract_binding_id or "").strip(),
                },
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
    previous_response_id = _requested_previous_response_id(request)
    raw_tools = _response_tools(request)
    supported_tools = _tool_shim_supported_tools(raw_tools)
    history_items = _history_items_for_request(
        previous_response_id=previous_response_id,
        parsed_input=parsed_input,
        principal_id=context.principal_id,
        container=container,
    )

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
    if supported_tools:
        response_metadata["tool_shim"] = True
        response_metadata["tool_shim_tools"] = [tool["name"] for tool in supported_tools]
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

    if is_survival_profile or is_survival_model:
        return _run_survival_response(
            request,
            parsed_input=parsed_input,
            context=context,
            container=container,
            codex_profile=codex_profile,
            profile_config=profile_config,
            model=SURVIVAL_PUBLIC_MODEL,
            metadata=response_metadata,
            history_items=history_items,
            previous_response_id=previous_response_id,
        )

    if not stream:
        tool_decision: _ToolShimDecision | None = None
        if supported_tools:
            tool_decision = _tool_shim_decision(
                model=model,
                max_output_tokens=max_output_tokens,
                instructions=instructions,
                tools=supported_tools,
                history_items=history_items,
                chatplayground_audit_callback=chatplayground_audit_callback,
                chatplayground_audit_callback_only=audit_profile_or_model,
                chatplayground_audit_principal_id=context.principal_id,
            )
            result = tool_decision.upstream_result
        else:
            result = _generate_upstream_text(
                prompt=parsed_input.prompt,
                messages=messages,
                requested_model=model,
                max_output_tokens=max_output_tokens,
                chatplayground_audit_callback=chatplayground_audit_callback,
                chatplayground_audit_callback_only=audit_profile_or_model,
                chatplayground_audit_principal_id=context.principal_id,
            )
        if not isinstance(result, UpstreamResult):
            raise HTTPException(status_code=502, detail="upstream_unavailable:invalid_upstream_result")
        final_metadata = {
            **response_metadata,
            "upstream_provider": result.provider_key,
            "upstream_model": result.model,
            "provider_backend": result.provider_backend,
            "provider_account_name": result.provider_account_name,
            "provider_key_slot": result.provider_key_slot,
        }
        output_items: list[dict[str, object]]
        output_text = ""
        history_items_to_store = list(history_items)
        if tool_decision and tool_decision.kind == "function_call":
            call_id = "call_" + uuid.uuid4().hex[:24]
            arguments_json = _json_compact(tool_decision.arguments or {})
            function_item = _function_call_item(
                item_id="fc_" + uuid.uuid4().hex[:24],
                call_id=call_id,
                name=tool_decision.tool_name,
                arguments=arguments_json,
                status="completed",
            )
            output_items = [function_item]
            history_items_to_store.append(function_item)
        else:
            output_text = tool_decision.text if tool_decision else result.text
            message = _message_item(item_id=item_id, text=output_text, status="completed")
            output_items = [message]
            history_items_to_store.append(message)
        response_obj = _response_object(
            response_id=response_id,
            model=model,
            created_at=created_at,
            status="completed",
            output=output_items,
            output_text=output_text,
            tokens_in=result.tokens_in,
            tokens_out=result.tokens_out,
            max_output_tokens=max_output_tokens,
            metadata=final_metadata,
            instructions=instructions,
            input_items=parsed_input.input_items,
            store=_should_store_response(request),
            previous_response_id=previous_response_id,
            parallel_tool_calls=request.parallel_tool_calls,
            tool_choice=request.tool_choice,
            tools=request.tools if request.tools is not None else None,
            reasoning=request.reasoning,
        )
        if _should_store_response(request):
            _store_response(
                response_id=response_id,
                response_obj=response_obj,
                input_items=parsed_input.input_items,
                history_items=history_items_to_store,
                principal_id=context.principal_id,
                container=container,
            )
        _capture_responses_debug(
            name="response",
            payload={
                "principal_id": context.principal_id,
                "codex_profile": codex_profile,
                "response": response_obj,
            },
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
            store=_should_store_response(request),
            previous_response_id=previous_response_id,
            parallel_tool_calls=request.parallel_tool_calls,
            tool_choice=request.tool_choice,
            tools=request.tools if request.tools is not None else None,
            reasoning=request.reasoning,
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

        result_queue: queue.Queue[tuple[str, object]] = queue.Queue(maxsize=1)

        def _run_upstream() -> None:
            try:
                if supported_tools:
                    decision = _tool_shim_decision(
                        model=model,
                        max_output_tokens=max_output_tokens,
                        instructions=instructions,
                        tools=supported_tools,
                        history_items=history_items,
                        chatplayground_audit_callback=chatplayground_audit_callback,
                        chatplayground_audit_callback_only=audit_profile_or_model,
                        chatplayground_audit_principal_id=context.principal_id,
                    )
                    result_queue.put(("decision", decision))
                    return
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
                yield _sse_heartbeat(sequence=_next_sequence(), response=in_progress_obj)

        status, result_payload = state
        if status == "error":
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
                    history_items=history_items,
                    principal_id=context.principal_id,
                    container=container,
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

        tool_decision: _ToolShimDecision | None = None
        if status == "decision":
            if not isinstance(result_payload, _ToolShimDecision) or not isinstance(result_payload.upstream_result, UpstreamResult):
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
                        history_items=history_items,
                        principal_id=context.principal_id,
                        container=container,
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
            tool_decision = result_payload
            result = result_payload.upstream_result
        elif not isinstance(result_payload, UpstreamResult):
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
                    history_items=history_items,
                    principal_id=context.principal_id,
                    container=container,
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

        else:
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
        history_items_to_store = list(history_items)
        if tool_decision and tool_decision.kind == "function_call":
            call_id = "call_" + uuid.uuid4().hex[:24]
            function_item_id = "fc_" + uuid.uuid4().hex[:24]
            arguments_json = _json_compact(tool_decision.arguments or {})
            in_progress_item = _function_call_item(
                item_id=function_item_id,
                call_id=call_id,
                name=tool_decision.tool_name,
                arguments="",
                status="in_progress",
            )
            yield _sse_event(
                event="response.output_item.added",
                sequence=_next_sequence(),
                data={
                    "type": "response.output_item.added",
                    "output_index": 0,
                    "item": in_progress_item,
                },
            )
            yield _sse_event(
                event="response.function_call_arguments.delta",
                sequence=_next_sequence(),
                data={
                    "type": "response.function_call_arguments.delta",
                    "output_index": 0,
                    "item_id": function_item_id,
                    "delta": arguments_json,
                },
            )
            yield _sse_event(
                event="response.function_call_arguments.done",
                sequence=_next_sequence(),
                data={
                    "type": "response.function_call_arguments.done",
                    "output_index": 0,
                    "item_id": function_item_id,
                    "arguments": arguments_json,
                },
            )
            final_item = _function_call_item(
                item_id=function_item_id,
                call_id=call_id,
                name=tool_decision.tool_name,
                arguments=arguments_json,
                status="completed",
            )
            yield _sse_event(
                event="response.output_item.done",
                sequence=_next_sequence(),
                data={
                    "type": "response.output_item.done",
                    "output_index": 0,
                    "item": final_item,
                },
            )
            history_items_to_store.append(final_item)
            completed_obj = _response_object(
                response_id=response_id,
                model=model,
                created_at=created_at,
                status="completed",
                output=[final_item],
                output_text="",
                tokens_in=result.tokens_in,
                tokens_out=result.tokens_out,
                max_output_tokens=max_output_tokens,
                metadata=stream_metadata,
                instructions=instructions,
                input_items=parsed_input.input_items,
                store=_should_store_response(request),
                previous_response_id=previous_response_id,
                parallel_tool_calls=request.parallel_tool_calls,
                tool_choice=request.tool_choice,
                tools=request.tools if request.tools is not None else None,
                reasoning=request.reasoning,
            )
        else:
            text = tool_decision.text if tool_decision else result.text
            empty_item = _message_item(item_id=item_id, text="", status="in_progress")
            yield _sse_event(
                event="response.output_item.added",
                sequence=_next_sequence(),
                data={
                    "type": "response.output_item.added",
                    "output_index": 0,
                    "item": empty_item,
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
                    "item": final_item,
                },
            )
            history_items_to_store.append(final_item)
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
                store=_should_store_response(request),
                previous_response_id=previous_response_id,
                parallel_tool_calls=request.parallel_tool_calls,
                tool_choice=request.tool_choice,
                tools=request.tools if request.tools is not None else None,
                reasoning=request.reasoning,
            )
        if _should_store_response(request):
            _store_response(
                response_id=response_id,
                response_obj=completed_obj,
                input_items=parsed_input.input_items,
                history_items=history_items_to_store,
                principal_id=context.principal_id,
                container=container,
            )
        _capture_responses_debug(
            name="response",
            payload={
                "principal_id": context.principal_id,
                "codex_profile": codex_profile,
                "response": completed_obj,
            },
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

    return StreamingResponse(
        _iter_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
        },
    )


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
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> Response:
    provider_health = _provider_health_report()
    return JSONResponse(
        {
            **provider_health,
            "principal": principal_identity_summary(context.principal_id),
            "provider_registry": _provider_registry_payload(
                container=container,
                principal_id=context.principal_id,
                provider_health=provider_health,
            ),
        }
    )


@responses_item_router.get("/{response_id}", response_model=_ResponseObject)
def get_response(
    response_id: str,
    *,
    context: RequestContext = Depends(get_request_context),
    container: object = Depends(get_container),
) -> Response:
    stored = _load_response(
        response_id=response_id,
        principal_id=context.principal_id,
        container=container,
    )
    return JSONResponse(stored.response)


@responses_item_router.get("/{response_id}/input_items", response_model=_ResponseInputItemsListObject)
def get_response_input_items(
    response_id: str,
    *,
    context: RequestContext = Depends(get_request_context),
    container: object = Depends(get_container),
) -> Response:
    stored = _load_response(
        response_id=response_id,
        principal_id=context.principal_id,
        container=container,
    )
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
    container: object = Depends(get_container),
) -> Response:
    return _run_response(payload, context=context, container=container)


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
    container: object = Depends(get_container),
) -> Response:
    normalized = _normalize_payload_for_profile(payload, profile="core")
    return _run_response(normalized, context=context, container=container, codex_profile="core")


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
    container: object = Depends(get_container),
) -> Response:
    normalized = _normalize_payload_for_profile(payload, profile="easy")
    return _run_response(normalized, context=context, container=container, codex_profile="easy")


@codex_router.post(
    "/repair",
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
def create_codex_repair(
    payload: dict[str, object],
    *,
    context: RequestContext = Depends(get_request_context),
    container: object = Depends(get_container),
) -> Response:
    normalized = _normalize_payload_for_profile(payload, profile="repair")
    return _run_response(normalized, context=context, container=container, codex_profile="repair")


@codex_router.post(
    "/groundwork",
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
def create_codex_groundwork(
    payload: dict[str, object],
    *,
    context: RequestContext = Depends(get_request_context),
    container: object = Depends(get_container),
) -> Response:
    normalized = _normalize_payload_for_profile(payload, profile="groundwork")
    return _run_response(normalized, context=context, container=container, codex_profile="groundwork")


@codex_router.post(
    "/review-light",
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
def create_codex_review_light(
    payload: dict[str, object],
    *,
    context: RequestContext = Depends(get_request_context),
    container: object = Depends(get_container),
) -> Response:
    normalized = _normalize_payload_for_profile(payload, profile="review_light")
    return _run_response(normalized, context=context, container=container, codex_profile="review_light")


@codex_router.post(
    "/survival",
    response_model=_ResponseObject,
    responses={
        202: {
            "description": "Returns an in-progress response object for background survival execution.",
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
def create_codex_survival(
    payload: dict[str, object],
    *,
    context: RequestContext = Depends(get_request_context),
    container: object = Depends(get_container),
) -> Response:
    normalized = _normalize_payload_for_profile(payload, profile="survival")
    return _run_response(normalized, context=context, container=container, codex_profile="survival")


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
def list_codex_profiles(
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> Response:
    provider_health = _provider_health_report()
    profiles = [
        {**profile, "provider_hint_order": list(profile["provider_hint_order"])}
        for profile in _codex_profiles(container=container, principal_id=context.principal_id)
    ]
    return JSONResponse(
        {
            "principal": principal_identity_summary(context.principal_id),
            "profiles": _attach_provider_slot_state(profiles, provider_health=provider_health),
            "provider_health": provider_health,
            "provider_registry": _provider_registry_payload(
                container=container,
                principal_id=context.principal_id,
                provider_health=provider_health,
            ),
        }
    )


@codex_router.get("/status")
def get_codex_status(
    window: str = "1h",
    refresh: bool = False,
) -> Response:
    _ = refresh
    return JSONResponse(codex_status_report(window=window))


router.include_router(models_router)
router.include_router(responses_item_router)
router.include_router(codex_router)
