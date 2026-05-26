from __future__ import annotations

import re
import shlex
from pathlib import Path
from typing import Callable


def tool_shim_has_tool_history(history_items: list[dict[str, object]]) -> bool:
    for item in history_items:
        if not isinstance(item, dict):
            continue
        item_type = str(item.get("type") or "").strip().lower()
        if item_type in {"function_call", "function_call_output"}:
            return True
    return False


def tool_shim_direct_file_read_command(
    path_text: str,
    *,
    prefer_cat: bool = False,
    max_lines: int = 220,
) -> str:
    quoted_path = shlex.quote(path_text)
    if prefer_cat or path_text.lower().endswith(".json"):
        return f"cat {quoted_path}"
    try:
        line_limit = max(1, int(max_lines))
    except Exception:
        line_limit = 220
    return f"sed -n '1,{line_limit}p' {quoted_path}"


def tool_shim_looks_like_shell_command(candidate: str) -> bool:
    stripped = str(candidate or "").strip()
    if not stripped:
        return False
    command_word = stripped.split(None, 1)[0]
    normalized = command_word.strip().lower()
    if not normalized:
        return False
    if normalized.startswith(("/", "./", "../")):
        return True
    return normalized in {
        "sed",
        "rg",
        "cat",
        "python",
        "python3",
        "bash",
        "sh",
        "jq",
        "find",
        "ls",
        "git",
        "docker",
        "pytest",
        "grep",
        "head",
        "tail",
        "wc",
        "perl",
    }


def build_tool_shim_staged_commands(
    *,
    tool_shim_looks_like_shell_command: Callable[[str], bool],
    tool_shim_direct_file_read_command: Callable[..., str],
    is_package_work_prompt: Callable[[str], bool],
    build_package_scope_search_command: Callable[[str], str | None],
    build_package_scope_repo_diff_command: Callable[[str], str | None],
    build_package_scope_repo_hunks_command: Callable[[str], str | None],
) -> Callable[[str], list[str]]:
    def tool_shim_staged_commands(latest_user_text: str) -> list[str]:
        text = str(latest_user_text or "")
        if not text:
            return []
        command_markers = (
            "Run these exact commands first:",
            "Safe first commands if you need orientation, copy them exactly instead of inventing telemetry queries:",
        )
        for marker in command_markers:
            marker_index = text.find(marker)
            if marker_index < 0:
                continue
            commands: list[str] = []
            trailing_lines = text[marker_index + len(marker):].splitlines()
            for raw_line in trailing_lines:
                line = str(raw_line or "").strip()
                if not line:
                    continue
                if line.startswith("- "):
                    candidate = line[2:].strip()
                elif line.startswith("$ "):
                    candidate = line[2:].strip()
                elif re.match(r"^\d+\.\s+", line):
                    candidate = re.sub(r"^\d+\.\s+", "", line, count=1).strip()
                else:
                    break
                if not candidate:
                    continue
                if candidate.startswith("`") and candidate.endswith("`") and len(candidate) >= 2:
                    candidate = candidate[1:-1].strip()
                if not tool_shim_looks_like_shell_command(candidate):
                    break
                commands.append(candidate)
            if commands:
                return commands

        file_markers = (
            "Read these files directly first:",
            "Read from disk before coding:",
        )
        file_marker_index = -1
        file_marker = ""
        for candidate_marker in file_markers:
            file_marker_index = text.find(candidate_marker)
            if file_marker_index >= 0:
                file_marker = candidate_marker
                break
        if file_marker_index < 0 or not file_marker:
            return []
        shell_commands: list[str] = []
        paths: list[str] = []
        package_worktree = ""
        max_paths = 6
        package_worktree_match = re.search(
            r"^[ \t]*Isolated worktree:\s+([^\s].*)$",
            text,
            flags=re.MULTILINE,
        )
        if package_worktree_match:
            raw_worktree = str(package_worktree_match.group(1) or "").strip()
            if raw_worktree.startswith("/"):
                package_worktree = raw_worktree
                max_paths = 3
        trailing_lines = text[file_marker_index + len(file_marker):].splitlines()
        for raw_line in trailing_lines:
            line = str(raw_line or "").strip()
            if not line:
                continue
            candidate = ""
            if line.startswith("$ "):
                candidate = line[2:].strip()
            elif line.startswith("- "):
                candidate = line[2:].strip()
            elif line.startswith("/"):
                candidate = line
            else:
                break
            if candidate.startswith("`") and candidate.endswith("`") and len(candidate) >= 2:
                candidate = candidate[1:-1].strip()
            bare_absolute_path = candidate.startswith("/") and not re.search(r"\s", candidate)
            if tool_shim_looks_like_shell_command(candidate) and not bare_absolute_path:
                if candidate not in shell_commands:
                    shell_commands.append(candidate)
                continue
            path_token = candidate.split()[0] if candidate else ""
            path_token = path_token.rstrip(",:;")
            if not path_token:
                break
            if not path_token.startswith("/"):
                if not package_worktree:
                    break
                if path_token.startswith(("http://", "https://")):
                    break
                relative_candidate = path_token[2:] if path_token.startswith("./") else path_token
                if not relative_candidate:
                    break
                path_token = str((Path(package_worktree) / relative_candidate).resolve())
            if "..." in path_token:
                continue
            if path_token in paths:
                continue
            paths.append(path_token)
            if len(paths) >= max_paths:
                break
        if shell_commands:
            return shell_commands
        if not paths:
            return []
        commands = []
        package_preview_lines = 20 if package_worktree else 220
        for index, path_text in enumerate(paths):
            prefer_cat = path_text.lower().endswith(".json")
            if not package_worktree and index == 0:
                prefer_cat = True
            commands.append(
                tool_shim_direct_file_read_command(
                    path_text,
                    prefer_cat=prefer_cat,
                    max_lines=package_preview_lines,
                )
            )
        if package_worktree and is_package_work_prompt(text):
            bundled_parts = [
                str(command or "").strip()
                for command in (
                    build_package_scope_search_command(text),
                    build_package_scope_repo_diff_command(text),
                    build_package_scope_repo_hunks_command(text),
                )
                if str(command or "").strip()
            ]
            bundled_parts.extend(
                command.strip()
                for command in commands
                if str(command or "").strip()
            )
            if bundled_parts:
                return [" ; ".join(bundled_parts)]
            return []
        return commands

    tool_shim_staged_commands.__name__ = "tool_shim_staged_commands"
    tool_shim_staged_commands.__qualname__ = "tool_shim_staged_commands"
    return tool_shim_staged_commands
