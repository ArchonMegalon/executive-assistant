from __future__ import annotations

import shlex
from pathlib import Path
from typing import Callable


def build_tool_shim_staged_first_command_max_output_tokens(
    *,
    is_package_work_prompt: Callable[[str], bool],
    is_operator_parity_build_prompt: Callable[[str], bool],
    is_operator_ui_parity_audit_prompt: Callable[[str], bool],
    is_operator_gap_fix_prompt: Callable[[str], bool],
    is_operator_gap_audit_prompt: Callable[[str], bool],
) -> Callable[[str], int]:
    def tool_shim_staged_first_command_max_output_tokens(latest_user_text: str) -> int:
        if is_package_work_prompt(latest_user_text):
            return 5000
        if is_operator_parity_build_prompt(latest_user_text):
            return 7000
        if is_operator_ui_parity_audit_prompt(latest_user_text):
            return 5000
        if is_operator_gap_fix_prompt(latest_user_text):
            return 6000
        if is_operator_gap_audit_prompt(latest_user_text):
            return 3000
        return 1500

    tool_shim_staged_first_command_max_output_tokens.__name__ = "tool_shim_staged_first_command_max_output_tokens"
    tool_shim_staged_first_command_max_output_tokens.__qualname__ = "tool_shim_staged_first_command_max_output_tokens"
    return tool_shim_staged_first_command_max_output_tokens


def build_tool_shim_direct_local_fleet_command(
    *,
    is_package_work_prompt: Callable[[str], bool],
    is_operator_fleet_unblock_context: Callable[[str, list[dict[str, object]]], bool],
    prompt_forbids_local_fleet_telemetry: Callable[[str], bool],
) -> Callable[[str, list[dict[str, object]] | None], str | None]:
    def tool_shim_direct_local_fleet_command(
        latest_user_text: str,
        history_items: list[dict[str, object]] | None = None,
    ) -> str | None:
        normalized = " ".join(str(latest_user_text or "").strip().lower().split())
        if "fleet" not in normalized:
            return None
        if is_package_work_prompt(latest_user_text):
            return None
        if is_operator_fleet_unblock_context(latest_user_text, history_items or []):
            return None
        if prompt_forbids_local_fleet_telemetry(normalized):
            return None
        state_root = Path("/docker/fleet/state/chummer_design_supervisor")
        supervisor_script = Path("/docker/fleet/scripts/chummer_design_supervisor.py")
        if not supervisor_script.exists() or not state_root.exists():
            return None
        eta_cmd = (
            "python3 /docker/fleet/scripts/chummer_design_supervisor.py "
            "eta --state-root /docker/fleet/state/chummer_design_supervisor --json"
        )
        status_cmd = (
            "python3 /docker/fleet/scripts/chummer_design_supervisor.py "
            "status --state-root /docker/fleet/state/chummer_design_supervisor --json"
        )

        def _json_field(cmd: str, expr: str) -> str:
            return (
                f"{cmd} | "
                "python3 -c "
                + shlex.quote(
                    "import json,sys; payload=json.load(sys.stdin); " + expr
                )
            )

        if "how many" in normalized and "milestone" in normalized and "not started" in normalized:
            return _json_field(eta_cmd, "print((payload or {}).get('remaining_not_started_milestones', ''))")
        if "how many" in normalized and "milestone" in normalized and "in progress" in normalized:
            return _json_field(eta_cmd, "print((payload or {}).get('remaining_in_progress_milestones', ''))")
        if "how many" in normalized and "milestone" in normalized and "open" in normalized:
            return _json_field(eta_cmd, "print((payload or {}).get('remaining_open_milestones', ''))")
        if "how many" in normalized and "shard" in normalized and any(token in normalized for token in ("running", "active")):
            return _json_field(status_cmd, "print((payload or {}).get('active_runs_count', ''))")
        if normalized.startswith("eta") or "eta of the fleet" in normalized or "fleet eta" in normalized:
            return _json_field(
                eta_cmd,
                "print((payload or {}).get('summary') or (payload or {}).get('eta_human') or json.dumps(payload,separators=(',',':')))"
            )
        if (
            any(
                normalized.startswith(prefix)
                for prefix in ("fleet ", "status ", "show ", "list ", "what ", "how many ", "are ")
            )
            and any(token in normalized for token in ("status", "running", "milestone", "shard"))
        ):
            return (
                f"{status_cmd} | "
                "python3 -c "
                + shlex.quote(
                    "import json,sys; payload=json.load(sys.stdin) or {}; eta=payload.get('eta') or {}; "
                    "out={'active_runs_count':payload.get('active_runs_count'),"
                    "'remaining_open_milestones':eta.get('remaining_open_milestones'),"
                    "'remaining_not_started_milestones':eta.get('remaining_not_started_milestones'),"
                    "'remaining_in_progress_milestones':eta.get('remaining_in_progress_milestones'),"
                    "'eta_human':eta.get('eta_human'),'summary':eta.get('summary')}; "
                    "print(json.dumps(out,separators=(',',':')))"
                )
            )
        return None

    tool_shim_direct_local_fleet_command.__name__ = "tool_shim_direct_local_fleet_command"
    tool_shim_direct_local_fleet_command.__qualname__ = "tool_shim_direct_local_fleet_command"
    return tool_shim_direct_local_fleet_command
