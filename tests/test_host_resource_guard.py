from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


MODULE_PATH = Path(__file__).parents[1] / "scripts" / "host_resource_guard.py"
SPEC = importlib.util.spec_from_file_location("host_resource_guard", MODULE_PATH)
assert SPEC and SPEC.loader
guard = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = guard
SPEC.loader.exec_module(guard)


def _snapshot(**overrides: object):
    values = {
        "mem_available": 12 * guard.GIB,
        "swap_total": 24 * guard.GIB,
        "swap_free": 24 * guard.GIB,
        "memory_some_avg10": 0.0,
        "memory_full_avg10": 0.0,
        "io_full_avg10": 0.0,
        "load1": 1.0,
        "blocked": 0,
        "cpus": 12,
    }
    values.update(overrides)
    return guard.Snapshot(**values)


def test_pressure_levels_are_progressive() -> None:
    assert guard.pressure_level(_snapshot()) == "normal"
    assert guard.pressure_level(_snapshot(mem_available=2 * guard.GIB)) == "warning"
    assert (
        guard.pressure_level(
            _snapshot(
                mem_available=guard.GIB,
                swap_free=guard.GIB,
                memory_some_avg10=4.0,
            )
        )
        == "critical"
    )
    assert guard.pressure_level(_snapshot(mem_available=512 * guard.MIB)) == "emergency"


def test_vscode_selection_excludes_pty_and_terminal_children() -> None:
    rows = [
        guard.ProcessRow(10, 1, 100, "MainThread", "/home/tibor/.vscode-server/bin/x/out/bootstrap-fork --type=extensionHost"),
        guard.ProcessRow(11, 10, 100, "vexp-core", "vexp-core mcp"),
        guard.ProcessRow(20, 1, 100, "MainThread", "/home/tibor/.vscode-server/bin/x/out/bootstrap-fork --type=ptyHost"),
        guard.ProcessRow(21, 20, 100, "bash", "/bin/bash"),
    ]
    selected, roots = guard.vscode_processes(rows)
    assert selected == {10, 11}
    assert [row.pid for row in roots] == [10]


def test_apply_profiles_assigns_entire_codex_tree(monkeypatch) -> None:
    rows = [
        guard.ProcessRow(100, 1, 100, "codex", "/opt/codex/bin/codex"),
        guard.ProcessRow(101, 100, 100, "node", "node mcp-server.js"),
        guard.ProcessRow(102, 1, 100, "python3", "python3 worker.py --label codex"),
    ]
    writes: list[tuple[Path, int | str, bool]] = []

    def record_write(path: Path, value: int | str, *, dry_run: bool) -> bool:
        writes.append((path, value, dry_run))
        return True

    monkeypatch.setattr(guard, "_write", record_write)
    guard.apply_profiles(rows, dry_run=True)

    target = guard.CGROUP_ROOT / "host-codex-fleet-lowprio" / "cgroup.procs"
    assert [(path, value) for path, value, _ in writes if path == target] == [
        (target, 100),
        (target, 101),
    ]


def test_vscode_runaway_cutoff_handles_preexisting_charges() -> None:
    normal = [guard.ProcessRow(10, 1, 512 * 1024, "MainThread", "extension host")]
    terminate = [guard.ProcessRow(10, 1, 4 * guard.GIB // 1024, "MainThread", "extension host")]
    kill = [guard.ProcessRow(10, 1, 5 * guard.GIB // 1024, "MainThread", "extension host")]
    assert guard.vscode_runaway_signal(normal) is None
    assert guard.vscode_runaway_signal(terminate) == guard.signal.SIGTERM
    assert guard.vscode_runaway_signal(kill) == guard.signal.SIGKILL


def test_cgroup_event_deltas_only_report_increases() -> None:
    current = {"guard": {"high": 4, "oom_kill": 1, "max": 0}}
    previous = {"guard": {"high": 2, "oom_kill": 1, "max": 0}}
    assert guard.cgroup_event_deltas(current, previous) == {"guard": {"high": 2}}
