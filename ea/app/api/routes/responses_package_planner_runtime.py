from __future__ import annotations

from typing import Any, Callable


def build_tool_shim_package_planner_blocked_final_text(
    *,
    is_package_work_prompt: Callable[[str], bool],
    tool_shim_exec_command_identity_history: Callable[[list[dict[str, object]]], list[str]],
    tool_shim_staged_commands: Callable[[str], list[str]],
    tool_shim_command_identity_sequence: Callable[[str], list[str]],
    tool_shim_build_package_scope_repo_diff_command: Callable[[str], str | None],
    tool_shim_command_identity: Callable[[str], str],
    tool_shim_build_package_scope_repo_hunks_command: Callable[[str], str | None],
    tool_shim_build_package_scope_search_command: Callable[[str], str | None],
    tool_shim_package_scope_text: Callable[[str], str],
    tool_shim_package_current_slice_text: Callable[[str], str],
) -> Callable[..., str | None]:
    def tool_shim_package_planner_blocked_final_text(
        latest_user_text: str,
        history_items: list[dict[str, object]],
        *,
        failure_message: str,
    ) -> str | None:
        if not is_package_work_prompt(latest_user_text):
            return None
        progress_markers: list[str] = []
        executed_commands = set(tool_shim_exec_command_identity_history(history_items))
        staged_commands = tool_shim_staged_commands(latest_user_text)
        if staged_commands:
            expected_commands: list[str] = []
            for command in staged_commands:
                expected_commands.extend(tool_shim_command_identity_sequence(command))
            if expected_commands and all(command in executed_commands for command in expected_commands):
                progress_markers.append("completed staged repo reads")
        package_scope_diff_command = tool_shim_build_package_scope_repo_diff_command(latest_user_text)
        if package_scope_diff_command and tool_shim_command_identity(package_scope_diff_command) in executed_commands:
            progress_markers.append("inspected package-scope git status and diff")
        package_scope_hunks_command = tool_shim_build_package_scope_repo_hunks_command(latest_user_text)
        if package_scope_hunks_command and tool_shim_command_identity(package_scope_hunks_command) in executed_commands:
            progress_markers.append("inspected package-scope diff hunks")
        package_scope_search_command = tool_shim_build_package_scope_search_command(latest_user_text)
        if package_scope_search_command and tool_shim_command_identity(package_scope_search_command) in executed_commands:
            progress_markers.append("searched the allowed package paths for slice-specific matches")
        shipped = "; ".join(progress_markers) if progress_markers else "completed local package orientation"
        package_scope = tool_shim_package_scope_text(latest_user_text)
        current_slice = tool_shim_package_current_slice_text(latest_user_text)
        remains = f"retry {package_scope or 'this package'} after planner capacity recovers"
        if current_slice:
            remains += f" for slice `{current_slice}`"
        return (
            f"Error: {failure_message}\n\n"
            f"What shipped: {shipped}\n\n"
            f"What remains: {remains}\n\n"
            f"Exact blocker: {failure_message}"
        )

    tool_shim_package_planner_blocked_final_text.__name__ = "tool_shim_package_planner_blocked_final_text"
    tool_shim_package_planner_blocked_final_text.__qualname__ = "tool_shim_package_planner_blocked_final_text"
    return tool_shim_package_planner_blocked_final_text


def build_tool_shim_package_planner_blocked_decision(
    *,
    tool_shim_package_planner_blocked_final_text: Callable[..., str | None],
    decision_cls: Callable[..., Any],
    tool_shim_local_upstream_result: Callable[[str], Any],
) -> Callable[..., Any | None]:
    def tool_shim_package_planner_blocked_decision(
        latest_user_text: str,
        history_items: list[dict[str, object]],
        *,
        failure_message: str,
    ) -> Any | None:
        final_text = tool_shim_package_planner_blocked_final_text(
            latest_user_text,
            history_items,
            failure_message=failure_message,
        )
        if not final_text:
            return None
        return decision_cls(
            kind="final",
            text=final_text,
            upstream_result=tool_shim_local_upstream_result(
                final_text,
                reason="tool_shim_package_planner_blocked",
            ),
        )

    tool_shim_package_planner_blocked_decision.__name__ = "tool_shim_package_planner_blocked_decision"
    tool_shim_package_planner_blocked_decision.__qualname__ = "tool_shim_package_planner_blocked_decision"
    return tool_shim_package_planner_blocked_decision


def tool_shim_provider_row_is_ready(provider: dict[str, object]) -> bool:
    state = str(provider.get("state") or "").strip().lower()
    if state == "ready":
        return True
    slots = [dict(item) for item in (provider.get("slots") or []) if isinstance(item, dict)]
    return any(str(slot.get("state") or "").strip().lower() == "ready" for slot in slots)


def build_tool_shim_provider_row_is_dispatchable(
    *,
    tool_shim_provider_row_is_ready: Callable[[dict[str, object]], bool],
) -> Callable[[dict[str, object]], bool]:
    def tool_shim_provider_row_is_dispatchable(provider: dict[str, object]) -> bool:
        if not isinstance(provider, dict) or not provider:
            return False
        for field_name in ("live_dispatchable_slot_count", "live_ready_slot_count", "ready_slot_count"):
            value = provider.get(field_name)
            if value in (None, ""):
                continue
            try:
                return int(value) > 0
            except Exception:
                continue
        return tool_shim_provider_row_is_ready(provider)

    tool_shim_provider_row_is_dispatchable.__name__ = "tool_shim_provider_row_is_dispatchable"
    tool_shim_provider_row_is_dispatchable.__qualname__ = "tool_shim_provider_row_is_dispatchable"
    return tool_shim_provider_row_is_dispatchable


def build_tool_shim_package_planner_preflight_failure_message(
    *,
    provider_health_snapshot: Callable[..., dict[str, object] | None],
    tool_shim_provider_row_is_dispatchable: Callable[[dict[str, object]], bool],
    tool_shim_provider_row_is_ready: Callable[[dict[str, object]], bool],
) -> Callable[[], str | None]:
    def tool_shim_package_planner_preflight_failure_message() -> str | None:
        snapshot = provider_health_snapshot(lightweight=True)
        providers = dict((snapshot.get("providers") or {})) if isinstance(snapshot, dict) else {}
        if not providers:
            return None
        onemin = dict(providers.get("onemin") or {})
        gemini = dict(providers.get("gemini_vortex") or {})
        magix = dict(providers.get("magixai") or {})
        onemin_ready = tool_shim_provider_row_is_dispatchable(onemin)
        gemini_ready = tool_shim_provider_row_is_ready(gemini)
        magix_ready = tool_shim_provider_row_is_ready(magix)
        if onemin_ready or gemini_ready or magix_ready:
            return None
        reasons: list[str] = []
        onemin_dispatchable = onemin.get("live_dispatchable_slot_count")
        if onemin_dispatchable in (None, ""):
            reasons.append("onemin_dispatchable=0")
        else:
            reasons.append(f"onemin_dispatchable={onemin_dispatchable}")
        gemini_state = str(gemini.get("state") or "").strip().lower() or "unknown"
        gemini_detail = " ".join(str(gemini.get("detail") or "").split()).strip()
        reasons.append(f"gemini_vortex={gemini_state}{':' + gemini_detail if gemini_detail else ''}")
        magix_state = str(magix.get("state") or "").strip().lower() or "unknown"
        magix_detail = " ".join(str(magix.get("detail") or "").split()).strip()
        reasons.append(f"magixai={magix_state}{':' + magix_detail if magix_detail else ''}")
        return "upstream_unavailable:planner_capacity_preflight:" + "; ".join(reasons[:3])

    tool_shim_package_planner_preflight_failure_message.__name__ = "tool_shim_package_planner_preflight_failure_message"
    tool_shim_package_planner_preflight_failure_message.__qualname__ = "tool_shim_package_planner_preflight_failure_message"
    return tool_shim_package_planner_preflight_failure_message
