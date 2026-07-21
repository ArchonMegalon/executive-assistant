#!/usr/bin/env python3
"""Keep recoverable host workloads from making the EA VM unschedulable."""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path


MIB = 1024 * 1024
GIB = 1024 * MIB
CGROUP_ROOT = Path("/sys/fs/cgroup")
STATE_PATH = Path("/run/host-resource-guard/state.json")
ACTION_COOLDOWN_SECONDS = 60
VSCODE_TERM_RSS_KIB = 4 * GIB // 1024
VSCODE_KILL_RSS_KIB = 5 * GIB // 1024

PROFILES = {
    # The July 10 incident involved a VS Code extension host reaching roughly
    # 12 GiB resident plus 9 GiB swap. Normal use is well below 1 GiB.
    "host-vscode-guard": {
        "memory.high": 4 * GIB,
        "memory.max": 6 * GIB,
        "memory.swap.max": 1 * GIB,
        "memory.oom.group": 0,
        "pids.max": 512,
    },
    # Bound aggregate automation without killing the interactive login slice.
    "host-codex-fleet-lowprio": {
        "memory.high": 8 * GIB,
        "memory.max": 12 * GIB,
        "memory.swap.max": 2 * GIB,
        "memory.oom.group": 0,
        "pids.max": 2048,
    },
    "host-background-lowprio": {
        "memory.high": 6 * GIB,
        "memory.max": 10 * GIB,
        "memory.swap.max": 2 * GIB,
        "memory.oom.group": 0,
        "pids.max": 4096,
    },
}


@dataclass(frozen=True)
class Snapshot:
    mem_available: int
    swap_total: int
    swap_free: int
    memory_some_avg10: float
    memory_full_avg10: float
    io_full_avg10: float
    load1: float
    blocked: int
    cpus: int

    @property
    def swap_used_pct(self) -> float:
        if self.swap_total <= 0:
            return 0.0
        return 100.0 * (self.swap_total - self.swap_free) / self.swap_total


@dataclass(frozen=True)
class ProcessRow:
    pid: int
    ppid: int
    rss_kib: int
    comm: str
    args: str


def pressure_level(snapshot: Snapshot) -> str:
    if (
        snapshot.mem_available < 768 * MIB
        or (
            snapshot.swap_used_pct >= 98
            and (snapshot.memory_some_avg10 >= 5 or snapshot.io_full_avg10 >= 25)
        )
        or (snapshot.blocked >= 48 and snapshot.load1 >= snapshot.cpus * 16)
    ):
        return "emergency"
    if (
        (
            snapshot.mem_available < 1536 * MIB
            and (
                snapshot.swap_used_pct >= 85
                or snapshot.memory_some_avg10 >= 2
                or snapshot.io_full_avg10 >= 15
            )
        )
        or (
            snapshot.swap_used_pct >= 95
            and (snapshot.memory_some_avg10 >= 5 or snapshot.io_full_avg10 >= 20)
        )
        or (snapshot.blocked >= 24 and snapshot.load1 >= snapshot.cpus * 8)
    ):
        return "critical"
    if (
        snapshot.mem_available < 3 * GIB
        or snapshot.swap_used_pct >= 80
        or snapshot.memory_some_avg10 >= 10
        or (
            snapshot.io_full_avg10 >= 20
            and (snapshot.swap_used_pct >= 60 or snapshot.mem_available < 5 * GIB)
        )
    ):
        return "warning"
    return "normal"


def pressure_reasons(snapshot: Snapshot) -> list[str]:
    reasons: list[str] = []
    if snapshot.mem_available < 3 * GIB:
        reasons.append(f"mem_available_mib={snapshot.mem_available // MIB}")
    if snapshot.swap_used_pct >= 80:
        reasons.append(f"swap_used_pct={snapshot.swap_used_pct:.2f}")
    if snapshot.memory_some_avg10 >= 10:
        reasons.append(f"memory_psi_some_avg10={snapshot.memory_some_avg10:.2f}")
    if snapshot.io_full_avg10 >= 20:
        reasons.append(f"io_psi_full_avg10={snapshot.io_full_avg10:.2f}")
    if snapshot.blocked >= 24:
        reasons.append(f"blocked={snapshot.blocked}")
    return reasons


def _meminfo() -> dict[str, int]:
    values: dict[str, int] = {}
    for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
        key, raw = line.split(":", 1)
        token = raw.strip().split()[0]
        values[key] = int(token) * 1024
    return values


def _psi(resource: str) -> dict[str, float]:
    values: dict[str, float] = {}
    for line in Path(f"/proc/pressure/{resource}").read_text(encoding="utf-8").splitlines():
        parts = line.split()
        prefix = parts[0]
        for item in parts[1:]:
            key, value = item.split("=", 1)
            if key.startswith("avg"):
                values[f"{prefix}_{key}"] = float(value)
    return values


def snapshot() -> Snapshot:
    memory = _meminfo()
    memory_psi = _psi("memory")
    io_psi = _psi("io")
    blocked = 0
    for line in Path("/proc/stat").read_text(encoding="utf-8").splitlines():
        if line.startswith("procs_blocked "):
            blocked = int(line.split()[1])
            break
    load1 = float(Path("/proc/loadavg").read_text(encoding="utf-8").split()[0])
    return Snapshot(
        mem_available=memory.get("MemAvailable", 0),
        swap_total=memory.get("SwapTotal", 0),
        swap_free=memory.get("SwapFree", 0),
        memory_some_avg10=memory_psi.get("some_avg10", 0.0),
        memory_full_avg10=memory_psi.get("full_avg10", 0.0),
        io_full_avg10=io_psi.get("full_avg10", 0.0),
        load1=load1,
        blocked=blocked,
        cpus=max(1, os.cpu_count() or 1),
    )


def _process_rows() -> list[ProcessRow]:
    result = subprocess.run(
        ["ps", "-eo", "pid=,ppid=,rss=,comm=,args="],
        check=False,
        capture_output=True,
        text=True,
    )
    rows: list[ProcessRow] = []
    for line in result.stdout.splitlines():
        parts = line.strip().split(None, 4)
        if len(parts) != 5:
            continue
        try:
            rows.append(ProcessRow(int(parts[0]), int(parts[1]), int(parts[2]), parts[3], parts[4]))
        except ValueError:
            continue
    return rows


def _descendants(roots: set[int], rows: list[ProcessRow]) -> set[int]:
    children: dict[int, list[int]] = {}
    for row in rows:
        children.setdefault(row.ppid, []).append(row.pid)
    result: set[int] = set()
    pending = list(roots)
    while pending:
        pid = pending.pop()
        if pid in result:
            continue
        result.add(pid)
        pending.extend(children.get(pid, ()))
    return result


def vscode_processes(rows: list[ProcessRow]) -> tuple[set[int], list[ProcessRow]]:
    extension_roots: list[ProcessRow] = []
    file_watcher_roots: set[int] = set()
    for row in rows:
        args = row.args.lower()
        if ".vscode-server/" not in args or "/out/bootstrap-fork" not in args:
            continue
        if "--type=extensionhost" in args:
            extension_roots.append(row)
        elif "--type=filewatcher" in args:
            file_watcher_roots.add(row.pid)
    extension_tree = _descendants({row.pid for row in extension_roots}, rows)
    return extension_tree | file_watcher_roots, extension_roots


def vscode_runaway_signal(roots: list[ProcessRow]) -> signal.Signals | None:
    largest_rss = max((row.rss_kib for row in roots), default=0)
    if largest_rss >= VSCODE_KILL_RSS_KIB:
        return signal.SIGKILL
    if largest_rss >= VSCODE_TERM_RSS_KIB:
        return signal.SIGTERM
    return None


def _write(path: Path, value: int | str, *, dry_run: bool) -> bool:
    if dry_run:
        return True
    try:
        path.write_text(f"{value}\n", encoding="utf-8")
        return True
    except OSError as exc:
        print(f"host-resource-guard write_failed path={path} error={exc}")
        return False


def _ensure_controllers(*, dry_run: bool) -> None:
    path = CGROUP_ROOT / "cgroup.subtree_control"
    for controller in ("+memory", "+pids"):
        _write(path, controller, dry_run=dry_run)


def apply_profiles(rows: list[ProcessRow], *, dry_run: bool) -> tuple[set[int], list[ProcessRow]]:
    _ensure_controllers(dry_run=dry_run)
    for name, limits in PROFILES.items():
        group = CGROUP_ROOT / name
        if not dry_run:
            group.mkdir(exist_ok=True)
        for setting, value in limits.items():
            _write(group / setting, value, dry_run=dry_run)

    vscode_pids, extension_roots = vscode_processes(rows)
    target = CGROUP_ROOT / "host-vscode-guard" / "cgroup.procs"
    for pid in sorted(vscode_pids):
        if Path(f"/proc/{pid}").exists():
            _write(target, pid, dry_run=dry_run)
    return vscode_pids, extension_roots


def _reclaim(bytes_to_reclaim: int, *, dry_run: bool) -> None:
    for name in PROFILES:
        path = CGROUP_ROOT / name / "memory.reclaim"
        if path.exists() or dry_run:
            _write(path, bytes_to_reclaim, dry_run=dry_run)


def _read_cgroup_value(path: Path) -> int | str | None:
    try:
        raw = path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if raw == "max":
        return raw
    try:
        return int(raw)
    except ValueError:
        return raw


def _read_cgroup_events(group: Path) -> dict[str, int]:
    events: dict[str, int] = {}
    path = group / "memory.events.local"
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return events
    for line in lines:
        key, value = line.split(None, 1)
        events[key] = int(value)
    return events


def cgroup_status() -> dict[str, dict[str, object]]:
    status: dict[str, dict[str, object]] = {}
    for name in PROFILES:
        group = CGROUP_ROOT / name
        status[name] = {
            "memory_current": _read_cgroup_value(group / "memory.current"),
            "memory_peak": _read_cgroup_value(group / "memory.peak"),
            "memory_high": _read_cgroup_value(group / "memory.high"),
            "memory_max": _read_cgroup_value(group / "memory.max"),
            "memory_swap_current": _read_cgroup_value(group / "memory.swap.current"),
            "memory_swap_max": _read_cgroup_value(group / "memory.swap.max"),
            "pids_current": _read_cgroup_value(group / "pids.current"),
            "pids_max": _read_cgroup_value(group / "pids.max"),
            "events": _read_cgroup_events(group),
        }
    return status


def cgroup_event_deltas(
    current: dict[str, dict[str, int]], previous: dict[str, object]
) -> dict[str, dict[str, int]]:
    deltas: dict[str, dict[str, int]] = {}
    for group, events in current.items():
        old_events = previous.get(group, {})
        if not isinstance(old_events, dict):
            old_events = {}
        changed = {
            key: value - int(old_events.get(key, 0))
            for key, value in events.items()
            if value > int(old_events.get(key, 0))
        }
        if changed:
            deltas[group] = changed
    return deltas


def _signal_largest(
    roots: list[ProcessRow], minimum_rss_kib: int, sig: signal.Signals, *, dry_run: bool
) -> bool:
    candidates = [row for row in roots if row.rss_kib >= minimum_rss_kib]
    if not candidates:
        return False
    offender = max(candidates, key=lambda row: row.rss_kib)
    print(
        "host-resource-guard shedding=vscode-extension-host "
        f"pid={offender.pid} rss_mib={offender.rss_kib // 1024} signal={sig.name}"
    )
    if not dry_run:
        try:
            os.kill(offender.pid, sig)
        except ProcessLookupError:
            pass
    return True


def _load_state() -> dict[str, object]:
    try:
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {}


def _save_state(state: dict[str, object], *, dry_run: bool) -> None:
    if dry_run:
        return
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary = STATE_PATH.with_suffix(".tmp")
    temporary.write_text(json.dumps(state, sort_keys=True), encoding="utf-8")
    os.replace(temporary, STATE_PATH)


def _self_test() -> None:
    base = dict(
        mem_available=12 * GIB,
        swap_total=24 * GIB,
        swap_free=24 * GIB,
        memory_some_avg10=0.0,
        memory_full_avg10=0.0,
        io_full_avg10=0.0,
        load1=1.0,
        blocked=0,
        cpus=12,
    )
    assert pressure_level(Snapshot(**base)) == "normal"
    assert pressure_level(Snapshot(**{**base, "mem_available": 2 * GIB})) == "warning"
    assert pressure_level(
        Snapshot(**{**base, "mem_available": GIB, "swap_free": GIB, "memory_some_avg10": 4.0})
    ) == "critical"
    assert pressure_level(Snapshot(**{**base, "mem_available": 512 * MIB})) == "emergency"
    print("host-resource-guard self-test: ok")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        _self_test()
        return 0
    if not args.dry_run and not args.status and os.geteuid() != 0:
        parser.error("must run as root unless --dry-run is used")

    rows = _process_rows()
    if args.status:
        vscode_pids, extension_roots = vscode_processes(rows)
    else:
        vscode_pids, extension_roots = apply_profiles(rows, dry_run=args.dry_run)
    current = snapshot()
    level = pressure_level(current)
    state = _load_state()
    previous = str(state.get("level") or "unknown")
    streak = int(state.get("streak") or 0) + 1 if previous == level else 1
    now = int(time.time())
    last_action = int(state.get("last_action_epoch") or 0)
    action_allowed = now - last_action >= ACTION_COOLDOWN_SECONDS
    groups = cgroup_status()
    events_now = {
        name: dict(data.get("events") or {})
        for name, data in groups.items()
        if isinstance(data.get("events"), dict)
    }
    previous_events = state.get("cgroup_events")
    if not isinstance(previous_events, dict):
        previous_events = {}
    event_deltas = cgroup_event_deltas(events_now, previous_events)
    for group, deltas in event_deltas.items():
        if any(key in deltas for key in ("high", "max", "oom", "oom_kill", "oom_group_kill")):
            print(
                "host-resource-guard cgroup_event "
                f"group={group} deltas={json.dumps(deltas, sort_keys=True)}"
            )

    report = {
        "status": level,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "next_action": {
            "normal": "continue_monitoring",
            "warning": "reclaim_after_three_consecutive_samples",
            "critical": "terminate_runaway_vscode_and_reclaim",
            "emergency": "kill_runaway_vscode_and_reclaim",
        }[level],
        "blocking_reason": ";".join(pressure_reasons(current)),
        "progress": {"consecutive_samples": streak},
        "source": "live:/proc/meminfo+/proc/pressure+cgroup-v2",
        "snapshot": {**asdict(current), "swap_used_pct": round(current.swap_used_pct, 2)},
        "cgroups": groups,
        "vscode_pids": sorted(vscode_pids),
        "vscode_extension_rss_mib": [row.rss_kib // 1024 for row in extension_roots],
    }

    if args.status:
        print(json.dumps(report, indent=2, sort_keys=True))
        return 0

    if args.verbose or args.dry_run or previous != level:
        print(f"host-resource-guard snapshot={json.dumps(report, sort_keys=True)}")

    acted = False
    runaway_signal = vscode_runaway_signal(extension_roots)
    if action_allowed and runaway_signal is not None:
        minimum = VSCODE_KILL_RSS_KIB if runaway_signal == signal.SIGKILL else VSCODE_TERM_RSS_KIB
        acted = _signal_largest(extension_roots, minimum, runaway_signal, dry_run=args.dry_run)
    elif action_allowed and level == "emergency":
        acted = _signal_largest(extension_roots, 256 * 1024, signal.SIGKILL, dry_run=args.dry_run)
        _reclaim(GIB, dry_run=args.dry_run)
        acted = True
    elif action_allowed and level == "critical" and streak >= 2:
        acted = _signal_largest(extension_roots, 1024 * 1024, signal.SIGTERM, dry_run=args.dry_run)
        _reclaim(512 * MIB, dry_run=args.dry_run)
        acted = True
    elif action_allowed and level == "warning" and streak >= 3:
        _reclaim(256 * MIB, dry_run=args.dry_run)
        acted = True

    _save_state(
        {
            **report,
            "level": level,
            "streak": streak,
            "last_observed_epoch": now,
            "last_action_epoch": now if acted else last_action,
            "cgroup_events": events_now,
        },
        dry_run=args.dry_run,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
