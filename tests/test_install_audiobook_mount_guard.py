from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
INSTALLER = ROOT / "scripts/install_audiobook_mount_guard.sh"
SERVICE = ROOT / "ops/systemd/ea-audiobook-mount-guard.service"


def test_installer_has_valid_bash_syntax_and_is_executable() -> None:
    subprocess.run(["bash", "-n", str(INSTALLER)], check=True)

    assert os.access(INSTALLER, os.X_OK)


def test_installer_refuses_non_root_execution() -> None:
    if os.geteuid() == 0:
        pytest.skip("non-root refusal requires a non-root test process")

    result = subprocess.run(
        [str(INSTALLER)],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 2
    assert "run this installer with sudo" in result.stderr


def test_installer_atomically_installs_and_verifies_guard_contract() -> None:
    source = INSTALLER.read_text(encoding="utf-8")

    assert 'mv -fT -- "${temporary}" "${destination}"' in source
    assert 'sha256sum "${guard_target}" >"${checksum_temporary}"' in source
    assert (
        'sha256sum --check --strict --status "${checksum_target}"'
        in source
    )
    assert "systemctl daemon-reload" in source
    assert "systemctl enable --now ea-audiobook-mount-guard.timer" in source
    assert "systemctl start ea-audiobook-mount-guard.service" in source
    assert '[[ "${service_result}" == "success" ]]' in source
    assert '[[ "${service_status}" == "0" ]]' in source
    assert '[[ "${memorial_status}" == "200" ]]' in source


def test_systemd_service_executes_only_the_verified_installed_copy() -> None:
    source = SERVICE.read_text(encoding="utf-8")

    assert (
        "ExecStartPre=/usr/bin/sha256sum --check --strict --status "
        "/etc/ea-audiobook-mount-guard.sha256"
    ) in source
    assert "ExecStart=/usr/local/libexec/ea-audiobook-mount-guard" in source
    assert "ExecStart=/docker/EA/" not in source
