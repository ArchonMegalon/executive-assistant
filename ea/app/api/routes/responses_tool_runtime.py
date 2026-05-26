from __future__ import annotations

import queue
import threading
import time
from typing import Any, Callable


def generate_upstream_text(
    *,
    prompt: str,
    messages: list[dict[str, str]] | None,
    requested_model: str,
    max_output_tokens: int | None,
    chatplayground_audit_callback: Callable[..., Any] | None,
    chatplayground_audit_callback_only: bool,
    chatplayground_audit_principal_id: str,
    preferred_onemin_labels: tuple[str, ...],
    request_deadline_monotonic: float | None,
    upstream_generate_text: Callable[..., Any],
    responses_upstream_error_type: type[Exception],
    http_exception_type: type[Exception],
) -> Any:
    try:
        return upstream_generate_text(
            prompt=prompt,
            messages=messages,
            requested_model=requested_model,
            max_output_tokens=max_output_tokens,
            chatplayground_audit_callback=chatplayground_audit_callback,
            chatplayground_audit_callback_only=chatplayground_audit_callback_only,
            chatplayground_audit_principal_id=chatplayground_audit_principal_id,
            preferred_onemin_labels=preferred_onemin_labels,
            request_deadline_monotonic=request_deadline_monotonic,
        )
    except responses_upstream_error_type as exc:
        raise http_exception_type(status_code=502, detail=f"upstream_unavailable:{exc}") from exc
    except Exception as exc:
        raise http_exception_type(status_code=502, detail=f"upstream_unavailable:{exc}") from exc


def build_tool_shim_generate_upstream_text_with_timeout(
    *,
    generate_upstream_text: Callable[..., Any],
    upstream_result_type: type[Any],
    http_exception_type: type[Exception],
) -> Callable[..., Any]:
    def tool_shim_generate_upstream_text_with_timeout(
        *,
        prompt: str,
        messages: list[dict[str, str]] | None,
        requested_model: str,
        max_output_tokens: int | None,
        chatplayground_audit_callback: Callable[..., Any] | None = None,
        chatplayground_audit_callback_only: bool = False,
        chatplayground_audit_principal_id: str = "",
        preferred_onemin_labels: tuple[str, ...] = (),
        request_deadline_monotonic: float | None = None,
    ) -> Any:
        if request_deadline_monotonic is None:
            return generate_upstream_text(
                prompt=prompt,
                messages=messages,
                requested_model=requested_model,
                max_output_tokens=max_output_tokens,
                chatplayground_audit_callback=chatplayground_audit_callback,
                chatplayground_audit_callback_only=chatplayground_audit_callback_only,
                chatplayground_audit_principal_id=chatplayground_audit_principal_id,
                preferred_onemin_labels=preferred_onemin_labels,
                request_deadline_monotonic=None,
            )
        timeout_seconds = max(1.0, request_deadline_monotonic - time.monotonic())
        result_queue: queue.Queue[tuple[str, object]] = queue.Queue(maxsize=1)

        def _run() -> None:
            try:
                result_queue.put(
                    (
                        "result",
                        generate_upstream_text(
                            prompt=prompt,
                            messages=messages,
                            requested_model=requested_model,
                            max_output_tokens=max_output_tokens,
                            chatplayground_audit_callback=chatplayground_audit_callback,
                            chatplayground_audit_callback_only=chatplayground_audit_callback_only,
                            chatplayground_audit_principal_id=chatplayground_audit_principal_id,
                            preferred_onemin_labels=preferred_onemin_labels,
                            request_deadline_monotonic=request_deadline_monotonic,
                        ),
                    )
                )
            except Exception as exc:
                result_queue.put(("error", exc))

        worker = threading.Thread(target=_run, daemon=True)
        worker.start()
        try:
            status, payload = result_queue.get(timeout=timeout_seconds)
        except queue.Empty as exc:
            raise http_exception_type(
                status_code=502,
                detail=f"upstream_unavailable:tool_shim_planner_timeout:{max(1, int(timeout_seconds))}s",
            ) from exc
        if status == "error":
            failure = payload if isinstance(payload, Exception) else RuntimeError(str(payload))
            raise failure
        if isinstance(payload, upstream_result_type):
            return payload
        raise http_exception_type(status_code=502, detail="upstream_unavailable:invalid_tool_shim_planner_result")

    tool_shim_generate_upstream_text_with_timeout.__name__ = "tool_shim_generate_upstream_text_with_timeout"
    tool_shim_generate_upstream_text_with_timeout.__qualname__ = "tool_shim_generate_upstream_text_with_timeout"
    return tool_shim_generate_upstream_text_with_timeout


def response_tools(payload: Any) -> list[dict[str, object]]:
    raw_tools = getattr(payload, "tools", None)
    if not isinstance(raw_tools, list):
        return []
    tools: list[dict[str, object]] = []
    for entry in raw_tools:
        if isinstance(entry, dict):
            tools.append(dict(entry))
    return tools


def tool_choice_disables_tools(payload: Any) -> bool:
    raw_tool_choice = getattr(payload, "tool_choice", None)
    if raw_tool_choice is None:
        return False
    if isinstance(raw_tool_choice, str):
        return raw_tool_choice.strip().lower() == "none"
    if isinstance(raw_tool_choice, dict):
        tool_choice_type = str(raw_tool_choice.get("type") or "").strip().lower()
        return tool_choice_type == "none"
    return False


def build_tool_shim_supported_tools(
    *,
    looks_like_lightweight_ops_query: Callable[[str], tuple[bool, Any]],
) -> Callable[..., list[dict[str, object]]]:
    def tool_shim_supported_tools(
        raw_tools: list[dict[str, object]],
        *,
        prompt: str | None = None,
    ) -> list[dict[str, object]]:
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
        lightweight_ops, _ = looks_like_lightweight_ops_query(prompt or "")
        if lightweight_ops:
            preferred_names = (
                "exec_command",
                "write_stdin",
                "read_mcp_resource",
                "list_mcp_resources",
            )
            narrowed = [tool for name in preferred_names for tool in supported if tool["name"] == name]
            if narrowed:
                return narrowed
        return supported

    tool_shim_supported_tools.__name__ = "tool_shim_supported_tools"
    tool_shim_supported_tools.__qualname__ = "tool_shim_supported_tools"
    return tool_shim_supported_tools
