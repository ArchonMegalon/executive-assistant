from __future__ import annotations

import time
from typing import Any, Callable


def background_timeout_seconds_for_response(response_obj: dict[str, object]) -> float:
    metadata = dict(response_obj.get("metadata") or {}) if isinstance(response_obj.get("metadata"), dict) else {}
    raw = metadata.get("background_timeout_seconds")
    try:
        return max(float(raw), 0.0)
    except Exception:
        return 0.0


def background_response_deadline_unix(response_obj: dict[str, object]) -> float:
    timeout_seconds = background_timeout_seconds_for_response(response_obj)
    created_at = int(response_obj.get("created_at") or 0)
    if timeout_seconds <= 0 or created_at <= 0:
        return 0.0
    return float(created_at) + timeout_seconds


def background_response_has_expired(response_obj: dict[str, object], *, now_unix: float | None = None) -> bool:
    deadline_unix = background_response_deadline_unix(response_obj)
    if deadline_unix <= 0:
        return False
    current = float(now_unix if now_unix is not None else time.time())
    return current >= deadline_unix


def background_replay_payload(
    *,
    prompt: str,
    messages: list[dict[str, str]],
    supported_tools: list[dict[str, object]],
    effective_codex_profile: str | None,
    chatplayground_audit_callback_enabled: bool,
    chatplayground_audit_callback_only: bool,
    preferred_onemin_labels: tuple[str, ...] = (),
) -> dict[str, object]:
    return {
        "prompt": str(prompt or ""),
        "messages": [dict(item) for item in messages],
        "supported_tools": [dict(item) for item in supported_tools],
        "effective_codex_profile": str(effective_codex_profile or "").strip(),
        "chatplayground_audit_callback_enabled": bool(chatplayground_audit_callback_enabled),
        "chatplayground_audit_callback_only": bool(chatplayground_audit_callback_only),
        "preferred_onemin_labels": [str(item or "").strip() for item in preferred_onemin_labels if str(item or "").strip()],
    }


def background_failed_response(
    *,
    stored: Any,
    failure_message: str,
    build_failed_response: Callable[..., dict[str, object]],
    requested_max_output_tokens_from_response: Callable[[dict[str, object]], int | None],
    now_unix: Callable[[], int],
    default_public_model: str,
) -> dict[str, object]:
    response_obj = dict(stored.response)
    return build_failed_response(
        response_id=str(response_obj.get("id") or ""),
        created_at=int(response_obj.get("created_at") or now_unix()),
        model=str(response_obj.get("model") or default_public_model),
        requested_max_output_tokens=requested_max_output_tokens_from_response(response_obj),
        metadata=dict(response_obj.get("metadata") or {}) if isinstance(response_obj.get("metadata"), dict) else {},
        instructions=response_obj.get("instructions") if isinstance(response_obj.get("instructions"), str) else None,
        input_items=[dict(item) for item in stored.input_items],
        failure_message=failure_message,
        visible_text=f"Error: {failure_message}",
    )


def background_timeout_failure_message(response_obj: dict[str, object]) -> str:
    timeout_seconds = int(round(background_timeout_seconds_for_response(response_obj))) or 0
    return f"background_timeout:{timeout_seconds}s" if timeout_seconds > 0 else "background_timeout"
