from __future__ import annotations

import re
from typing import Any, Callable


def tool_shim_unwrap_tool_output_envelope(output_text: str) -> str:
    stripped = str(output_text or "").strip()
    if not stripped:
        return ""
    output_marker = "\nOutput:\n"
    if output_marker in stripped:
        return stripped.rsplit(output_marker, 1)[1].strip()
    succeeded_match = re.search(r"\nsucceeded in [^\n]*:\n(?P<body>.*)\Z", stripped, flags=re.DOTALL)
    if succeeded_match:
        return str(succeeded_match.group("body") or "").strip()
    return stripped


def build_tool_shim_latest_function_output(
    *,
    extract_textish: Callable[[object], str],
    tool_shim_unwrap_tool_output_envelope: Callable[[str], str],
) -> Callable[[list[dict[str, object]]], str]:
    def tool_shim_latest_function_output(history_items: list[dict[str, object]]) -> str:
        for item in reversed(history_items):
            item_type = str(item.get("type") or "").strip().lower()
            if item_type != "function_call_output":
                continue
            output_text = tool_shim_unwrap_tool_output_envelope(extract_textish(item.get("output")))
            if output_text:
                return output_text
        return ""

    tool_shim_latest_function_output.__name__ = "tool_shim_latest_function_output"
    tool_shim_latest_function_output.__qualname__ = "tool_shim_latest_function_output"
    return tool_shim_latest_function_output


def build_tool_shim_requires_immediate_tool(
    *,
    looks_like_lightweight_ops_query: Callable[[str], tuple[bool, object]],
) -> Callable[..., bool]:
    def tool_shim_requires_immediate_tool(
        *,
        latest_user_text: str,
        available_tools: list[dict[str, object]],
    ) -> bool:
        if not available_tools:
            return False
        prompt = str(latest_user_text or "").strip()
        if not prompt:
            return False
        lightweight_ops, _ = looks_like_lightweight_ops_query(prompt)
        if lightweight_ops:
            return True
        normalized = " ".join(prompt.lower().split())
        if len(normalized) > 220:
            return False
        if not (
            "?" in normalized
            or normalized.startswith(("how many ", "what ", "which ", "is ", "are ", "eta ", "status "))
        ):
            return False
        local_markers = (
            "right now",
            "currently",
            "current ",
            "in the fleet",
            "in this repo",
            "in the repo",
            "in the workspace",
            "local ",
        )
        return any(marker in normalized for marker in local_markers)

    tool_shim_requires_immediate_tool.__name__ = "tool_shim_requires_immediate_tool"
    tool_shim_requires_immediate_tool.__qualname__ = "tool_shim_requires_immediate_tool"
    return tool_shim_requires_immediate_tool


def build_tool_shim_local_upstream_result(
    *,
    upstream_result_cls: Callable[..., Any],
) -> Callable[[str], Any]:
    def tool_shim_local_upstream_result(text: str, *, reason: str) -> Any:
        return upstream_result_cls(
            text=text,
            provider_key="local",
            model="tool_shim_local",
            provider_key_slot=None,
            provider_backend="local",
            provider_account_name="tool_shim_local",
            tokens_in=0,
            tokens_out=0,
            upstream_model="tool_shim_local",
            latency_ms=0,
            fallback_reason=reason,
        )

    tool_shim_local_upstream_result.__name__ = "tool_shim_local_upstream_result"
    tool_shim_local_upstream_result.__qualname__ = "tool_shim_local_upstream_result"
    return tool_shim_local_upstream_result


def tool_shim_scalar_text(value: object) -> str | None:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (str, int, float)):
        return str(value)
    if value is None:
        return None
    if isinstance(value, list) and len(value) == 1:
        return tool_shim_scalar_text(value[0])
    if isinstance(value, dict):
        preferred_keys = ("output", "stdout", "text", "result", "value", "content", "message")
        for key in preferred_keys:
            if key in value:
                scalar = tool_shim_scalar_text(value.get(key))
                if scalar is not None:
                    return scalar
        if len(value) == 1:
            only_value = next(iter(value.values()))
            return tool_shim_scalar_text(only_value)
    return None
