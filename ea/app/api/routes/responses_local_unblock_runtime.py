from __future__ import annotations

from typing import Callable


def tool_shim_local_unblock_command_for_prompt(latest_user_text: str) -> str | None:
    normalized = " ".join(str(latest_user_text or "").strip().lower().split())
    if not normalized:
        return None
    command = "python3 /docker/fleet/scripts/fleet_local_unblock.py"
    if "execute wl-d014-01" in normalized or (
        "review_template_mirror_publish_evidence.md" in normalized
        and "compute source and destination sha-256" in normalized
    ):
        return f"{command} --task review_template_parity"
    if "surface campaign memory and consequences on desktop" in normalized:
        return f"{command} --task verify_ui_campaign_memory"
    if "finish milestone coverage modeling for ui so eta and completion truth are no longer partial" in normalized:
        return f"{command} --task verify_ui_milestone_coverage"
    if "finish milestone coverage modeling for media-factory so eta and completion truth are no longer partial" in normalized:
        return f"{command} --task verify_media_factory_coverage"
    mirror_repo_markers = (
        ("chummer6-mobile", ("recurring `mobile` mirror drift", "sync the approved chummer design bundle into `mobile`")),
        ("chummer6-ui-kit", ("recurring `ui-kit` mirror drift", "sync the approved chummer design bundle into `ui-kit`")),
        ("chummer6-hub-registry", ("recurring `hub-registry` mirror drift", "sync the approved chummer design bundle into `hub-registry`")),
        ("chummer6-media-factory", ("recurring `media-factory` mirror drift", "sync the approved chummer design bundle into `media-factory`")),
        ("chummer6-ui", ("recurring `ui` mirror drift", "sync the approved chummer design bundle into `ui`")),
    )
    for repo_id, markers in mirror_repo_markers:
        if any(marker in normalized for marker in markers):
            return f"{command} --task mirror_sync --repo {repo_id}"
    return None


def build_tool_shim_direct_local_unblock_command(
    *,
    tool_shim_local_unblock_command_for_prompt: Callable[[str], str | None],
    tool_shim_command_sequence_executed: Callable[[list[dict[str, object]], str], bool],
) -> Callable[[str, list[dict[str, object]]], str | None]:
    def tool_shim_direct_local_unblock_command(
        latest_user_text: str,
        history_items: list[dict[str, object]],
    ) -> str | None:
        command = tool_shim_local_unblock_command_for_prompt(latest_user_text)
        if not command:
            return None
        if tool_shim_command_sequence_executed(history_items, command):
            return None
        return command

    tool_shim_direct_local_unblock_command.__name__ = "tool_shim_direct_local_unblock_command"
    tool_shim_direct_local_unblock_command.__qualname__ = "tool_shim_direct_local_unblock_command"
    return tool_shim_direct_local_unblock_command


def tool_shim_local_unblock_final_text(summary: dict[str, object]) -> str | None:
    if str(summary.get("probe_kind") or "").strip().lower() != "fleet_local_unblock":
        return None
    task = str(summary.get("task") or "").strip() or "local_unblock"
    ok = bool(summary.get("ok"))
    message = str(summary.get("message") or "").strip()
    details = str(summary.get("details") or "").strip()
    if ok:
        shipped = message or f"completed {task}"
        if details:
            return f"Completed local unblock task `{task}`.\n\nWhat shipped: {shipped}\n\nEvidence: {details}"
        return f"Completed local unblock task `{task}`.\n\nWhat shipped: {shipped}"
    error = str(summary.get("error") or "").strip()
    if not error:
        exit_code = str(summary.get("exit_code") or "").strip()
        error = f"{task}:exit_{exit_code}" if exit_code else task
    result = f"Error: local_unblock_failed:{error}"
    if details:
        result += f"\n\nWhat remains: {details}"
    return result
