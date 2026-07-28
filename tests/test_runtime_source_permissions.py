from __future__ import annotations

import os
from pathlib import Path
import stat
import subprocess

import pytest

from scripts import verify_ea_runtime_source_permissions as verifier
from scripts.memorial_bind_source_guard import BindSourceGuardError


ROOT = Path(__file__).resolve().parents[1]


def _runtime_tree(tmp_path: Path) -> tuple[Path, Path]:
    root = tmp_path / "release"
    source = root / "ea" / "app"
    source.mkdir(parents=True)
    scripts = root / "scripts"
    scripts.mkdir()
    module = source / "main.py"
    module.write_text("from __future__ import annotations\n", encoding="utf-8")
    launcher = scripts / "runtime_guard.sh"
    launcher.write_text("#!/usr/bin/env sh\n", encoding="utf-8")
    root.chmod(0o755)
    source.parent.chmod(0o755)
    source.chmod(0o755)
    scripts.chmod(0o755)
    module.chmod(0o644)
    launcher.chmod(0o755)
    return root, module


def test_runtime_source_tree_passes_without_reading_contents(tmp_path: Path) -> None:
    root, _module = _runtime_tree(tmp_path)

    receipt = verifier.verify_runtime_source_tree(root)

    assert receipt["status"] == "pass"
    assert receipt["runtime_user"] == "10001:10001"
    assert receipt["source_trees"] == ["ea/app", "scripts"]
    assert receipt["release_files_scanned"] == 2
    assert receipt["file_contents_read"] is False
    assert receipt["secrets_included"] is False


def test_runtime_source_tree_rejects_git_invisible_0600_drift(tmp_path: Path) -> None:
    root, module = _runtime_tree(tmp_path)
    module.chmod(0o600)

    with pytest.raises(BindSourceGuardError, match="bind_source_file_not_readable"):
        verifier.verify_runtime_source_tree(root)


def test_runtime_source_repair_normalizes_0600_without_making_source_writable(
    tmp_path: Path,
) -> None:
    root, module = _runtime_tree(tmp_path)
    module.chmod(0o600)

    repaired = verifier.repair_runtime_source_tree_permissions(root / "ea" / "app")
    receipt = verifier.verify_runtime_source_tree(root)

    assert repaired == 1
    assert stat.S_IMODE(module.stat().st_mode) == 0o644
    assert receipt["status"] == "pass"


def test_runtime_source_repair_covers_scripts_bind_mount(tmp_path: Path) -> None:
    root, _module = _runtime_tree(tmp_path)
    launcher = root / "scripts" / "runtime_guard.sh"
    launcher.chmod(0o700)

    repaired = verifier.repair_runtime_source_permissions(root)
    receipt = verifier.verify_runtime_source_tree(root)

    assert repaired == 1
    assert stat.S_IMODE(launcher.stat().st_mode) == 0o744
    assert receipt["status"] == "pass"


def test_runtime_source_repair_rejects_symlinked_source_root(tmp_path: Path) -> None:
    root, _module = _runtime_tree(tmp_path)
    linked_source = tmp_path / "linked-app"
    linked_source.symlink_to(root / "ea" / "app", target_is_directory=True)

    with pytest.raises(BindSourceGuardError, match="bind_source_symlink_forbidden"):
        verifier.repair_runtime_source_tree_permissions(linked_source)


def test_deploy_runs_runtime_source_permission_preflight() -> None:
    deploy = (ROOT / "scripts" / "deploy.sh").read_text(encoding="utf-8")

    assert "verify_ea_runtime_source_permissions.py" in deploy
    assert '--root "${APP_ROOT}" --repair' in deploy
    assert deploy.index("verify_ea_runtime_source_permissions.py") < deploy.index(
        "source_worktree_status="
    )


def test_codexea_exit_gate_targets_dedicated_runtime_base_url(tmp_path: Path) -> None:
    launcher = tmp_path / "codexea"
    marker = tmp_path / "runtime-base-urls"
    launcher.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        'printf "%s\\n" "${EA_MCP_BASE_URL:-missing}" >> "${CODEXEA_TEST_MARKER:?}"\n'
        'case "${1:-}" in\n'
        "  easy) printf 'READY\\n' ;;\n"
        "  core) printf 'TASK_OK:12\\n' ;;\n"
        "  *) exit 2 ;;\n"
        "esac\n",
        encoding="utf-8",
    )
    launcher.chmod(launcher.stat().st_mode | stat.S_IXUSR)

    env = {
        **os.environ,
        "CODEXEA_E2E_LAUNCHER": str(launcher),
        "CODEXEA_E2E_RUNTIME_BASE_URL": "http://127.0.0.1:19092",
        "CODEXEA_E2E_RUNTIME_READY_PROBE_COMMAND": "exit 0",
        "CODEXEA_TEST_MARKER": str(marker),
        "CODEXEA_E2E_EXIT_GATE_TIMEOUT_SECONDS": "60",
    }
    completed = subprocess.run(
        ["bash", str(ROOT / "scripts" / "verify_codexea_e2e_exit_gate.sh")],
        cwd=ROOT,
        env=env,
        check=False,
        capture_output=True,
        text=True,
        timeout=90,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert marker.read_text(encoding="utf-8").splitlines() == [
        "http://127.0.0.1:19092",
        "http://127.0.0.1:19092",
    ]
