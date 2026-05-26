from __future__ import annotations

import re
import shlex
from pathlib import Path
from typing import Callable


def _repo_root_for_path(path: Path) -> Path | None:
    current = path.parent if path.is_file() else path
    for candidate in (current, *current.parents):
        git_marker = candidate / ".git"
        if git_marker.exists():
            return candidate
    return None


def build_tool_shim_build_repo_diff_command_for_paths(
    *,
    tool_shim_resolve_equivalent_shard_runtime_path: Callable[[str], str],
) -> Callable[[list[str]], str | None]:
    def tool_shim_build_repo_diff_command_for_paths(raw_paths: list[str]) -> str | None:
        if not raw_paths:
            return None
        path_groups: dict[str, list[str]] = {}
        seen_paths: set[str] = set()
        for raw_path in raw_paths:
            normalized_path = tool_shim_resolve_equivalent_shard_runtime_path(str(raw_path or "").strip())
            if not normalized_path or normalized_path in seen_paths:
                continue
            path = Path(normalized_path)
            if not path.exists() or not path.is_file():
                continue
            repo_root_path = _repo_root_for_path(path)
            if repo_root_path is None:
                continue
            repo_root = str(repo_root_path)
            if not repo_root:
                continue
            try:
                rel_path = str(path.relative_to(repo_root_path))
            except Exception:
                continue
            path_groups.setdefault(repo_root, []).append(rel_path)
            seen_paths.add(normalized_path)
        parts: list[str] = []
        for repo_root, rel_paths in path_groups.items():
            deduped_rel_paths = list(dict.fromkeys(rel_paths))
            if not deduped_rel_paths:
                continue
            quoted_root = shlex.quote(repo_root)
            quoted_paths = " ".join(shlex.quote(item) for item in deduped_rel_paths)
            parts.append(f"git -C {quoted_root} status --short -- {quoted_paths}")
            parts.append(f"git -C {quoted_root} diff --stat -- {quoted_paths}")
        if not parts:
            return None
        return " ; ".join(parts)

    tool_shim_build_repo_diff_command_for_paths.__name__ = "tool_shim_build_repo_diff_command_for_paths"
    tool_shim_build_repo_diff_command_for_paths.__qualname__ = "tool_shim_build_repo_diff_command_for_paths"
    return tool_shim_build_repo_diff_command_for_paths


def _extract_command_paths(commands: list[str]) -> list[str]:
    extracted_paths: list[str] = []
    seen_paths: set[str] = set()
    for command in commands:
        for match in re.findall(r"(/[A-Za-z0-9._/\-]+)", str(command or "")):
            raw_path = str(match or "").strip()
            if not raw_path or raw_path in seen_paths:
                continue
            extracted_paths.append(raw_path)
            seen_paths.add(raw_path)
    worktree_paths = [
        path_text
        for path_text in extracted_paths
        if "/var/lib/codex-fleet/worktrees/" in path_text or "/docker/fleet/worktrees/" in path_text
    ]
    if worktree_paths:
        return worktree_paths
    return extracted_paths


def build_tool_shim_build_staged_repo_diff_command(
    *,
    tool_shim_build_repo_diff_command_for_paths: Callable[[list[str]], str | None],
) -> Callable[[list[str]], str | None]:
    def tool_shim_build_staged_repo_diff_command(commands: list[str]) -> str | None:
        if not commands:
            return None
        return tool_shim_build_repo_diff_command_for_paths(_extract_command_paths(commands))

    tool_shim_build_staged_repo_diff_command.__name__ = "tool_shim_build_staged_repo_diff_command"
    tool_shim_build_staged_repo_diff_command.__qualname__ = "tool_shim_build_staged_repo_diff_command"
    return tool_shim_build_staged_repo_diff_command


def build_tool_shim_build_repo_hunks_command_for_paths(
    *,
    tool_shim_resolve_equivalent_shard_runtime_path: Callable[[str], str],
) -> Callable[[list[str]], str | None]:
    def tool_shim_build_repo_hunks_command_for_paths(raw_paths: list[str]) -> str | None:
        if not raw_paths:
            return None
        path_groups: dict[str, list[str]] = {}
        seen_paths: set[str] = set()
        for raw_path in raw_paths:
            normalized_path = tool_shim_resolve_equivalent_shard_runtime_path(str(raw_path or "").strip())
            if not normalized_path or normalized_path in seen_paths:
                continue
            path = Path(normalized_path)
            if not path.exists() or not path.is_file():
                continue
            repo_root_path = _repo_root_for_path(path)
            if repo_root_path is None:
                continue
            try:
                rel_path = str(path.relative_to(repo_root_path))
            except Exception:
                continue
            path_groups.setdefault(str(repo_root_path), []).append(rel_path)
            seen_paths.add(normalized_path)
        parts: list[str] = []
        for repo_root, rel_paths in path_groups.items():
            deduped_rel_paths = list(dict.fromkeys(rel_paths))
            if not deduped_rel_paths:
                continue
            quoted_root = shlex.quote(repo_root)
            quoted_paths = " ".join(shlex.quote(item) for item in deduped_rel_paths)
            parts.append(f"git -C {quoted_root} diff --unified=0 -- {quoted_paths} | sed -n '1,200p'")
        if not parts:
            return None
        return " ; ".join(parts)

    tool_shim_build_repo_hunks_command_for_paths.__name__ = "tool_shim_build_repo_hunks_command_for_paths"
    tool_shim_build_repo_hunks_command_for_paths.__qualname__ = "tool_shim_build_repo_hunks_command_for_paths"
    return tool_shim_build_repo_hunks_command_for_paths


def build_tool_shim_build_staged_repo_hunks_command(
    *,
    tool_shim_build_repo_hunks_command_for_paths: Callable[[list[str]], str | None],
) -> Callable[[list[str]], str | None]:
    def tool_shim_build_staged_repo_hunks_command(commands: list[str]) -> str | None:
        if not commands:
            return None
        return tool_shim_build_repo_hunks_command_for_paths(_extract_command_paths(commands))

    tool_shim_build_staged_repo_hunks_command.__name__ = "tool_shim_build_staged_repo_hunks_command"
    tool_shim_build_staged_repo_hunks_command.__qualname__ = "tool_shim_build_staged_repo_hunks_command"
    return tool_shim_build_staged_repo_hunks_command


def build_tool_shim_operator_unblock_repo_diff_command(
    *,
    tool_shim_build_repo_diff_command_for_paths: Callable[[list[str]], str | None],
) -> Callable[[], str | None]:
    def tool_shim_operator_unblock_repo_diff_command() -> str | None:
        return tool_shim_build_repo_diff_command_for_paths(
            [
                "/docker/fleet/scripts/codex-shims/codexea",
                "/docker/fleet/scripts/codex-shims/python3",
                "/docker/EA/ea/app/api/routes/responses.py",
                "/docker/EA/ea/app/services/onemin_manager.py",
                "/docker/EA/ea/app/services/responses_upstream.py",
            ]
        )

    tool_shim_operator_unblock_repo_diff_command.__name__ = "tool_shim_operator_unblock_repo_diff_command"
    tool_shim_operator_unblock_repo_diff_command.__qualname__ = "tool_shim_operator_unblock_repo_diff_command"
    return tool_shim_operator_unblock_repo_diff_command


def build_tool_shim_operator_unblock_repo_hunks_command(
    *,
    tool_shim_build_repo_hunks_command_for_paths: Callable[[list[str]], str | None],
) -> Callable[[], str | None]:
    def tool_shim_operator_unblock_repo_hunks_command() -> str | None:
        return tool_shim_build_repo_hunks_command_for_paths(
            [
                "/docker/fleet/scripts/codex-shims/codexea",
                "/docker/fleet/scripts/codex-shims/python3",
                "/docker/EA/ea/app/api/routes/responses.py",
                "/docker/EA/ea/app/services/onemin_manager.py",
                "/docker/EA/ea/app/services/responses_upstream.py",
            ]
        )

    tool_shim_operator_unblock_repo_hunks_command.__name__ = "tool_shim_operator_unblock_repo_hunks_command"
    tool_shim_operator_unblock_repo_hunks_command.__qualname__ = "tool_shim_operator_unblock_repo_hunks_command"
    return tool_shim_operator_unblock_repo_hunks_command
