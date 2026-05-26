from __future__ import annotations

import json
import os
from typing import Callable


def tool_shim_resolve_equivalent_shard_runtime_path(path_text: str) -> str:
    normalized = str(path_text or "").strip()
    if not normalized:
        return normalized
    candidates = [normalized]
    replacements = (
        (
            "/docker/fleet/state/chummer_design_supervisor/",
            "/var/lib/codex-fleet/chummer_design_supervisor/",
        ),
        (
            "/var/lib/codex-fleet/chummer_design_supervisor/",
            "/docker/fleet/state/chummer_design_supervisor/",
        ),
    )
    for source_prefix, target_prefix in replacements:
        if normalized.startswith(source_prefix):
            candidates.append(normalized.replace(source_prefix, target_prefix, 1))
    for candidate in candidates:
        if os.path.exists(candidate):
            return candidate
    return normalized


def tool_shim_normalize_equivalent_command_paths(command: str) -> str:
    normalized = str(command or "")
    replacements = (
        (
            "/docker/fleet/state/chummer_design_supervisor/",
            "/__fleet_shard_runtime__/chummer_design_supervisor/",
        ),
        (
            "/var/lib/codex-fleet/chummer_design_supervisor/",
            "/__fleet_shard_runtime__/chummer_design_supervisor/",
        ),
    )
    for source_prefix, target_prefix in replacements:
        normalized = normalized.replace(source_prefix, target_prefix)
    return normalized


def tool_shim_exec_command_history(history_items: list[dict[str, object]]) -> list[str]:
    executed_commands: list[str] = []
    for item in history_items:
        if not isinstance(item, dict):
            continue
        if str(item.get("type") or "").strip().lower() != "function_call":
            continue
        if str(item.get("name") or "").strip() != "exec_command":
            continue
        arguments = item.get("arguments")
        parsed_arguments = arguments
        if isinstance(arguments, str):
            try:
                parsed_arguments = json.loads(arguments)
            except Exception:
                parsed_arguments = None
        if not isinstance(parsed_arguments, dict):
            continue
        command = str(parsed_arguments.get("cmd") or "").strip()
        if command:
            executed_commands.append(command)
    return executed_commands


def build_tool_shim_exec_command_identity_history(
    *,
    tool_shim_exec_command_history: Callable[[list[dict[str, object]]], list[str]],
    tool_shim_command_identity: Callable[[str], str],
) -> Callable[[list[dict[str, object]]], list[str]]:
    def tool_shim_exec_command_identity_history(history_items: list[dict[str, object]]) -> list[str]:
        identities: list[str] = []
        for command in tool_shim_exec_command_history(history_items):
            raw_command = str(command or "").strip()
            if not raw_command:
                continue
            parts = [raw_command]
            if " ; " in raw_command:
                parts.extend(part.strip() for part in raw_command.split(" ; ") if part.strip())
            for part in parts:
                identity = tool_shim_command_identity(part)
                if identity:
                    identities.append(identity)
        return identities

    tool_shim_exec_command_identity_history.__name__ = "tool_shim_exec_command_identity_history"
    tool_shim_exec_command_identity_history.__qualname__ = "tool_shim_exec_command_identity_history"
    return tool_shim_exec_command_identity_history


def build_tool_shim_command_identity_sequence(
    *,
    tool_shim_command_identity: Callable[[str], str],
) -> Callable[[str], list[str]]:
    def tool_shim_command_identity_sequence(command: str) -> list[str]:
        raw_command = str(command or "").strip()
        if not raw_command:
            return []
        parts = [raw_command]
        if " ; " in raw_command:
            split_parts = [part.strip() for part in raw_command.split(" ; ") if part.strip()]
            if len(split_parts) > 1:
                parts = split_parts
        identities: list[str] = []
        for part in parts:
            identity = tool_shim_command_identity(part)
            if identity:
                identities.append(identity)
        return identities

    tool_shim_command_identity_sequence.__name__ = "tool_shim_command_identity_sequence"
    tool_shim_command_identity_sequence.__qualname__ = "tool_shim_command_identity_sequence"
    return tool_shim_command_identity_sequence


def build_tool_shim_exec_command_expanded_sequence(
    *,
    tool_shim_exec_command_history: Callable[[list[dict[str, object]]], list[str]],
    tool_shim_command_identity_sequence: Callable[[str], list[str]],
) -> Callable[[list[dict[str, object]]], list[str]]:
    def tool_shim_exec_command_expanded_sequence(history_items: list[dict[str, object]]) -> list[str]:
        sequence: list[str] = []
        for command in tool_shim_exec_command_history(history_items):
            sequence.extend(tool_shim_command_identity_sequence(command))
        return sequence

    tool_shim_exec_command_expanded_sequence.__name__ = "tool_shim_exec_command_expanded_sequence"
    tool_shim_exec_command_expanded_sequence.__qualname__ = "tool_shim_exec_command_expanded_sequence"
    return tool_shim_exec_command_expanded_sequence


def build_tool_shim_command_sequence_executed(
    *,
    tool_shim_command_identity_sequence: Callable[[str], list[str]],
    tool_shim_exec_command_identity_history: Callable[[list[dict[str, object]]], list[str]],
) -> Callable[[list[dict[str, object]], str], bool]:
    def tool_shim_command_sequence_executed(
        history_items: list[dict[str, object]],
        command: str,
    ) -> bool:
        expected_identities = tool_shim_command_identity_sequence(command)
        if not expected_identities:
            return False
        executed_identities = set(tool_shim_exec_command_identity_history(history_items))
        return all(identity in executed_identities for identity in expected_identities)

    tool_shim_command_sequence_executed.__name__ = "tool_shim_command_sequence_executed"
    tool_shim_command_sequence_executed.__qualname__ = "tool_shim_command_sequence_executed"
    return tool_shim_command_sequence_executed


def build_tool_shim_exec_command_output_history(
    *,
    extract_textish: Callable[[object], str],
    tool_shim_unwrap_tool_output_envelope: Callable[[str], str],
) -> Callable[[list[dict[str, object]]], list[dict[str, str]]]:
    def tool_shim_exec_command_output_history(history_items: list[dict[str, object]]) -> list[dict[str, str]]:
        call_commands: dict[str, str] = {}
        output_history: list[dict[str, str]] = []
        for item in history_items:
            if not isinstance(item, dict):
                continue
            item_type = str(item.get("type") or "").strip().lower()
            if item_type == "function_call":
                if str(item.get("name") or "").strip() != "exec_command":
                    continue
                call_id = str(item.get("call_id") or "").strip()
                if not call_id:
                    continue
                arguments = item.get("arguments")
                parsed_arguments = arguments
                if isinstance(arguments, str):
                    try:
                        parsed_arguments = json.loads(arguments)
                    except Exception:
                        parsed_arguments = None
                if not isinstance(parsed_arguments, dict):
                    continue
                command = str(parsed_arguments.get("cmd") or "").strip()
                if command:
                    call_commands[call_id] = command
                continue
            if item_type != "function_call_output":
                continue
            call_id = str(item.get("call_id") or "").strip()
            output_text = tool_shim_unwrap_tool_output_envelope(extract_textish(item.get("output")))
            if not output_text:
                continue
            output_history.append(
                {
                    "call_id": call_id,
                    "cmd": str(call_commands.get(call_id) or "").strip(),
                    "output": output_text,
                }
            )
        return output_history

    tool_shim_exec_command_output_history.__name__ = "tool_shim_exec_command_output_history"
    tool_shim_exec_command_output_history.__qualname__ = "tool_shim_exec_command_output_history"
    return tool_shim_exec_command_output_history


def build_tool_shim_latest_exec_json_output(
    *,
    tool_shim_exec_command_output_history: Callable[[list[dict[str, object]]], list[dict[str, str]]],
    extract_json_object: Callable[[str], object],
) -> Callable[[list[dict[str, object]]], dict[str, object] | None]:
    def tool_shim_latest_exec_json_output(history_items: list[dict[str, object]]) -> dict[str, object] | None:
        for record in reversed(tool_shim_exec_command_output_history(history_items)):
            payload = extract_json_object(str(record.get("output") or "").strip())
            if isinstance(payload, dict):
                return payload
        return None

    tool_shim_latest_exec_json_output.__name__ = "tool_shim_latest_exec_json_output"
    tool_shim_latest_exec_json_output.__qualname__ = "tool_shim_latest_exec_json_output"
    return tool_shim_latest_exec_json_output


def build_tool_shim_latest_exec_json_output_for_command(
    *,
    tool_shim_exec_command_output_history: Callable[[list[dict[str, object]]], list[dict[str, str]]],
    extract_json_object: Callable[[str], object],
) -> Callable[..., dict[str, object] | None]:
    def tool_shim_latest_exec_json_output_for_command(
        history_items: list[dict[str, object]],
        *,
        command_substring: str,
        probe_kind: str | None = None,
    ) -> dict[str, object] | None:
        needle = str(command_substring or "").strip()
        expected_probe = str(probe_kind or "").strip().lower()
        if not needle:
            return None
        for record in reversed(tool_shim_exec_command_output_history(history_items)):
            cmd = str(record.get("cmd") or "").strip()
            if needle not in cmd:
                continue
            payload = extract_json_object(str(record.get("output") or "").strip())
            if not isinstance(payload, dict):
                continue
            if expected_probe and str(payload.get("probe_kind") or "").strip().lower() != expected_probe:
                continue
            return payload
        return None

    tool_shim_latest_exec_json_output_for_command.__name__ = "tool_shim_latest_exec_json_output_for_command"
    tool_shim_latest_exec_json_output_for_command.__qualname__ = "tool_shim_latest_exec_json_output_for_command"
    return tool_shim_latest_exec_json_output_for_command
