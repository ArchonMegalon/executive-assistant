from __future__ import annotations

from typing import Callable


def build_tool_shim_direct_final_text(
    *,
    tool_shim_latest_user_text: Callable[[list[dict[str, object]]], str],
    tool_shim_latest_exec_json_output: Callable[[list[dict[str, object]]], dict[str, object] | None],
    tool_shim_local_unblock_final_text: Callable[[dict[str, object]], str | None],
    tool_shim_local_unblock_command_for_prompt: Callable[[str], str | None],
    tool_shim_latest_exec_json_output_for_command: Callable[..., dict[str, object] | None],
    tool_shim_is_operator_parity_build_prompt: Callable[[str], bool],
    tool_shim_parity_build_final_text: Callable[[dict[str, object]], str | None],
    tool_shim_is_operator_ui_parity_audit_prompt: Callable[[str], bool],
    tool_shim_ui_parity_audit_final_text: Callable[[dict[str, object]], str | None],
    tool_shim_is_operator_gap_fix_prompt: Callable[[str], bool],
    tool_shim_gap_fix_final_text: Callable[[dict[str, object]], str | None],
    tool_shim_is_operator_gap_audit_prompt: Callable[[str], bool],
    tool_shim_gap_audit_final_text: Callable[[dict[str, object]], str | None],
    tool_shim_is_operator_readiness_remedy_prompt: Callable[[str], bool],
    tool_shim_direct_staged_git_commit_push_final_text: Callable[[str, list[dict[str, object]]], str | None],
    looks_like_lightweight_ops_query: Callable[[str], tuple[bool, object]],
    tool_shim_latest_function_output: Callable[[list[dict[str, object]]], str],
    tool_shim_scalar_text: Callable[[object], str | None],
) -> Callable[[list[dict[str, object]]], str | None]:
    def tool_shim_direct_final_text(history_items: list[dict[str, object]]) -> str | None:
        latest_user_text = tool_shim_latest_user_text(history_items)
        local_unblock_summary = tool_shim_latest_exec_json_output(history_items)
        if isinstance(local_unblock_summary, dict):
            local_unblock_final = tool_shim_local_unblock_final_text(local_unblock_summary)
            if local_unblock_final:
                return local_unblock_final
        local_unblock_command = tool_shim_local_unblock_command_for_prompt(latest_user_text)
        if local_unblock_command:
            local_unblock_summary = tool_shim_latest_exec_json_output_for_command(
                history_items,
                command_substring="fleet_local_unblock.py",
                probe_kind="fleet_local_unblock",
            )
            if isinstance(local_unblock_summary, dict):
                local_unblock_final = tool_shim_local_unblock_final_text(local_unblock_summary)
                if local_unblock_final:
                    return local_unblock_final
        parity_build_summary = tool_shim_latest_exec_json_output(history_items)
        if tool_shim_is_operator_parity_build_prompt(latest_user_text) and isinstance(parity_build_summary, dict):
            parity_build_final = tool_shim_parity_build_final_text(parity_build_summary)
            if parity_build_final:
                return parity_build_final
        parity_build_summary = tool_shim_latest_exec_json_output_for_command(
            history_items,
            command_substring="codexea_parity_build_workflow.py",
            probe_kind="parity_build",
        )
        if isinstance(parity_build_summary, dict):
            parity_build_final = tool_shim_parity_build_final_text(parity_build_summary)
            if parity_build_final:
                return parity_build_final
        ui_parity_summary = tool_shim_latest_exec_json_output(history_items)
        if tool_shim_is_operator_ui_parity_audit_prompt(latest_user_text) and isinstance(ui_parity_summary, dict):
            ui_parity_final = tool_shim_ui_parity_audit_final_text(ui_parity_summary)
            if ui_parity_final:
                return ui_parity_final
        ui_parity_summary = tool_shim_latest_exec_json_output_for_command(
            history_items,
            command_substring="codexea_ui_parity_audit_probe.py",
            probe_kind="ui_parity_audit",
        )
        if isinstance(ui_parity_summary, dict):
            ui_parity_final = tool_shim_ui_parity_audit_final_text(ui_parity_summary)
            if ui_parity_final:
                return ui_parity_final
        gap_fix_summary = tool_shim_latest_exec_json_output(history_items)
        if tool_shim_is_operator_gap_fix_prompt(latest_user_text) and isinstance(gap_fix_summary, dict):
            gap_fix_final = tool_shim_gap_fix_final_text(gap_fix_summary)
            if gap_fix_final:
                return gap_fix_final
        gap_fix_summary = tool_shim_latest_exec_json_output_for_command(
            history_items,
            command_substring="codexea_gap_fix_workflow.py",
            probe_kind="gap_fix",
        )
        if isinstance(gap_fix_summary, dict):
            gap_fix_final = tool_shim_gap_fix_final_text(gap_fix_summary)
            if gap_fix_final:
                return gap_fix_final
        gap_audit_summary = tool_shim_latest_exec_json_output(history_items)
        if tool_shim_is_operator_gap_audit_prompt(latest_user_text) and isinstance(gap_audit_summary, dict):
            gap_audit_final = tool_shim_gap_audit_final_text(gap_audit_summary)
            if gap_audit_final:
                return gap_audit_final
        gap_audit_summary = tool_shim_latest_exec_json_output_for_command(
            history_items,
            command_substring="codexea_gap_audit_probe.py",
            probe_kind="gap_audit",
        )
        if isinstance(gap_audit_summary, dict):
            gap_audit_final = tool_shim_gap_audit_final_text(gap_audit_summary)
            if gap_audit_final:
                return gap_audit_final
        if tool_shim_is_operator_readiness_remedy_prompt(latest_user_text):
            readiness_summary = tool_shim_latest_exec_json_output(history_items)
            if isinstance(readiness_summary, dict):
                published_trace_exists = readiness_summary.get("published_trace_exists")
                published_audit_status = str(readiness_summary.get("published_audit_status") or "").strip().lower()
                published_audit_reasons = readiness_summary.get("published_audit_reasons")
                if (
                    published_trace_exists is True
                    and published_audit_status in {"pass", "passed", "ready"}
                    and not published_audit_reasons
                ):
                    trace_path = str(readiness_summary.get("published_trace_path") or "").strip()
                    detail_parts = [
                        "Published readiness proof is already materialized.",
                        "status=pass",
                    ]
                    if trace_path:
                        detail_parts.append(f"trace_path={trace_path}")
                    return " ".join(detail_parts)
                status = str(readiness_summary.get("status") or "").strip().lower()
                reasons = readiness_summary.get("reasons")
                if status in {"pass", "passed", "ready"} and not reasons:
                    trace_path = str(readiness_summary.get("trace_path") or "").strip()
                    tester_shard_id = str(readiness_summary.get("tester_shard_id") or "").strip()
                    fix_shard_id = str(readiness_summary.get("fix_shard_id") or "").strip()
                    detail_parts = [
                        "Published the user-journey tester trace and reran the readiness audit.",
                        "status=pass",
                    ]
                    if trace_path:
                        detail_parts.append(f"trace_path={trace_path}")
                    if tester_shard_id:
                        detail_parts.append(f"tester_shard_id={tester_shard_id}")
                    if fix_shard_id:
                        detail_parts.append(f"fix_shard_id={fix_shard_id}")
                    return " ".join(detail_parts)
        staged_git_final_text = tool_shim_direct_staged_git_commit_push_final_text(
            latest_user_text,
            history_items,
        )
        if staged_git_final_text is not None:
            return staged_git_final_text
        lightweight_ops, _ = looks_like_lightweight_ops_query(latest_user_text)
        if not lightweight_ops:
            return None
        output_text = tool_shim_latest_function_output(history_items)
        if not output_text:
            return None
        stripped = output_text.strip()
        if not stripped:
            return None
        if len(stripped) <= 40 and "\n" not in stripped:
            return stripped
        parsed_ok = False
        try:
            import json

            parsed = json.loads(stripped)
            parsed_ok = True
        except Exception:
            parsed = None
        if parsed_ok:
            scalar = tool_shim_scalar_text(parsed)
            if scalar is not None:
                return scalar
        compact_lines = [line.strip() for line in stripped.splitlines() if line.strip()]
        if len(compact_lines) == 1 and len(compact_lines[0]) <= 120:
            return compact_lines[0]
        return None

    tool_shim_direct_final_text.__name__ = "tool_shim_direct_final_text"
    tool_shim_direct_final_text.__qualname__ = "tool_shim_direct_final_text"
    return tool_shim_direct_final_text
