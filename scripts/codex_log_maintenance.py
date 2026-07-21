#!/usr/bin/env python3
"""Bound Codex's rebuildable SQLite log sink without touching thread state."""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import sqlite3
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path


MIB = 1024 * 1024
DEFAULT_MAX_BYTES = 256 * MIB
DEFAULT_RETAIN_ROWS = 50_000
DEFAULT_MAX_WAIT_SECONDS = 24 * 60 * 60
DEFAULT_POLL_SECONDS = 2.0
DEFAULT_STABLE_SAMPLES = 3
REQUIRED_LOG_COLUMNS = {
    "id",
    "ts",
    "ts_nanos",
    "level",
    "target",
    "feedback_log_body",
    "estimated_bytes",
}


@dataclass(frozen=True)
class MaintenanceResult:
    status: str
    rows_before: int
    rows_after: int
    bytes_before: int
    bytes_after: int
    checkpoint_busy: int


def database_bytes(path: Path) -> int:
    total = 0
    for candidate in (path, Path(f"{path}-wal"), Path(f"{path}-shm")):
        try:
            total += candidate.stat().st_size
        except FileNotFoundError:
            pass
    return total


def active_codex_pids(proc_root: Path = Path("/proc")) -> list[int]:
    pids: list[int] = []
    try:
        entries = proc_root.iterdir()
    except OSError:
        return pids
    for entry in entries:
        if not entry.name.isdigit():
            continue
        try:
            comm = (entry / "comm").read_text(encoding="utf-8").strip()
        except OSError:
            continue
        if comm == "codex":
            pids.append(int(entry.name))
    return sorted(pids)


def wait_for_idle(
    *,
    proc_root: Path,
    max_wait_seconds: float,
    poll_seconds: float,
    stable_samples: int,
) -> tuple[bool, list[int]]:
    deadline = time.monotonic() + max_wait_seconds
    stable = 0
    latest: list[int] = []
    while True:
        time.sleep(poll_seconds)
        latest = active_codex_pids(proc_root)
        stable = stable + 1 if not latest else 0
        if stable >= stable_samples:
            return True, []
        if time.monotonic() >= deadline:
            return False, latest


def _quick_check(connection: sqlite3.Connection) -> None:
    rows = [str(row[0]) for row in connection.execute("PRAGMA quick_check")]
    if rows != ["ok"]:
        raise RuntimeError(f"logs database integrity check failed: {rows!r}")


def _verify_logs_schema(connection: sqlite3.Connection) -> None:
    columns = {
        str(row[1]) for row in connection.execute("PRAGMA table_info(logs)")
    }
    missing = sorted(REQUIRED_LOG_COLUMNS - columns)
    if missing:
        raise RuntimeError(f"logs database schema is missing columns: {missing}")


def maintain_logs_database(
    path: Path,
    *,
    max_bytes: int = DEFAULT_MAX_BYTES,
    retain_rows: int = DEFAULT_RETAIN_ROWS,
) -> MaintenanceResult:
    if max_bytes <= 0:
        raise ValueError("max_bytes must be positive")
    if retain_rows <= 0:
        raise ValueError("retain_rows must be positive")

    bytes_before = database_bytes(path)
    if not path.exists() or bytes_before < max_bytes:
        return MaintenanceResult(
            status="below_threshold",
            rows_before=0,
            rows_after=0,
            bytes_before=bytes_before,
            bytes_after=bytes_before,
            checkpoint_busy=0,
        )

    connection = sqlite3.connect(path, timeout=60)
    try:
        connection.execute("PRAGMA busy_timeout = 60000")
        _quick_check(connection)
        _verify_logs_schema(connection)
        rows_before = int(connection.execute("SELECT COUNT(*) FROM logs").fetchone()[0])

        cutoff = connection.execute(
            "SELECT id FROM logs ORDER BY id DESC LIMIT 1 OFFSET ?",
            (retain_rows - 1,),
        ).fetchone()
        if cutoff is not None:
            connection.execute("BEGIN IMMEDIATE")
            try:
                connection.execute("DELETE FROM logs WHERE id < ?", (int(cutoff[0]),))
                connection.commit()
            except Exception:
                connection.rollback()
                raise

        checkpoint = connection.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
        checkpoint_busy = int(checkpoint[0]) if checkpoint is not None else 0
        if checkpoint_busy:
            raise RuntimeError(f"logs database checkpoint remained busy: {checkpoint!r}")

        if path.stat().st_size >= max_bytes:
            connection.execute("VACUUM")
        connection.execute("PRAGMA optimize")
        _quick_check(connection)
        rows_after = int(connection.execute("SELECT COUNT(*) FROM logs").fetchone()[0])
    finally:
        connection.close()

    return MaintenanceResult(
        status="maintained",
        rows_before=rows_before,
        rows_after=rows_after,
        bytes_before=bytes_before,
        bytes_after=database_bytes(path),
        checkpoint_busy=checkpoint_busy,
    )


def _append_event(codex_home: Path, event: dict[str, object]) -> None:
    log_dir = codex_home / "log"
    log_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    path = log_dir / "codex-log-maintenance.log"
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    with os.fdopen(descriptor, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, sort_keys=True) + "\n")


def _lock(handle: object, *, nonblocking: bool) -> bool:
    flags = fcntl.LOCK_EX | (fcntl.LOCK_NB if nonblocking else 0)
    try:
        fcntl.flock(handle.fileno(), flags)  # type: ignore[attr-defined]
    except BlockingIOError:
        return False
    return True


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--codex-home", type=Path, required=True)
    parser.add_argument("--max-bytes", type=int, default=DEFAULT_MAX_BYTES)
    parser.add_argument("--retain-rows", type=int, default=DEFAULT_RETAIN_ROWS)
    parser.add_argument("--max-wait-seconds", type=float, default=DEFAULT_MAX_WAIT_SECONDS)
    parser.add_argument("--poll-seconds", type=float, default=DEFAULT_POLL_SECONDS)
    parser.add_argument("--stable-samples", type=int, default=DEFAULT_STABLE_SAMPLES)
    parser.add_argument("--proc-root", type=Path, default=Path("/proc"))
    args = parser.parse_args()

    os.umask(0o077)
    if args.max_bytes <= 0 or args.retain_rows <= 0:
        parser.error("max-bytes and retain-rows must be positive")
    if args.max_wait_seconds < 0 or args.poll_seconds <= 0 or args.stable_samples <= 0:
        parser.error("wait and sampling values are invalid")

    codex_home = args.codex_home.expanduser().resolve()
    database = codex_home / "logs_2.sqlite"
    if database_bytes(database) < args.max_bytes:
        return 0

    codex_home.mkdir(mode=0o700, parents=True, exist_ok=True)
    event: dict[str, object] = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "database": "logs_2.sqlite",
    }
    lock_path = codex_home / ".logs-maintenance.lock"
    with lock_path.open("a+", encoding="utf-8") as maintenance_lock:
        if not _lock(maintenance_lock, nonblocking=True):
            return 0

        idle, active = wait_for_idle(
            proc_root=args.proc_root,
            max_wait_seconds=args.max_wait_seconds,
            poll_seconds=args.poll_seconds,
            stable_samples=args.stable_samples,
        )
        if not idle:
            _append_event(
                codex_home,
                {**event, "status": "idle_timeout", "active_codex_pids": active},
            )
            return 0

        startup_lock_path = codex_home / ".startup.lock"
        with startup_lock_path.open("a+", encoding="utf-8") as startup_lock:
            _lock(startup_lock, nonblocking=False)
            time.sleep(args.poll_seconds)
            active = active_codex_pids(args.proc_root)
            if active:
                _append_event(
                    codex_home,
                    {**event, "status": "launch_race_avoided", "active_codex_pids": active},
                )
                return 0
            try:
                result = maintain_logs_database(
                    database,
                    max_bytes=args.max_bytes,
                    retain_rows=args.retain_rows,
                )
            except Exception as exc:
                _append_event(
                    codex_home,
                    {**event, "status": "failed_closed", "error": str(exc)},
                )
                return 1

    _append_event(codex_home, {**event, **asdict(result)})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
