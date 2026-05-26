from __future__ import annotations

import re
import shlex
from typing import Callable


def tool_shim_is_git_command(command: str, verb: str | None = None) -> bool:
    normalized = " ".join(str(command or "").strip().lower().split())
    if not normalized.startswith("git "):
        return False
    if verb is None:
        return True
    return normalized.startswith(f"git {verb} ") or normalized == f"git {verb}"


def build_tool_shim_is_staged_git_commit_push_workflow(
    *,
    tool_shim_is_git_command: Callable[[str, str | None], bool],
) -> Callable[[list[str]], bool]:
    def tool_shim_is_staged_git_commit_push_workflow(commands: list[str]) -> bool:
        if not commands:
            return False
        if not all(tool_shim_is_git_command(command, None) for command in commands):
            return False
        has_add = any(tool_shim_is_git_command(command, "add") for command in commands)
        has_commit = any(tool_shim_is_git_command(command, "commit") for command in commands)
        has_push = any(tool_shim_is_git_command(command, "push") for command in commands)
        return has_add and has_commit and has_push

    tool_shim_is_staged_git_commit_push_workflow.__name__ = "tool_shim_is_staged_git_commit_push_workflow"
    tool_shim_is_staged_git_commit_push_workflow.__qualname__ = "tool_shim_is_staged_git_commit_push_workflow"
    return tool_shim_is_staged_git_commit_push_workflow


def build_tool_shim_build_staged_git_commit_push_command(
    *,
    tool_shim_is_staged_git_commit_push_workflow: Callable[[list[str]], bool],
    tool_shim_is_git_command: Callable[[str, str | None], bool],
) -> Callable[[list[str]], str | None]:
    def tool_shim_build_staged_git_commit_push_command(commands: list[str]) -> str | None:
        if not tool_shim_is_staged_git_commit_push_workflow(commands):
            return None
        pre_commands: list[str] = []
        add_command = ""
        commit_command = ""
        push_command = ""
        post_commands: list[str] = []
        seen_commit = False
        seen_push = False
        for command in commands:
            if tool_shim_is_git_command(command, "add") and not add_command:
                add_command = command
                continue
            if tool_shim_is_git_command(command, "commit") and not commit_command:
                commit_command = command
                seen_commit = True
                continue
            if tool_shim_is_git_command(command, "push") and not push_command:
                push_command = command
                seen_push = True
                continue
            if seen_push:
                post_commands.append(command)
            elif seen_commit:
                post_commands.append(command)
            else:
                pre_commands.append(command)
        if not add_command or not commit_command or not push_command:
            return None
        script_parts = ["set -euo pipefail"]
        script_parts.extend(pre_commands)
        script_parts.append(add_command)
        script_parts.append(
            f"if git diff --cached --quiet; then echo '[codexea] nothing new to commit'; else {commit_command}; fi"
        )
        script_parts.append(push_command)
        script_parts.extend(post_commands)
        script_parts.append("git rev-parse HEAD")
        return f"bash -lc {shlex.quote('; '.join(script_parts))}"

    tool_shim_build_staged_git_commit_push_command.__name__ = "tool_shim_build_staged_git_commit_push_command"
    tool_shim_build_staged_git_commit_push_command.__qualname__ = "tool_shim_build_staged_git_commit_push_command"
    return tool_shim_build_staged_git_commit_push_command


def tool_shim_extract_git_head_hash(output_text: str) -> str:
    lines = [line.strip() for line in str(output_text or "").splitlines() if line.strip()]
    for line in reversed(lines):
        if re.fullmatch(r"[0-9a-f]{40}", line):
            return line
    return ""


def build_tool_shim_direct_staged_git_commit_push_final_text(
    *,
    tool_shim_staged_commands: Callable[[str], list[str]],
    tool_shim_build_staged_git_commit_push_command: Callable[[list[str]], str | None],
    tool_shim_exec_command_history: Callable[[list[dict[str, object]]], list[str]],
    tool_shim_latest_function_output: Callable[[list[dict[str, object]]], str],
    tool_shim_extract_git_head_hash: Callable[[str], str],
) -> Callable[[str, list[dict[str, object]]], str | None]:
    def tool_shim_direct_staged_git_commit_push_final_text(
        latest_user_text: str,
        history_items: list[dict[str, object]],
    ) -> str | None:
        commands = tool_shim_staged_commands(latest_user_text)
        git_workflow_command = tool_shim_build_staged_git_commit_push_command(commands)
        if not git_workflow_command:
            return None
        executed_commands = set(tool_shim_exec_command_history(history_items))
        if git_workflow_command not in executed_commands:
            return None
        head_hash = tool_shim_extract_git_head_hash(tool_shim_latest_function_output(history_items))
        if not head_hash:
            return None
        return f"Pushed commit {head_hash}"

    tool_shim_direct_staged_git_commit_push_final_text.__name__ = "tool_shim_direct_staged_git_commit_push_final_text"
    tool_shim_direct_staged_git_commit_push_final_text.__qualname__ = "tool_shim_direct_staged_git_commit_push_final_text"
    return tool_shim_direct_staged_git_commit_push_final_text
