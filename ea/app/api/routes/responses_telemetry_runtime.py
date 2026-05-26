from __future__ import annotations

import os
import shlex
from typing import Callable


def tool_shim_direct_compact_provider_health_command(path_text: str) -> str:
    script = "\n".join(
        [
            "from pathlib import Path",
            "import json",
            "import sys",
            "",
            "def _to_float(value):",
            "    try:",
            "        return float(value)",
            "    except Exception:",
            "        return None",
            "",
            "payload = json.loads(Path(sys.argv[1]).read_text(encoding='utf-8', errors='replace'))",
            "root = (payload.get('payload') or payload) if isinstance(payload, dict) else {}",
            "providers = (root.get('providers') or {}) if isinstance(root, dict) else {}",
            "onemin = (providers.get('onemin') or {}) if isinstance(providers, dict) else {}",
            "slots = [slot for slot in (onemin.get('slots') or []) if isinstance(slot, dict)]",
            "counts = {}",
            "for slot in slots:",
            "    state = str(slot.get('state') or 'unknown').strip() or 'unknown'",
            "    counts[state] = counts.get(state, 0) + 1",
            "blocked = []",
            "for slot in slots:",
            "    state = str(slot.get('state') or 'unknown').strip() or 'unknown'",
            "    if state not in {'quarantine', 'degraded', 'unavailable'}:",
            "        continue",
            "    blocked.append({",
            "        'account_name': str(slot.get('account_name') or ''),",
            "        'slot_env_name': str(slot.get('slot_env_name') or ''),",
            "        'state': state,",
            "        'remaining_credits': slot.get('remaining_credits'),",
            "        'required_credits': slot.get('required_credits'),",
            "        'last_probe_result': str(slot.get('last_probe_result') or ''),",
            "        'last_probe_detail': str(slot.get('last_probe_detail') or ''),",
            "    })",
            "blocked = blocked[:8]",
            "billing_live_mismatch_slots = []",
            "for slot in slots:",
            "    billing = slot.get('billing_remaining_credits')",
            "    live = slot.get('remaining_credits')",
            "    required = slot.get('required_credits')",
            "    if billing is None or live is None or required is None:",
            "        continue",
            "    billing_value = _to_float(billing)",
            "    live_value = _to_float(live)",
            "    required_value = _to_float(required)",
            "    if billing_value is None or live_value is None or required_value is None:",
            "        continue",
            "    if billing_value < 10000 or required_value <= live_value:",
            "        continue",
            "    billing_live_mismatch_slots.append({",
            "        'account_name': str(slot.get('account_name') or ''),",
            "        'slot_env_name': str(slot.get('slot_env_name') or ''),",
            "        'state': str(slot.get('state') or ''),",
            "        'billing_remaining_credits': billing,",
            "        'remaining_credits': live,",
            "        'required_credits': required,",
            "        'estimated_credit_basis': str(slot.get('estimated_credit_basis') or ''),",
            "        'last_probe_result': str(slot.get('last_probe_result') or ''),",
            "        'last_billing_snapshot_at': str(slot.get('last_billing_snapshot_at') or ''),",
            "        'last_success_at': slot.get('last_success_at'),",
            "        'upstream_reset_unknown': bool(slot.get('upstream_reset_unknown')),",
            "    })",
            "billing_live_mismatch_slots = sorted(",
            "    billing_live_mismatch_slots,",
            "    key=lambda item: (-(_to_float(item.get('billing_remaining_credits')) or 0.0), str(item.get('slot_env_name') or '')),",
            ")[:8]",
            "out = {",
            "    'fetched_at': root.get('fetched_at') or payload.get('cached_at') or '',",
            "    'source_url': payload.get('source_url') or '',",
            "    'configured_slots': onemin.get('configured_slots'),",
            "    'ready_slots': counts.get('ready', 0),",
            "    'degraded_slots': counts.get('degraded', 0),",
            "    'quarantine_slots': counts.get('quarantine', 0),",
            "    'unavailable_slots': counts.get('unavailable', 0),",
            "    'unknown_slots': counts.get('unknown', 0),",
            "    'balance_basis_summary': onemin.get('balance_basis_summary'),",
            "    'last_actual_balance_at': onemin.get('last_actual_balance_at'),",
            "    'max_credits_total': onemin.get('max_credits_total'),",
            "    'remaining_percent_of_max': onemin.get('remaining_percent_of_max'),",
            "    'estimated_remaining_credits_total': onemin.get('estimated_remaining_credits_total'),",
            "    'reason': str(onemin.get('reason') or ''),",
            "    'blocked_slots': blocked,",
            "    'billing_live_mismatch_slots': billing_live_mismatch_slots,",
            "}",
            "print(json.dumps(out, ensure_ascii=True, separators=(',', ':')))",
        ]
    )
    return f"python3 -c {shlex.quote(script)} {shlex.quote(path_text)}"


def build_tool_shim_operator_unblock_provider_health_command(
    *,
    tool_shim_direct_compact_provider_health_command: Callable[[str], str],
) -> Callable[[], str]:
    def tool_shim_operator_unblock_provider_health_command() -> str:
        return tool_shim_direct_compact_provider_health_command(
            "/docker/fleet/state/chummer_design_supervisor/ea_provider_health_cache.json"
        )

    tool_shim_operator_unblock_provider_health_command.__name__ = "tool_shim_operator_unblock_provider_health_command"
    tool_shim_operator_unblock_provider_health_command.__qualname__ = "tool_shim_operator_unblock_provider_health_command"
    return tool_shim_operator_unblock_provider_health_command


def tool_shim_operator_unblock_live_routing_hotspots_command() -> str:
    return (
        "sed -n '293,355p;680,780p' /docker/EA/ea/app/services/onemin_manager.py"
        " ; "
        "sed -n '2004,2048p;2816,2898p;2935,2978p;5541,5658p' /docker/EA/ea/app/services/responses_upstream.py"
    )


def build_tool_shim_telemetry_followup_commands(
    *,
    tool_shim_is_operator_fleet_unblock_context: Callable[[str, list[dict[str, object]]], bool],
    tool_shim_looks_like_shell_command: Callable[[str], bool],
    tool_shim_operator_unblock_scope_rejection_reason: Callable[..., str | None],
    tool_shim_operator_unblock_repo_diff_command: Callable[[], str | None],
    tool_shim_rewrite_operator_unblock_command: Callable[[str], str],
    tool_shim_is_safe_worker_followup_command: Callable[[str], bool],
    tool_shim_is_allowed_package_followup_command: Callable[[str, str], bool],
    tool_shim_resolve_equivalent_shard_runtime_path: Callable[[str], str],
    tool_shim_direct_file_read_command: Callable[..., str],
) -> Callable[..., list[str]]:
    def tool_shim_telemetry_followup_commands(
        *,
        latest_user_text: str,
        history_items: list[dict[str, object]],
        payload: dict[str, object],
    ) -> list[str]:
        commands: list[str] = []
        operator_unblock_context = tool_shim_is_operator_fleet_unblock_context(
            latest_user_text,
            history_items,
        )
        allowed_operator_followup_paths = {
            "/docker/fleet/WORKLIST.md",
            "/docker/fleet/README.md",
        }

        def _append_command(candidate: str) -> None:
            normalized = str(candidate or "").strip()
            if not normalized or normalized in commands:
                return
            if not tool_shim_looks_like_shell_command(normalized):
                return
            if (
                tool_shim_operator_unblock_scope_rejection_reason(
                    latest_user_text=latest_user_text,
                    cmd=normalized,
                    history_items=history_items,
                )
                is not None
            ):
                return
            commands.append(normalized)

        operator_repo_diff_command = None
        if operator_unblock_context:
            operator_repo_diff_command = tool_shim_operator_unblock_repo_diff_command()
        if operator_repo_diff_command:
            _append_command(operator_repo_diff_command)
            return commands

        raw_first_commands = payload.get("first_commands")
        if isinstance(raw_first_commands, list):
            for raw_command in raw_first_commands:
                rewritten_command = tool_shim_rewrite_operator_unblock_command(str(raw_command or "").strip())
                if not tool_shim_is_safe_worker_followup_command(
                    rewritten_command
                ) and not tool_shim_is_allowed_package_followup_command(
                    latest_user_text,
                    rewritten_command,
                ):
                    continue
                if rewritten_command not in commands:
                    commands.append(rewritten_command)
        if commands:
            return commands

        raw_source_paths = payload.get("source_paths")
        if isinstance(raw_source_paths, list):
            for raw_path in raw_source_paths:
                path_text = tool_shim_resolve_equivalent_shard_runtime_path(str(raw_path or "").strip())
                if not path_text.startswith("/") or "..." in path_text:
                    continue
                if operator_unblock_context and path_text not in allowed_operator_followup_paths:
                    continue
                if not os.path.exists(path_text) or not os.path.isfile(path_text):
                    continue
                candidate_command = tool_shim_direct_file_read_command(
                    path_text,
                    prefer_cat=path_text.lower().endswith(".json"),
                )
                if operator_unblock_context:
                    _append_command(candidate_command)
                    continue
                if tool_shim_is_safe_worker_followup_command(candidate_command) and candidate_command not in commands:
                    commands.append(candidate_command)

        return commands

    tool_shim_telemetry_followup_commands.__name__ = "tool_shim_telemetry_followup_commands"
    tool_shim_telemetry_followup_commands.__qualname__ = "tool_shim_telemetry_followup_commands"
    return tool_shim_telemetry_followup_commands


def build_tool_shim_recent_nested_telemetry_commands(
    *,
    tool_shim_is_operator_fleet_unblock_context: Callable[[str, list[dict[str, object]]], bool],
    tool_shim_history_has_fleet_shard_runtime_context: Callable[[list[dict[str, object]]], bool],
    tool_shim_exec_command_output_history: Callable[[list[dict[str, object]]], list[dict[str, str]]],
    extract_json_object: Callable[[str], object],
    tool_shim_telemetry_followup_commands: Callable[..., list[str]],
) -> Callable[[str, list[dict[str, object]]], list[str]]:
    def tool_shim_recent_nested_telemetry_commands(
        latest_user_text: str,
        history_items: list[dict[str, object]],
    ) -> list[str]:
        if not (
            tool_shim_is_operator_fleet_unblock_context(latest_user_text, history_items)
            or tool_shim_history_has_fleet_shard_runtime_context(history_items)
        ):
            return []
        for record in reversed(tool_shim_exec_command_output_history(history_items)):
            command = str(record.get("cmd") or "").strip()
            output_text = str(record.get("output") or "").strip()
            if (
                "TASK_LOCAL_TELEMETRY.generated.json" not in command
                and "\"first_commands\"" not in output_text
                and "\"source_paths\"" not in output_text
            ):
                continue
            payload = extract_json_object(output_text)
            if not isinstance(payload, dict):
                continue
            commands = tool_shim_telemetry_followup_commands(
                latest_user_text=latest_user_text,
                history_items=history_items,
                payload=payload,
            )
            if commands:
                return commands
        return []

    tool_shim_recent_nested_telemetry_commands.__name__ = "tool_shim_recent_nested_telemetry_commands"
    tool_shim_recent_nested_telemetry_commands.__qualname__ = "tool_shim_recent_nested_telemetry_commands"
    return tool_shim_recent_nested_telemetry_commands


def build_tool_shim_direct_nested_telemetry_first_command(
    *,
    tool_shim_recent_nested_telemetry_commands: Callable[[str, list[dict[str, object]]], list[str]],
    tool_shim_command_identity: Callable[[str], str],
    tool_shim_exec_command_history: Callable[[list[dict[str, object]]], list[str]],
) -> Callable[[str, list[dict[str, object]]], str | None]:
    def tool_shim_direct_nested_telemetry_first_command(
        latest_user_text: str,
        history_items: list[dict[str, object]],
    ) -> str | None:
        commands = tool_shim_recent_nested_telemetry_commands(latest_user_text, history_items)
        if not commands:
            return None
        executed_commands = {tool_shim_command_identity(command) for command in tool_shim_exec_command_history(history_items)}
        for command in commands:
            if tool_shim_command_identity(command) not in executed_commands:
                return command
        return None

    tool_shim_direct_nested_telemetry_first_command.__name__ = "tool_shim_direct_nested_telemetry_first_command"
    tool_shim_direct_nested_telemetry_first_command.__qualname__ = "tool_shim_direct_nested_telemetry_first_command"
    return tool_shim_direct_nested_telemetry_first_command
