from __future__ import annotations

import hashlib
import os
import stat
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
INSTALLER = ROOT / "scripts" / "install_codexea.sh"
SHIM_SOURCE = ROOT / "scripts" / "codexea"
ROUTE_SOURCE = ROOT / "scripts" / "codexea_route.py"


def _installer_env(home: Path, **overrides: str) -> dict[str, str]:
    env = {
        key: value
        for key, value in os.environ.items()
        if key != "CODEXEA_INSTALL_FAILPOINT"
    }
    env["HOME"] = str(home)
    env.update(overrides)
    return env


def _run_installer(
    home: Path,
    *args: str,
    check: bool = False,
    **overrides: str,
) -> subprocess.CompletedProcess[str]:
    home.mkdir(parents=True, exist_ok=True)
    return subprocess.run(
        [str(INSTALLER), *args],
        cwd=ROOT,
        env=_installer_env(home, **overrides),
        check=check,
        capture_output=True,
        text=True,
        timeout=30,
    )


def _install_root(home: Path) -> Path:
    return home / ".local" / "share" / "codexea"


def _release_id(shim_payload: bytes, route_payload: bytes) -> str:
    shim_digest = hashlib.sha256(shim_payload).hexdigest()
    route_digest = hashlib.sha256(route_payload).hexdigest()
    combined = f"{shim_digest}\n{route_digest}\n".encode()
    return hashlib.sha256(combined).hexdigest()


def _make_valid_release(home: Path, marker: str) -> str:
    shim_payload = SHIM_SOURCE.read_bytes() + f"\n# installer-test-{marker}\n".encode()
    route_payload = ROUTE_SOURCE.read_bytes() + f"\n# installer-test-{marker}\n".encode()
    release_id = _release_id(shim_payload, route_payload)
    scripts_dir = _install_root(home) / "releases" / release_id / "scripts"
    scripts_dir.mkdir(parents=True, exist_ok=False)
    shim_path = scripts_dir / "codexea"
    route_path = scripts_dir / "codexea_route.py"
    shim_path.write_bytes(shim_payload)
    route_path.write_bytes(route_payload)
    shim_path.chmod(0o755)
    route_path.chmod(0o755)
    return f"releases/{release_id}"


def _read_target(path: Path) -> str:
    assert path.is_symlink()
    return os.readlink(path)


def _assert_no_transaction_debris(home: Path) -> None:
    install_root = _install_root(home)
    assert not list(install_root.rglob(".staging.*"))
    assert not list(install_root.glob(".current-*"))
    assert not list(install_root.glob(".current.*"))
    assert not list(install_root.glob(".previous-*"))
    assert not list(install_root.glob(".previous.*"))
    assert not list(install_root.glob(".*-restore.*"))
    assert not list((home / ".local" / "bin").glob(".codexea-launcher.*"))


def test_concurrent_fresh_installs_are_serialized_and_leave_one_release(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()

    def install_once(_index: int) -> subprocess.CompletedProcess[str]:
        return _run_installer(home)

    with ThreadPoolExecutor(max_workers=12) as executor:
        completed = list(executor.map(install_once, range(12)))

    assert [result.returncode for result in completed] == [0] * 12
    install_root = _install_root(home)
    releases = [path for path in (install_root / "releases").iterdir() if path.is_dir()]
    assert len(releases) == 1
    assert _read_target(install_root / "current") == f"releases/{releases[0].name}"
    assert not (install_root / "previous").exists()
    _assert_no_transaction_debris(home)


def test_failed_upgrade_restores_current_and_removes_new_release(tmp_path: Path) -> None:
    home = tmp_path / "home"
    install_root = _install_root(home)
    (install_root / "releases").mkdir(parents=True)
    previous_target = _make_valid_release(home, "failed-upgrade-base")
    (install_root / "current").symlink_to(previous_target)

    completed = _run_installer(
        home,
        CODEXEA_INSTALL_FAILPOINT="after_current_switch",
    )

    assert completed.returncode == 97
    assert _read_target(install_root / "current") == previous_target
    assert sorted(path.name for path in (install_root / "releases").iterdir()) == [
        previous_target.removeprefix("releases/")
    ]
    _assert_no_transaction_debris(home)


@pytest.mark.parametrize(
    ("failpoint", "expected_returncode"),
    (
        ("rollback_after_current_switch", 98),
        ("rollback_after_previous_switch", 99),
    ),
)
def test_rollback_failure_restores_both_pointer_authorities(
    tmp_path: Path,
    failpoint: str,
    expected_returncode: int,
) -> None:
    home = tmp_path / failpoint
    installed = _run_installer(home, check=True)
    assert installed.returncode == 0
    install_root = _install_root(home)
    current = install_root / "current"
    previous = install_root / "previous"
    current_target = _read_target(current)
    previous_target = _make_valid_release(home, failpoint)
    previous.symlink_to(previous_target)

    failed = _run_installer(
        home,
        "--rollback",
        CODEXEA_INSTALL_FAILPOINT=failpoint,
    )

    assert failed.returncode == expected_returncode
    assert _read_target(current) == current_target
    assert _read_target(previous) == previous_target
    _assert_no_transaction_debris(home)

    completed = _run_installer(home, "--rollback", check=True)
    assert completed.returncode == 0
    assert _read_target(current) == previous_target
    assert _read_target(previous) == current_target
    _assert_no_transaction_debris(home)


@pytest.mark.parametrize("broken_kind", ("missing_route", "wrong_digest"))
def test_rollback_rejects_incomplete_or_unbound_previous_release(
    tmp_path: Path,
    broken_kind: str,
) -> None:
    home = tmp_path / broken_kind
    _run_installer(home, check=True)
    install_root = _install_root(home)
    current = install_root / "current"
    current_target = _read_target(current)
    broken_id = "f" * 64
    scripts_dir = install_root / "releases" / broken_id / "scripts"
    scripts_dir.mkdir(parents=True)
    shim_path = scripts_dir / "codexea"
    shim_path.write_bytes(SHIM_SOURCE.read_bytes())
    shim_path.chmod(shim_path.stat().st_mode | stat.S_IXUSR)
    if broken_kind == "wrong_digest":
        route_path = scripts_dir / "codexea_route.py"
        route_path.write_bytes(ROUTE_SOURCE.read_bytes())
        route_path.chmod(route_path.stat().st_mode | stat.S_IXUSR)
    previous = install_root / "previous"
    previous.symlink_to(f"releases/{broken_id}")

    completed = _run_installer(home, "--rollback")

    assert completed.returncode == 1
    assert "incomplete or fails its content digest" in completed.stderr
    assert _read_target(current) == current_target
    assert _read_target(previous) == f"releases/{broken_id}"
    _assert_no_transaction_debris(home)


def test_noop_reinstall_retains_valid_previous_release(tmp_path: Path) -> None:
    home = tmp_path / "home"
    install_root = _install_root(home)
    (install_root / "releases").mkdir(parents=True)
    previous_target = _make_valid_release(home, "retained-rollback")
    (install_root / "current").symlink_to(previous_target)

    upgraded = _run_installer(home, check=True)
    assert upgraded.returncode == 0
    current_target = _read_target(install_root / "current")
    assert current_target != previous_target
    assert _read_target(install_root / "previous") == previous_target

    completed = _run_installer(home, check=True)

    assert completed.returncode == 0
    assert _read_target(install_root / "current") == current_target
    assert _read_target(install_root / "previous") == previous_target
    assert sorted(path.name for path in (install_root / "releases").iterdir()) == sorted(
        (current_target.removeprefix("releases/"), previous_target.removeprefix("releases/"))
    )
    _assert_no_transaction_debris(home)
