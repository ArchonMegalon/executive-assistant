from __future__ import annotations

from typing import Callable


def build_tool_shim_transcript_limit_for_prompt(
    *,
    tool_shim_transcript_max_chars: Callable[[], int],
    is_operator_fleet_unblock_prompt: Callable[[str], bool],
    is_operator_readiness_remedy_prompt: Callable[[str], bool],
    is_staged_local_orientation_prompt: Callable[[str], bool],
) -> Callable[[str], int]:
    def tool_shim_transcript_limit_for_prompt(text: str) -> int:
        default_limit = tool_shim_transcript_max_chars()
        if is_operator_fleet_unblock_prompt(text):
            return max(1200, min(default_limit, 1800))
        if is_operator_readiness_remedy_prompt(text):
            return max(1400, min(default_limit, 2200))
        if is_staged_local_orientation_prompt(text):
            return max(1400, min(default_limit, 2600))
        return default_limit

    tool_shim_transcript_limit_for_prompt.__name__ = "tool_shim_transcript_limit_for_prompt"
    tool_shim_transcript_limit_for_prompt.__qualname__ = "tool_shim_transcript_limit_for_prompt"
    return tool_shim_transcript_limit_for_prompt


def build_tool_shim_compact_operator_prompt_for_planner(
    *,
    is_operator_fleet_unblock_prompt: Callable[[str], bool],
) -> Callable[[str], str]:
    def tool_shim_compact_operator_prompt_for_planner(text: str) -> str:
        prompt = str(text or "")
        if not is_operator_fleet_unblock_prompt(prompt):
            return prompt
        marker = "\n\nPrepared repo context:\n"
        marker_index = prompt.find(marker)
        if marker_index < 0:
            return prompt
        before = prompt[:marker_index].rstrip()
        after = prompt[marker_index + len(marker):]
        snapshot_marker = "\n\nLive fleet snapshot:\n"
        snapshot_index = after.find(snapshot_marker)
        prepared_block = after[:snapshot_index] if snapshot_index >= 0 else after
        tail = after[snapshot_index:] if snapshot_index >= 0 else ""
        prepared_lines = [line.strip() for line in prepared_block.splitlines() if line.strip()]
        command_lines = [line for line in prepared_lines if line.startswith("$ ")]
        interesting_lines: list[str] = []
        for line in prepared_lines:
            if line.startswith("$ git -C "):
                interesting_lines.append(line)
            elif "file changed" in line or "insertions(" in line or "deletions(" in line:
                interesting_lines.append(line)
            elif line.startswith("$ rg -n "):
                interesting_lines.append(line)
            if len(interesting_lines) >= 8:
                break
        summary_lines = [
            "Prepared repo context summary:",
            f"- Bootstrap context was already captured from {len(command_lines)} local commands.",
            "- Avoid rerunning broad orientation reads unless a narrower line window is missing.",
        ]
        if interesting_lines:
            summary_lines.extend(interesting_lines)
        return "\n\n".join(
            part
            for part in (
                before,
                "\n".join(summary_lines).strip(),
                tail.strip(),
            )
            if str(part or "").strip()
        ).strip()

    tool_shim_compact_operator_prompt_for_planner.__name__ = "tool_shim_compact_operator_prompt_for_planner"
    tool_shim_compact_operator_prompt_for_planner.__qualname__ = "tool_shim_compact_operator_prompt_for_planner"
    return tool_shim_compact_operator_prompt_for_planner


def build_tool_shim_compact_readiness_prompt_for_planner(
    *,
    is_operator_readiness_remedy_prompt: Callable[[str], bool],
) -> Callable[[str], str]:
    def tool_shim_compact_readiness_prompt_for_planner(text: str) -> str:
        prompt = str(text or "")
        if not is_operator_readiness_remedy_prompt(prompt):
            return prompt
        marker = "\n\nPrepared repo context:\n"
        marker_index = prompt.find(marker)
        if marker_index < 0:
            return prompt
        before = prompt[:marker_index].rstrip()
        after = prompt[marker_index + len(marker):]
        objective_marker = "\n\nObjective:\n"
        objective_index = after.find(objective_marker)
        prepared_block = after[:objective_index] if objective_index >= 0 else after
        tail = after[objective_index:] if objective_index >= 0 else ""
        prepared_lines = [line.strip() for line in prepared_block.splitlines() if line.strip()]
        command_lines = [line for line in prepared_lines if line.startswith("$ ")]
        interesting_lines: list[str] = []
        for line in prepared_lines:
            if (
                "fail:" in line.lower()
                or "trace is missing" in line.lower()
                or "used_internal_apis=false" in line.lower()
                or "tester_shard_id" in line
                or line.startswith("$ git -C ")
                or "file changed" in line
                or "insertions(" in line
                or "deletions(" in line
            ):
                interesting_lines.append(line)
            if len(interesting_lines) >= 10:
                break
        summary_lines = [
            "Prepared repo context summary:",
            f"- Bootstrap context was already captured from {len(command_lines)} local commands.",
            "- Avoid rerunning the broad readiness bootstrap unless a narrower line window is missing.",
        ]
        if interesting_lines:
            summary_lines.extend(interesting_lines)
        return "\n\n".join(
            part
            for part in (
                before,
                "\n".join(summary_lines).strip(),
                tail.strip(),
            )
            if str(part or "").strip()
        ).strip()

    tool_shim_compact_readiness_prompt_for_planner.__name__ = "tool_shim_compact_readiness_prompt_for_planner"
    tool_shim_compact_readiness_prompt_for_planner.__qualname__ = "tool_shim_compact_readiness_prompt_for_planner"
    return tool_shim_compact_readiness_prompt_for_planner
