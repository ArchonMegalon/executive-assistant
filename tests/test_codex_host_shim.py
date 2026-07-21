from __future__ import annotations

import os
import signal
import subprocess
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SHIM = ROOT / "scripts" / "codex_host_shim.sh"
THREAD_A = "11111111-1111-4111-8111-111111111111"
THREAD_B = "22222222-2222-4222-8222-222222222222"


def _fake_codex(tmp_path: Path) -> Path:
    path = tmp_path / "fake-codex"
    path.write_text(
        """#!/usr/bin/env bash
set -euo pipefail
sleep "${FAKE_CODEX_SLEEP_SECONDS:-0}"
if [ "${FAKE_CODEX_PRINT_PATH:-0}" = "1" ]; then
  printf 'PATH=%s\n' "$PATH"
fi
printf '%s\n' "$*"
""",
        encoding="utf-8",
    )
    path.chmod(0o755)
    return path


def _env(tmp_path: Path, fake_codex: Path, **overrides: str) -> dict[str, str]:
    env = {
        **os.environ,
        "CODEX_HOME": str(tmp_path / "codex-home"),
        "HOST_REAL_CODEX": str(fake_codex),
        "HOST_LOWPRIO_DISABLE": "1",
        "CODEX_STARTUP_GUARD_DISABLE": "1",
        "CODEX_STARTUP_STAGGER_SECONDS": "0",
    }
    env.update(overrides)
    return env


def _wait_until_locked(path: Path, process: subprocess.Popen[str]) -> None:
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        returncode = process.poll()
        if returncode is not None:
            stdout, stderr = process.communicate()
            raise AssertionError(
                f"shim exited before acquiring {path}: returncode={returncode} "
                f"stdout={stdout!r} stderr={stderr!r}"
            )
        if path.exists():
            probe = subprocess.run(
                ["flock", "-n", str(path), "true"],
                check=False,
                capture_output=True,
                text=True,
            )
            if probe.returncode != 0:
                return
        time.sleep(0.02)
    raise AssertionError(f"resume lock was not acquired: {path}")


def _terminate_process_group(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    os.killpg(process.pid, signal.SIGTERM)
    try:
        process.wait(timeout=3)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
        process.wait(timeout=3)


def test_shim_has_valid_shell_syntax() -> None:
    result = subprocess.run(["bash", "-n", str(SHIM)], check=False, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_distinct_thread_starts_while_another_thread_is_active(tmp_path: Path) -> None:
    fake = _fake_codex(tmp_path)
    first = subprocess.Popen(
        ["bash", str(SHIM), "-C", str(tmp_path), "resume", THREAD_A],
        env=_env(tmp_path, fake, FAKE_CODEX_SLEEP_SECONDS="5"),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    try:
        lock = tmp_path / "codex-home" / "resume-locks" / f"{THREAD_A}.lock"
        _wait_until_locked(lock, first)

        started = time.monotonic()
        second = subprocess.run(
            ["bash", str(SHIM), "resume", THREAD_B],
            env=_env(tmp_path, fake),
            check=False,
            capture_output=True,
            text=True,
            timeout=2,
        )
        elapsed = time.monotonic() - started

        assert second.returncode == 0, second.stderr
        assert THREAD_B in second.stdout
        assert elapsed < 1
    finally:
        _terminate_process_group(first)


def test_duplicate_thread_resume_fails_immediately(tmp_path: Path) -> None:
    fake = _fake_codex(tmp_path)
    first = subprocess.Popen(
        ["bash", str(SHIM), "resume", THREAD_A],
        env=_env(tmp_path, fake, FAKE_CODEX_SLEEP_SECONDS="5"),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    try:
        lock = tmp_path / "codex-home" / "resume-locks" / f"{THREAD_A}.lock"
        _wait_until_locked(lock, first)

        started = time.monotonic()
        duplicate = subprocess.run(
            ["bash", str(SHIM), "-C", str(tmp_path), "resume", THREAD_A],
            env=_env(tmp_path, fake),
            check=False,
            capture_output=True,
            text=True,
            timeout=2,
        )
        elapsed = time.monotonic() - started

        assert duplicate.returncode == 75
        assert "already active" in duplicate.stderr
        assert elapsed < 1
    finally:
        _terminate_process_group(first)


def test_shim_does_not_wait_for_global_sqlite_writers() -> None:
    text = SHIM.read_text(encoding="utf-8")
    assert "wait_for_codex_database_writer" not in text
    assert "SQLite writer did not clear" not in text
    assert 'CODEX_STARTUP_GUARD_WAIT_SECONDS:-300' in text
    assert 'HOST_LOWPRIO_NICE="${HOST_LOWPRIO_NICE:-5}"' in text
    assert 'HOST_LOWPRIO_IO_WEIGHT="${HOST_LOWPRIO_IO_WEIGHT:-100}"' in text
    assert 'HOST_LOWPRIO_CPU_QUOTA="${HOST_LOWPRIO_CPU_QUOTA:-200%}"' in text


def test_shim_deduplicates_inherited_path(tmp_path: Path) -> None:
    fake = _fake_codex(tmp_path)
    env = _env(
        tmp_path,
        fake,
        FAKE_CODEX_PRINT_PATH="1",
        PATH="/usr/bin:/one:/two:/one:/three:/two:/usr/bin",
    )
    result = subprocess.run(
        ["/bin/bash", str(SHIM), "--version"],
        env=env,
        check=False,
        capture_output=True,
        text=True,
        timeout=2,
    )

    assert result.returncode == 0, result.stderr
    assert "PATH=/usr/bin:/one:/two:/three" in result.stdout


def test_oversized_log_database_schedules_nonblocking_maintenance(tmp_path: Path) -> None:
    fake = _fake_codex(tmp_path)
    marker = tmp_path / "maintenance-called"
    maintainer = tmp_path / "fake-maintainer"
    maintainer.write_text(
        f"#!/usr/bin/env bash\nprintf '%s' \"$*\" > {marker!s}\n",
        encoding="utf-8",
    )
    maintainer.chmod(0o755)
    codex_home = tmp_path / "codex-home"
    codex_home.mkdir()
    (codex_home / "logs_2.sqlite").write_bytes(b"oversized")
    env = _env(
        tmp_path,
        fake,
        CODEX_LOG_MAINTAINER=str(maintainer),
        CODEX_LOG_MAINTENANCE_THRESHOLD_BYTES="1",
        CODEX_LOG_MAINTENANCE_NO_SYSTEMD="1",
    )

    started = time.monotonic()
    result = subprocess.run(
        ["bash", str(SHIM)],
        env=env,
        check=False,
        capture_output=True,
        text=True,
        timeout=2,
    )
    elapsed = time.monotonic() - started
    deadline = time.monotonic() + 2
    while not marker.exists() and time.monotonic() < deadline:
        time.sleep(0.02)

    assert result.returncode == 0, result.stderr
    assert elapsed < 1
    assert marker.exists()
    arguments = marker.read_text(encoding="utf-8")
    assert f"--codex-home {codex_home}" in arguments
    assert "--max-bytes 1" in arguments
