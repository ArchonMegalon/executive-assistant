from __future__ import annotations

from typing import Any, Callable


def tool_shim_truncate_text(text: str, *, limit: int) -> str:
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


def tool_shim_tool_parameters_summary(parameters: object) -> dict[str, object]:
    if not isinstance(parameters, dict):
        return {}
    summary: dict[str, object] = {}
    parameter_type = str(parameters.get("type") or "").strip()
    if parameter_type:
        summary["type"] = parameter_type
    properties = parameters.get("properties")
    if isinstance(properties, dict):
        parameter_keys = [str(key or "").strip() for key in properties.keys() if str(key or "").strip()]
        if parameter_keys:
            summary["parameter_keys"] = parameter_keys[:24]
    required = parameters.get("required")
    if isinstance(required, list):
        required_keys = [str(key or "").strip() for key in required if str(key or "").strip()]
        if required_keys:
            summary["required"] = required_keys[:24]
    return summary


def build_history_item_to_transcript(
    *,
    normalize_message_role: Callable[[Any], str],
    extract_textish: Callable[[Any], str],
    tool_shim_truncate_text: Callable[..., str],
    transcript_part_max_chars: Callable[[], int],
) -> Callable[..., str]:
    def history_item_to_transcript(
        item: dict[str, object],
        *,
        include_system: bool = True,
        compact: bool = False,
    ) -> str:
        item_type = str(item.get("type") or "").strip().lower()
        if item_type == "message":
            role = normalize_message_role(item.get("role"))
            if role == "system" and not include_system:
                return ""
            content = item.get("content")
            text = ""
            if isinstance(content, list):
                text = "\n\n".join(
                    extract_textish(part.get("text"))
                    for part in content
                    if isinstance(part, dict) and extract_textish(part.get("text"))
                ).strip()
            else:
                text = extract_textish(content)
            if not text:
                return ""
            if compact:
                text = tool_shim_truncate_text(text, limit=transcript_part_max_chars())
            return f"{role.capitalize()}:\n{text}"
        if item_type == "input_text":
            text = extract_textish(item.get("text"))
            if compact:
                text = tool_shim_truncate_text(text, limit=transcript_part_max_chars())
            return f"User:\n{text}" if text else ""
        if item_type == "function_call":
            name = str(item.get("name") or "").strip()
            call_id = str(item.get("call_id") or "").strip()
            arguments = str(item.get("arguments") or "").strip()
            if not name:
                return ""
            if compact:
                arguments = tool_shim_truncate_text(arguments, limit=transcript_part_max_chars())
            return (
                f"Assistant tool call ({call_id or 'no-call-id'})\n"
                f"Tool: {name}\n"
                f"Arguments: {arguments}"
            ).strip()
        if item_type == "function_call_output":
            call_id = str(item.get("call_id") or "").strip()
            output_text = extract_textish(item.get("output"))
            if compact:
                output_text = tool_shim_truncate_text(output_text, limit=transcript_part_max_chars())
            return f"Tool output ({call_id or 'no-call-id'}):\n{output_text}".strip()
        return ""

    history_item_to_transcript.__name__ = "history_item_to_transcript"
    history_item_to_transcript.__qualname__ = "history_item_to_transcript"
    return history_item_to_transcript


def build_tool_shim_latest_user_text(
    *,
    normalize_message_role: Callable[[Any], str],
    extract_textish: Callable[[Any], str],
) -> Callable[[list[dict[str, object]]], str]:
    def tool_shim_latest_user_text(history_items: list[dict[str, object]]) -> str:
        for item in reversed(history_items):
            item_type = str(item.get("type") or "").strip().lower()
            if item_type == "input_text":
                text = extract_textish(item.get("text"))
                if text:
                    return text
                continue
            if item_type != "message":
                continue
            role = normalize_message_role(item.get("role"))
            if role != "user":
                continue
            content = item.get("content")
            if isinstance(content, list):
                text = "\n\n".join(
                    extract_textish(part.get("text"))
                    for part in content
                    if isinstance(part, dict) and extract_textish(part.get("text"))
                ).strip()
            else:
                text = extract_textish(content)
            if text:
                return text
        return ""

    tool_shim_latest_user_text.__name__ = "tool_shim_latest_user_text"
    tool_shim_latest_user_text.__qualname__ = "tool_shim_latest_user_text"
    return tool_shim_latest_user_text


def build_tool_shim_latest_package_work_prompt(
    *,
    normalize_message_role: Callable[[Any], str],
    extract_textish: Callable[[Any], str],
    is_package_work_prompt: Callable[[str], bool],
    tool_shim_staged_commands: Callable[[str], list[str]],
) -> Callable[[list[dict[str, object]]], str]:
    def tool_shim_latest_package_work_prompt(history_items: list[dict[str, object]]) -> str:
        for item in reversed(history_items):
            item_type = str(item.get("type") or "").strip().lower()
            if item_type == "input_text":
                text = extract_textish(item.get("text"))
                if text and (is_package_work_prompt(text) or tool_shim_staged_commands(text)):
                    return text
                continue
            if item_type != "message":
                continue
            role = normalize_message_role(item.get("role"))
            if role != "user":
                continue
            content = item.get("content")
            if isinstance(content, list):
                text = "\n\n".join(
                    extract_textish(part.get("text"))
                    for part in content
                    if isinstance(part, dict) and extract_textish(part.get("text"))
                ).strip()
            else:
                text = extract_textish(content)
            if text and (is_package_work_prompt(text) or tool_shim_staged_commands(text)):
                return text
        return ""

    tool_shim_latest_package_work_prompt.__name__ = "tool_shim_latest_package_work_prompt"
    tool_shim_latest_package_work_prompt.__qualname__ = "tool_shim_latest_package_work_prompt"
    return tool_shim_latest_package_work_prompt
