from __future__ import annotations

import re
import shlex
from typing import Callable


def build_tool_shim_is_operator_fleet_unblock_context(
    *,
    is_operator_fleet_unblock_prompt: Callable[[str], bool],
    is_package_work_prompt: Callable[[str], bool],
    tool_shim_exec_command_history: Callable[[list[dict[str, object]]], list[str]],
) -> Callable[[str, list[dict[str, object]]], bool]:
    def tool_shim_is_operator_fleet_unblock_context(
        latest_user_text: str,
        history_items: list[dict[str, object]],
    ) -> bool:
        if is_operator_fleet_unblock_prompt(latest_user_text):
            return True
        if is_package_work_prompt(latest_user_text):
            return False
        commands = tool_shim_exec_command_history(history_items)
        saw_shim_hotspot = any(
            "/docker/fleet/scripts/codex-shims/codexea" in command
            or "/docker/fleet/scripts/codex-shims/python3" in command
            for command in commands
        )
        saw_ea_hotspot = any(
            "/docker/EA/ea/app/api/routes/responses.py" in command
            or "/docker/EA/ea/app/services/onemin_manager.py" in command
            or "/docker/EA/ea/app/services/responses_upstream.py" in command
            for command in commands
        )
        if saw_shim_hotspot and saw_ea_hotspot:
            return True
        return False

    tool_shim_is_operator_fleet_unblock_context.__name__ = "tool_shim_is_operator_fleet_unblock_context"
    tool_shim_is_operator_fleet_unblock_context.__qualname__ = "tool_shim_is_operator_fleet_unblock_context"
    return tool_shim_is_operator_fleet_unblock_context


def build_tool_shim_operator_unblock_scope_rejection_reason(
    *,
    is_operator_fleet_unblock_context: Callable[[str, list[dict[str, object]]], bool],
) -> Callable[..., str | None]:
    def tool_shim_operator_unblock_scope_rejection_reason(
        *,
        latest_user_text: str,
        cmd: str,
        history_items: list[dict[str, object]] | None = None,
    ) -> str | None:
        if not is_operator_fleet_unblock_context(latest_user_text, history_items or []):
            return None
        allowed_exact_paths = {
            "/docker/fleet/WORKLIST.md",
            "/docker/fleet/README.md",
        }
        allowed_prefixes = (
            "/docker/fleet/scripts/codex-shims/",
            "/docker/fleet/tests/",
            "/docker/EA/ea/app/",
            "/docker/EA/tests/",
        )
        allowed_shard_artifact_suffixes = (
            "/WORKER_EXEC_TRACE_PROMPT.md",
            "/worker.stderr.log",
            "/TASK_LOCAL_TELEMETRY.generated.json",
            "/TASK_RUNTIME_HANDOFF.generated.json",
        )
        shard_state_paths = re.findall(
            r"((?:/docker/fleet/state|/var/lib/codex-fleet)/chummer_design_supervisor/shard-[^ \t\n'\"`]+)",
            cmd,
        )
        for shard_state_path in shard_state_paths:
            normalized_path = str(shard_state_path or "").strip()
            if not normalized_path:
                continue
            if any(normalized_path.endswith(suffix) for suffix in allowed_shard_artifact_suffixes):
                continue
            return (
                "This operator fleet-unblock run may inspect only shard-run prompt/log artifacts needed to "
                "reproduce the live worker path. Do not inspect broader shard state or backlog content under "
                "`/docker/fleet/state/chummer_design_supervisor/shard-*`."
            )
        allowed_git_roots: set[str] = set()
        for raw_git_command in [part.strip() for part in cmd.split(";") if str(part).strip()]:
            git_path_command = raw_git_command.split("|", 1)[0].strip()
            git_root_match = re.search(r"^git\s+-C\s+(/[^ \t]+)", git_path_command)
            if not git_root_match:
                continue
            git_root = str(git_root_match.group(1) or "").strip()
            if not git_root:
                continue
            allowed_git_roots.add(git_root)
            git_path_args = re.findall(r"(?:^|\s)--\s+(.+)$", git_path_command)
            rel_paths = []
            if git_path_args:
                rel_paths = [
                    token
                    for token in shlex.split(git_path_args[-1])
                    if token and not token.startswith("-")
                ]
            if git_root == "/docker/EA":
                if any(not (path.startswith("ea/app/") or path.startswith("tests/")) for path in rel_paths):
                    return (
                        "This operator fleet-unblock run is scoped to EA endpoint and 1min-manager code only. "
                        "Do not inspect or diff top-level EA task docs such as `TASKS_WORK_LOG.md` or `MILESTONE.json`."
                    )
            if git_root == "/docker/fleet":
                if any(
                    path not in {"WORKLIST.md", "README.md"}
                    and not path.startswith("scripts/codex-shims/")
                    and not path.startswith("tests/")
                    for path in rel_paths
                ):
                    return (
                        "This operator fleet-unblock run is scoped to the codexea shim and Fleet unblock helpers only. "
                        "Do not inspect or diff repo worklists, published artifacts, or other non-shim Fleet content."
                    )
        command_paths = [
            str(match or "").strip()
            for match in re.findall(r"(/[A-Za-z0-9._/\-]+)", cmd)
            if str(match or "").strip()
        ]
        for path_text in command_paths:
            if path_text in allowed_git_roots:
                continue
            if path_text in allowed_exact_paths or any(path_text.startswith(prefix) for prefix in allowed_prefixes):
                continue
            if path_text.startswith("/docker/fleet/state/chummer_design_supervisor/shard-") and any(
                path_text.endswith(suffix) for suffix in allowed_shard_artifact_suffixes
            ):
                continue
            if path_text.startswith("/var/lib/codex-fleet/chummer_design_supervisor/shard-") and any(
                path_text.endswith(suffix) for suffix in allowed_shard_artifact_suffixes
            ):
                continue
            if path_text.startswith("/docker/EA/") or path_text.startswith("/docker/fleet/"):
                return (
                    "This operator fleet-unblock run may read only the codexea shim, Fleet unblock tests, "
                    "EA endpoint/1min-manager code, exact Fleet orientation files, and matching shard-run artifacts."
                )
        blocked_roots = (
            "/docker/chummercomplete/",
            "/docker/fleet/.codex-studio/",
            "/docker/fleet/state/chummer_design_supervisor/shard-",
            "/var/lib/codex-fleet/chummer_design_supervisor/shard-",
        )
        for root in blocked_roots:
            if root in {
                "/docker/fleet/state/chummer_design_supervisor/shard-",
                "/var/lib/codex-fleet/chummer_design_supervisor/shard-",
            } and shard_state_paths:
                disallowed = [
                    path
                    for path in shard_state_paths
                    if not any(str(path or "").strip().endswith(suffix) for suffix in allowed_shard_artifact_suffixes)
                ]
                if not disallowed:
                    continue
            if root in cmd:
                return (
                    "This operator fleet-unblock run is scoped to the codexea shim, EA endpoints, "
                    "and the 1min manager. Do not inspect shard content, backlog artifacts, or "
                    f"product repos under `{root}`. Stay within `/docker/fleet/scripts/codex-shims/`, "
                    "`/docker/fleet/tests/`, `/docker/EA/ea/app/`, `/docker/EA/tests/`, or direct "
                    "`ea-api` verification commands."
                )
        git_cwd_match = re.search(r"(?:^|\\s)-C\\s+(/[^ \\t]+)", cmd)
        if git_cwd_match:
            git_cwd = str(git_cwd_match.group(1) or "").strip()
            if git_cwd.startswith("/docker/chummercomplete/"):
                return (
                    "This operator fleet-unblock run must not pivot into `/docker/chummercomplete/*` repos. "
                    "Use `/docker/fleet` or `/docker/EA` targets only for unblock-path diagnosis and verification."
                )
        return None

    tool_shim_operator_unblock_scope_rejection_reason.__name__ = "tool_shim_operator_unblock_scope_rejection_reason"
    tool_shim_operator_unblock_scope_rejection_reason.__qualname__ = "tool_shim_operator_unblock_scope_rejection_reason"
    return tool_shim_operator_unblock_scope_rejection_reason
