from __future__ import annotations

import importlib.util
import sqlite3
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "codex_log_maintenance.py"
SPEC = importlib.util.spec_from_file_location("codex_log_maintenance", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def _logs_database(path: Path, rows: int = 12) -> None:
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts INTEGER NOT NULL,
            ts_nanos INTEGER NOT NULL,
            level TEXT NOT NULL,
            target TEXT NOT NULL,
            feedback_log_body TEXT,
            module_path TEXT,
            file TEXT,
            line INTEGER,
            thread_id TEXT,
            process_uuid TEXT,
            estimated_bytes INTEGER NOT NULL DEFAULT 0
        );
        """
    )
    connection.executemany(
        """
        INSERT INTO logs (
            ts, ts_nanos, level, target, feedback_log_body, estimated_bytes
        ) VALUES (?, 0, 'TRACE', 'test', ?, ?)
        """,
        [(index, "x" * 4096, 4096) for index in range(rows)],
    )
    connection.commit()
    connection.close()


def test_maintenance_retains_newest_rows_and_integrity(tmp_path: Path) -> None:
    database = tmp_path / "logs_2.sqlite"
    _logs_database(database)

    result = MODULE.maintain_logs_database(database, max_bytes=1, retain_rows=4)

    assert result.status == "maintained"
    assert result.rows_before == 12
    assert result.rows_after == 4
    connection = sqlite3.connect(database)
    try:
        assert connection.execute("SELECT id FROM logs ORDER BY id").fetchall() == [
            (9,),
            (10,),
            (11,),
            (12,),
        ]
        assert connection.execute("PRAGMA quick_check").fetchone() == ("ok",)
    finally:
        connection.close()


def test_maintenance_below_threshold_is_read_only(tmp_path: Path) -> None:
    database = tmp_path / "logs_2.sqlite"
    _logs_database(database, rows=2)
    before = database.read_bytes()

    result = MODULE.maintain_logs_database(
        database,
        max_bytes=len(before) + 1,
        retain_rows=1,
    )

    assert result.status == "below_threshold"
    assert database.read_bytes() == before


def test_maintenance_rejects_wrong_schema_without_mutation(tmp_path: Path) -> None:
    database = tmp_path / "logs_2.sqlite"
    connection = sqlite3.connect(database)
    connection.execute("CREATE TABLE logs (id INTEGER PRIMARY KEY)")
    connection.execute("INSERT INTO logs (id) VALUES (1)")
    connection.commit()
    connection.close()
    before = database.read_bytes()

    with pytest.raises(RuntimeError, match="missing columns"):
        MODULE.maintain_logs_database(database, max_bytes=1, retain_rows=1)

    assert database.read_bytes() == before


def test_active_codex_pid_detection_is_exact(tmp_path: Path) -> None:
    for pid, comm in (("101", "codex"), ("102", "node"), ("103", "codex-helper")):
        process = tmp_path / pid
        process.mkdir()
        (process / "comm").write_text(f"{comm}\n", encoding="utf-8")

    assert MODULE.active_codex_pids(tmp_path) == [101]
