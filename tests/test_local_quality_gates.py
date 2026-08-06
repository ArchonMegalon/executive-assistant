from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]


def _load_script(name: str):
    path = ROOT / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _load_script_with_env(name: str, monkeypatch, **env_values: str):
    for key, value in env_values.items():
        monkeypatch.setenv(key, value)
    return _load_script(name)


def test_quality_requirements_are_pinned() -> None:
    path = ROOT / "requirements-dev-quality.txt"
    lines = [
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]

    assert lines
    assert all("==" in line for line in lines)
    assert not any(">=" in line or "<=" in line or "~=" in line for line in lines)


def test_local_quality_gate_contract_passes() -> None:
    module = _load_script("verify_local_quality_gates")

    result = module.verify()

    assert result["contract_name"] == "ea.local_quality_gates.v1"
    assert result["status"] == "pass"
    assert result["issues"] == []
    details = dict(result["details"])
    assert details["quality_requirements"] == "requirements-dev-quality.txt"
    assert details["env_secret_guard"] == "scripts/verify_env_no_secrets.py"
    assert details["codexea_e2e_exit_gate"] == "scripts/verify_codexea_e2e_exit_gate.sh"
    assert details["codexea_fleet_shim_parity"] == "scripts/verify_codexea_fleet_shim_parity.py"
    assert details["codexea_e2e_exit_gate_timeout_seconds"] >= 1
    assert details["codexea_e2e_exit_gate_timeout_seconds_valid"] is True
    assert details["codexea_e2e_exit_gate_supervisor_grace_seconds"] >= 5
    assert details["codexea_e2e_exit_gate_supervisor_grace_seconds_valid"] is True
    assert details["pip_audit_requirements"] == ["ea/requirements.txt"]
    assert details["bandit_targets"] == [
        "ea/app/settings.py",
        "scripts/verify_release_manifest_runtime_mode.py",
        "scripts/verify_release_manifest_artifact_plane.py",
        "scripts/verify_release_authority.py",
        "scripts/verify_runtime_supply_chain.py",
        "scripts/verify_codexea_fleet_shim_parity.py",
        "scripts/verify_local_quality_gates.py",
    ]
    assert dict(details["codexea_e2e_exit_gate_result"])["status"] == "pass"
    assert dict(details["codexea_e2e_exit_gate_result"])["timed_out"] is False
    assert dict(details["codexea_fleet_shim_parity_result"])["status"] == "pass"
    assert dict(details["env_secret_guard_result"])["status"] == "pass"
    assert dict(details["ruff"])["status"] == "pass"
    assert dict(details["mypy"])["status"] == "pass"
    assert dict(details["bandit"])["status"] == "pass"
    assert dict(details["pip_audit"])["status"] == "pass"
    assert [dict(item)["requirements_path"] for item in list(dict(details["pip_audit"])["runs"])] == [
        "ea/requirements.txt",
    ]
    assert all(dict(item)["status"] == "pass" for item in list(dict(details["pip_audit"])["runs"]))


def test_makefile_wires_local_quality_gate() -> None:
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")

    assert "verify-local-quality-gates:" in makefile
    assert "$(PYTHON_BIN) scripts/verify_local_quality_gates.py" in makefile
    assert "verify-codexea-e2e-exit-gate:" in makefile
    assert "bash scripts/verify_codexea_e2e_exit_gate.sh" in makefile
    assert "verify-codexea-fleet-shim-parity:" in makefile
    assert "$(PYTHON_BIN) scripts/verify_codexea_fleet_shim_parity.py" in makefile
    assert "materialize-release-manifest:" in makefile
    assert "$(PYTHON_BIN) scripts/materialize_release_manifest.py" in makefile
    assert "materialize-release-authority-status:" in makefile
    materialize_status_body = makefile.split("materialize-release-authority-status:", 1)[1].split("\n\n", 1)[0]
    assert "materialize-release-manifest" in materialize_status_body
    assert "$(PYTHON_BIN) scripts/materialize_release_authority_status.py" in makefile
    assert "materialize-deploy-context:" in makefile
    assert "$(PYTHON_BIN) scripts/materialize_deploy_context.py --pretty" in makefile
    assert "refresh-deploy-context:" in makefile
    assert "$(PYTHON_BIN) scripts/materialize_deploy_context.py >/dev/null" in makefile
    assert "verify-deploy-context:" in makefile
    verify_deploy_context_body = makefile.split("verify-deploy-context:", 1)[1].split("\n\n", 1)[0]
    assert "refresh-deploy-context" in verify_deploy_context_body
    assert "$(PYTHON_BIN) scripts/verify_deploy_context.py --pretty" in makefile
    assert "verify-release-authority-runtime:" in makefile
    assert "refresh-release-authority-status:" in makefile
    assert "$(PYTHON_BIN) scripts/materialize_release_authority_status.py >/dev/null" in makefile
    verify_release_runtime_body = makefile.split("verify-release-authority-runtime:", 1)[1].split("\n\n", 1)[0]
    assert "refresh-release-authority-status" in verify_release_runtime_body
    assert "$(PYTHON_BIN) scripts/verify_release_authority_runtime.py --pretty" in makefile
    assert "verify-release-authority-runtime-authoritative:" in makefile
    verify_release_runtime_authoritative_body = makefile.split("verify-release-authority-runtime-authoritative:", 1)[1].split("\n\n", 1)[0]
    assert "refresh-release-authority-status" in verify_release_runtime_authoritative_body
    assert "$(PYTHON_BIN) scripts/verify_release_authority_runtime.py --pretty --require-authoritative" in makefile
    assert "verify-release-authority:" in makefile
    assert "refresh-release-manifest:" in makefile
    assert "$(PYTHON_BIN) scripts/materialize_release_manifest.py >/dev/null" in makefile
    verify_release_authority_body = makefile.split("verify-release-authority:", 1)[1].split("\n\n", 1)[0]
    assert "refresh-release-manifest" in verify_release_authority_body
    assert "$(PYTHON_BIN) scripts/verify_release_authority.py --pretty" in makefile
    ci_gates_body = makefile.split("ci-gates:\n", 1)[1].split("\n\n", 1)[0]
    assert "$(MAKE) verify-codexea-e2e-exit-gate" in ci_gates_body
    assert "$(MAKE) verify-codexea-fleet-shim-parity" in ci_gates_body
    assert "$(MAKE) verify-local-quality-gates" in ci_gates_body
    all_local_body = makefile.split("all-local:", 1)[1].split("\n\n", 1)[0]
    assert "verify-codexea-e2e-exit-gate" in all_local_body
    assert "verify-codexea-fleet-shim-parity" in all_local_body
    assert "verify-local-quality-gates" in all_local_body
    operator_help_body = makefile.split("operator-help:\n", 1)[1].split("\n\n", 1)[0]
    assert "scripts/verify_codexea_e2e_exit_gate.sh" in operator_help_body
    assert "scripts/verify_codexea_fleet_shim_parity.py" in operator_help_body
    assert "scripts/verify_local_quality_gates.py" in operator_help_body


def test_hard_exit_scripts_wire_codexea_e2e_gate() -> None:
    hard_exit = (ROOT / "scripts" / "hard_exit_gates.sh").read_text(encoding="utf-8")
    runtime_hard_exit = (ROOT / "scripts" / "runtime_hard_exit_gates.sh").read_text(encoding="utf-8")

    assert "spawned CodexEA worker-lane e2e smoke gate" in hard_exit
    assert "bash scripts/verify_codexea_e2e_exit_gate.sh" in hard_exit
    assert "spawned CodexEA worker-lane e2e smoke gate" in runtime_hard_exit
    assert "bash scripts/verify_codexea_e2e_exit_gate.sh" in runtime_hard_exit


def test_smoke_help_includes_current_fleet_parity_verifier() -> None:
    smoke_help = (ROOT / "scripts" / "smoke_help.sh").read_text(encoding="utf-8")

    assert "scripts/verify_codexea_fleet_shim_parity.py" in smoke_help
    assert "memorial" not in smoke_help.lower()


def test_hard_exit_help_mentions_codexea_e2e_gate() -> None:
    completed = subprocess.run(
        ["bash", str(ROOT / "scripts" / "hard_exit_gates.sh"), "--help"],
        cwd=ROOT,
        env={"PATH": "/usr/bin:/bin"},
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0
    assert "spawned CodexEA worker-lane e2e smoke gate" in completed.stdout
    assert completed.stderr == ""


def test_runtime_hard_exit_help_mentions_codexea_e2e_gate() -> None:
    completed = subprocess.run(
        ["bash", str(ROOT / "scripts" / "runtime_hard_exit_gates.sh"), "--help"],
        cwd=ROOT,
        env={"PATH": "/usr/bin:/bin"},
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0
    assert "spawned CodexEA worker-lane e2e smoke gate" in completed.stdout
    assert "memorial" not in completed.stdout.lower()
    assert completed.stderr == ""


def test_hard_exit_rejects_unknown_args() -> None:
    completed = subprocess.run(
        ["bash", str(ROOT / "scripts" / "hard_exit_gates.sh"), "--bogus"],
        cwd=ROOT,
        env={"PATH": "/usr/bin:/bin"},
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 2
    assert completed.stdout == ""
    assert "Unknown arguments: --bogus" in completed.stderr


def test_runtime_hard_exit_rejects_unknown_args() -> None:
    completed = subprocess.run(
        ["bash", str(ROOT / "scripts" / "runtime_hard_exit_gates.sh"), "--bogus"],
        cwd=ROOT,
        env={"PATH": "/usr/bin:/bin"},
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 2
    assert completed.stdout == ""
    assert "Unknown arguments: --bogus" in completed.stderr


def test_local_quality_gate_reports_codexea_e2e_timeout(monkeypatch) -> None:
    module = _load_script("verify_local_quality_gates")

    def fake_run(command: list[str], *, env=None, timeout_seconds=None):
        if command[:2] == ["bash", str(module.CODEXEA_E2E_EXIT_GATE)]:
            return {
                "returncode": 124,
                "output": "Command timed out after 3s",
                "timed_out": True,
                "timeout_seconds": 3,
            }
        return {
            "returncode": 0,
            "output": "",
            "timed_out": False,
            "timeout_seconds": timeout_seconds,
        }

    monkeypatch.setattr(module, "_run", fake_run)
    monkeypatch.setattr(module, "CODEXEA_E2E_EXIT_GATE_TIMEOUT_SECONDS", 3)
    monkeypatch.setattr(module, "CODEXEA_E2E_EXIT_GATE_SUPERVISOR_GRACE_SECONDS", 9)

    result = module.verify()

    assert result["status"] == "fail"
    assert "codexea_e2e_exit_gate_failed" in result["issues"]
    details = dict(result["details"])
    assert details["codexea_e2e_exit_gate_timeout_seconds"] == 3
    assert details["codexea_e2e_exit_gate_supervisor_grace_seconds"] == 9
    gate_result = dict(details["codexea_e2e_exit_gate_result"])
    assert gate_result["status"] == "fail"
    assert gate_result["timed_out"] is True
    assert gate_result["timeout_seconds"] == 3
    assert "timed out after 3s" in gate_result["output"]


def test_codexea_e2e_exit_gate_script_rejects_invalid_timeout_env() -> None:
    completed = subprocess.run(
        ["bash", str(ROOT / "scripts" / "verify_codexea_e2e_exit_gate.sh")],
        cwd=ROOT,
        env={"PATH": "/usr/bin:/bin", "CODEXEA_E2E_EXIT_GATE_TIMEOUT_SECONDS": "bad"},
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 2
    assert completed.stdout == ""
    assert "Invalid CODEXEA_E2E_EXIT_GATE_TIMEOUT_SECONDS: bad" in completed.stderr


def test_codexea_e2e_exit_gate_script_help_mentions_timeout_control() -> None:
    completed = subprocess.run(
        ["bash", str(ROOT / "scripts" / "verify_codexea_e2e_exit_gate.sh"), "--help"],
        cwd=ROOT,
        env={"PATH": "/usr/bin:/bin"},
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0
    assert "CODEXEA_E2E_EXIT_GATE_TIMEOUT_SECONDS" in completed.stdout
    assert "CODEXEA_E2E_LIVE_PROMPT" in completed.stdout
    assert "CODEXEA_E2E_LIVE_PROBE_COMMAND" in completed.stdout
    assert "Default: 300." in completed.stdout
    assert "installed launcher startup-status and compact-pretty status paths render" in completed.stdout
    assert "runs one live spawned `codexea easy exec`" in completed.stdout
    assert completed.stderr == ""


def test_codexea_e2e_exit_gate_script_help_ignores_invalid_timeout_env() -> None:
    completed = subprocess.run(
        ["bash", str(ROOT / "scripts" / "verify_codexea_e2e_exit_gate.sh"), "--help"],
        cwd=ROOT,
        env={
            "PATH": "/usr/bin:/bin",
            "CODEXEA_E2E_EXIT_GATE_TIMEOUT_SECONDS": "bad",
        },
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0
    assert "CODEXEA_E2E_EXIT_GATE_TIMEOUT_SECONDS" in completed.stdout
    assert "CODEXEA_E2E_LIVE_PROMPT" in completed.stdout
    assert "CODEXEA_E2E_LIVE_PROBE_COMMAND" in completed.stdout
    assert "Default: 300." in completed.stdout
    assert "installed launcher startup-status and compact-pretty status paths render" in completed.stdout
    assert completed.stderr == ""


def test_codexea_e2e_exit_gate_script_rejects_unknown_args() -> None:
    completed = subprocess.run(
        ["bash", str(ROOT / "scripts" / "verify_codexea_e2e_exit_gate.sh"), "--bogus"],
        cwd=ROOT,
        env={"PATH": "/usr/bin:/bin"},
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 2
    assert completed.stdout == ""
    assert "Unknown arguments: --bogus" in completed.stderr


def test_codexea_e2e_exit_gate_script_times_out_stalled_child(tmp_path: Path) -> None:
    fake_python = tmp_path / "fake-python"
    fake_python.write_text(
        "\n".join(
            [
                "#!/usr/bin/env bash",
                "sleep 5",
                "exit 0",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    fake_python.chmod(0o755)

    completed = subprocess.run(
        ["bash", str(ROOT / "scripts" / "verify_codexea_e2e_exit_gate.sh")],
        cwd=ROOT,
        env={
            "PATH": "/usr/bin:/bin",
            "PYTHON_BIN": str(fake_python),
            "CODEXEA_E2E_EXIT_GATE_TIMEOUT_SECONDS": "1",
        },
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 124
    assert completed.stdout == ""
    assert "CodexEA E2E exit gate timed out after 1s." in completed.stderr


def test_codexea_e2e_exit_gate_script_fallback_branch_times_out_stalled_child(tmp_path: Path) -> None:
    fake_python = tmp_path / "fake-python"
    fake_python.write_text(
        "\n".join(
            [
                "#!/usr/bin/env bash",
                "sleep 5",
                "exit 0",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    fake_python.chmod(0o755)

    completed = subprocess.run(
        ["bash", str(ROOT / "scripts" / "verify_codexea_e2e_exit_gate.sh")],
        cwd=ROOT,
        env={
            "PATH": "/bin",
            "PYTHON_BIN": str(fake_python),
            "CODEXEA_E2E_EXIT_GATE_TIMEOUT_SECONDS": "1",
        },
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 124
    assert completed.stdout == ""
    assert "CodexEA E2E exit gate timed out after 1s." in completed.stderr


def test_codexea_e2e_exit_gate_script_fallback_branch_passes_when_child_succeeds(tmp_path: Path) -> None:
    fake_python = tmp_path / "fake-python"
    fake_python.write_text(
        "\n".join(
            [
                "#!/usr/bin/env bash",
                "cat <<'EOF'",
                "..                                                                       [100%]",
                "4 passed, 999 deselected in 0.01s",
                "EOF",
                "exit 0",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    fake_python.chmod(0o755)

    completed = subprocess.run(
        ["bash", str(ROOT / "scripts" / "verify_codexea_e2e_exit_gate.sh")],
        cwd=ROOT,
        env={
            "PATH": "/bin",
            "PYTHON_BIN": str(fake_python),
            "CODEXEA_E2E_EXIT_GATE_TIMEOUT_SECONDS": "1",
            "CODEXEA_E2E_LIVE_PROBE_COMMAND": "printf 'READY\\n'",
        },
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0
    assert "4 passed" in completed.stdout
    assert "deselected" in completed.stdout
    assert "READY" in completed.stdout
    assert completed.stderr == ""


def test_codexea_e2e_exit_gate_script_fails_when_live_probe_does_not_return_ready(tmp_path: Path) -> None:
    fake_python = tmp_path / "fake-python"
    fake_python.write_text(
        "\n".join(
            [
                "#!/usr/bin/env bash",
                "cat <<'EOF'",
                "..                                                                       [100%]",
                "4 passed, 999 deselected in 0.01s",
                "EOF",
                "exit 0",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    fake_python.chmod(0o755)

    completed = subprocess.run(
        ["bash", str(ROOT / "scripts" / "verify_codexea_e2e_exit_gate.sh")],
        cwd=ROOT,
        env={
            "PATH": "/bin",
            "PYTHON_BIN": str(fake_python),
            "CODEXEA_E2E_EXIT_GATE_TIMEOUT_SECONDS": "1",
            "CODEXEA_E2E_LIVE_PROBE_COMMAND": "printf 'NOT_READY\\n'",
        },
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 1
    assert "4 passed" not in completed.stderr
    assert "CodexEA live spawned exec probe did not return a clean READY closeout." in completed.stderr
    assert "NOT_READY" in completed.stderr


def test_local_quality_gate_env_parser_fails_structurally_for_invalid_timeout_values(monkeypatch) -> None:
    module = _load_script_with_env(
        "verify_local_quality_gates",
        monkeypatch,
        CODEXEA_E2E_EXIT_GATE_TIMEOUT_SECONDS="bad",
        CODEXEA_E2E_EXIT_GATE_SUPERVISOR_GRACE_SECONDS="also-bad",
    )

    result = module.verify()

    assert result["status"] == "fail"
    assert "codexea_e2e_exit_gate_timeout_seconds_invalid" in result["issues"]
    assert "codexea_e2e_exit_gate_supervisor_grace_seconds_invalid" in result["issues"]
    details = dict(result["details"])
    assert details["codexea_e2e_exit_gate_timeout_seconds"] == 300
    assert details["codexea_e2e_exit_gate_timeout_seconds_valid"] is False
    assert details["codexea_e2e_exit_gate_timeout_seconds_raw"] == "bad"
    assert details["codexea_e2e_exit_gate_supervisor_grace_seconds"] == 30
    assert details["codexea_e2e_exit_gate_supervisor_grace_seconds_valid"] is False
    assert details["codexea_e2e_exit_gate_supervisor_grace_seconds_raw"] == "also-bad"


def test_local_quality_gate_env_parser_fails_for_non_positive_timeout_values(monkeypatch) -> None:
    module = _load_script_with_env(
        "verify_local_quality_gates",
        monkeypatch,
        CODEXEA_E2E_EXIT_GATE_TIMEOUT_SECONDS="0",
        CODEXEA_E2E_EXIT_GATE_SUPERVISOR_GRACE_SECONDS="-1",
    )

    result = module.verify()

    assert result["status"] == "fail"
    assert "codexea_e2e_exit_gate_timeout_seconds_invalid" in result["issues"]
    assert "codexea_e2e_exit_gate_supervisor_grace_seconds_invalid" in result["issues"]
    details = dict(result["details"])
    assert details["codexea_e2e_exit_gate_timeout_seconds"] == 300
    assert details["codexea_e2e_exit_gate_timeout_seconds_valid"] is False
    assert details["codexea_e2e_exit_gate_timeout_seconds_raw"] == "0"
    assert details["codexea_e2e_exit_gate_supervisor_grace_seconds"] == 30
    assert details["codexea_e2e_exit_gate_supervisor_grace_seconds_valid"] is False
    assert details["codexea_e2e_exit_gate_supervisor_grace_seconds_raw"] == "-1"


def test_local_quality_gate_env_parser_fails_for_fractional_timeout_values(monkeypatch) -> None:
    module = _load_script_with_env(
        "verify_local_quality_gates",
        monkeypatch,
        CODEXEA_E2E_EXIT_GATE_TIMEOUT_SECONDS="1.5",
        CODEXEA_E2E_EXIT_GATE_SUPERVISOR_GRACE_SECONDS="5.9",
    )

    result = module.verify()

    assert result["status"] == "fail"
    assert "codexea_e2e_exit_gate_timeout_seconds_invalid" in result["issues"]
    assert "codexea_e2e_exit_gate_supervisor_grace_seconds_invalid" in result["issues"]
    details = dict(result["details"])
    assert details["codexea_e2e_exit_gate_timeout_seconds"] == 300
    assert details["codexea_e2e_exit_gate_timeout_seconds_valid"] is False
    assert details["codexea_e2e_exit_gate_timeout_seconds_raw"] == "1.5"
    assert details["codexea_e2e_exit_gate_supervisor_grace_seconds"] == 30
    assert details["codexea_e2e_exit_gate_supervisor_grace_seconds_valid"] is False
    assert details["codexea_e2e_exit_gate_supervisor_grace_seconds_raw"] == "5.9"


def test_local_quality_gate_invalid_timeout_env_fails_before_running_subprocesses(monkeypatch) -> None:
    module = _load_script_with_env(
        "verify_local_quality_gates",
        monkeypatch,
        CODEXEA_E2E_EXIT_GATE_TIMEOUT_SECONDS="bad",
    )

    def fail_run(*args, **kwargs):
        raise AssertionError("subprocess execution should be skipped when timeout env is invalid")

    monkeypatch.setattr(module, "_run", fail_run)

    result = module.verify()

    assert result["status"] == "fail"
    assert "codexea_e2e_exit_gate_timeout_seconds_invalid" in result["issues"]
    assert "codexea_e2e_exit_gate_result" not in dict(result["details"])


def test_local_quality_gate_cli_fails_structurally_for_invalid_timeout_values() -> None:
    completed = subprocess.run(
        ["python3", str(ROOT / "scripts" / "verify_local_quality_gates.py")],
        cwd=ROOT,
        env={
            "PATH": "/usr/bin:/bin",
            "CODEXEA_E2E_EXIT_GATE_TIMEOUT_SECONDS": "bad",
            "CODEXEA_E2E_EXIT_GATE_SUPERVISOR_GRACE_SECONDS": "also-bad",
        },
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 1
    assert completed.stderr == ""
    payload = json.loads(completed.stdout)
    assert payload["status"] == "fail"
    assert "codexea_e2e_exit_gate_timeout_seconds_invalid" in payload["issues"]
    assert "codexea_e2e_exit_gate_supervisor_grace_seconds_invalid" in payload["issues"]
    details = dict(payload["details"])
    assert details["codexea_e2e_exit_gate_timeout_seconds"] == 300
    assert details["codexea_e2e_exit_gate_timeout_seconds_valid"] is False
    assert details["codexea_e2e_exit_gate_timeout_seconds_raw"] == "bad"
    assert details["codexea_e2e_exit_gate_supervisor_grace_seconds"] == 30
    assert details["codexea_e2e_exit_gate_supervisor_grace_seconds_valid"] is False
    assert details["codexea_e2e_exit_gate_supervisor_grace_seconds_raw"] == "also-bad"


def test_local_quality_gate_cli_help_describes_codexea_gate_controls() -> None:
    completed = subprocess.run(
        ["python3", str(ROOT / "scripts" / "verify_local_quality_gates.py"), "--help"],
        cwd=ROOT,
        env={"PATH": "/usr/bin:/bin"},
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0
    assert "Runs the local quality verifier, including the spawned CodexEA" in completed.stdout
    assert "CODEXEA_E2E_EXIT_GATE_TIMEOUT_SECONDS" in completed.stdout
    assert "CODEXEA_E2E_EXIT_GATE_SUPERVISOR_GRACE_SECONDS" in completed.stdout
    assert completed.stderr == ""


def test_local_quality_gate_cli_help_ignores_invalid_timeout_env() -> None:
    completed = subprocess.run(
        ["python3", str(ROOT / "scripts" / "verify_local_quality_gates.py"), "--help"],
        cwd=ROOT,
        env={
            "PATH": "/usr/bin:/bin",
            "CODEXEA_E2E_EXIT_GATE_TIMEOUT_SECONDS": "bad",
            "CODEXEA_E2E_EXIT_GATE_SUPERVISOR_GRACE_SECONDS": "also-bad",
        },
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0
    assert "Runs the local quality verifier, including the spawned CodexEA" in completed.stdout
    assert "CODEXEA_E2E_EXIT_GATE_TIMEOUT_SECONDS" in completed.stdout
    assert "CODEXEA_E2E_EXIT_GATE_SUPERVISOR_GRACE_SECONDS" in completed.stdout
    assert completed.stderr == ""


def test_local_quality_gate_cli_rejects_unknown_args() -> None:
    completed = subprocess.run(
        ["python3", str(ROOT / "scripts" / "verify_local_quality_gates.py"), "--bogus"],
        cwd=ROOT,
        env={"PATH": "/usr/bin:/bin"},
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 2
    assert completed.stdout == ""
    assert "Unknown arguments: --bogus" in completed.stderr


def test_make_verify_local_quality_gates_fails_structurally_for_invalid_timeout_values() -> None:
    completed = subprocess.run(
        ["make", "-C", str(ROOT), "verify-local-quality-gates"],
        cwd=ROOT,
        env={
            "PATH": "/usr/bin:/bin",
            "CODEXEA_E2E_EXIT_GATE_TIMEOUT_SECONDS": "bad",
            "CODEXEA_E2E_EXIT_GATE_SUPERVISOR_GRACE_SECONDS": "also-bad",
        },
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 2
    assert ".venv/bin/python scripts/verify_local_quality_gates.py" in completed.stdout
    assert '"status": "fail"' in completed.stdout
    assert "codexea_e2e_exit_gate_timeout_seconds_invalid" in completed.stdout
    assert "codexea_e2e_exit_gate_supervisor_grace_seconds_invalid" in completed.stdout
    assert "Makefile:" in completed.stderr


def test_make_verify_local_quality_gates_passes_in_healthy_path() -> None:
    completed = subprocess.run(
        ["make", "-C", str(ROOT), "verify-local-quality-gates"],
        cwd=ROOT,
        env={"PATH": "/usr/bin:/bin"},
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0
    assert ".venv/bin/python scripts/verify_local_quality_gates.py" in completed.stdout
    assert '"codexea_fleet_shim_parity_result"' in completed.stdout
    assert '"status": "pass"' in completed.stdout
    assert '"codexea_e2e_exit_gate_result"' in completed.stdout
    assert '"timed_out": false' in completed.stdout
    assert completed.stderr == ""


def test_make_verify_codexea_e2e_exit_gate_fails_for_invalid_timeout_values() -> None:
    completed = subprocess.run(
        ["make", "-C", str(ROOT), "verify-codexea-e2e-exit-gate"],
        cwd=ROOT,
        env={
            "PATH": "/usr/bin:/bin",
            "CODEXEA_E2E_EXIT_GATE_TIMEOUT_SECONDS": "bad",
        },
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 2
    assert "bash scripts/verify_codexea_e2e_exit_gate.sh" in completed.stdout
    assert "Invalid CODEXEA_E2E_EXIT_GATE_TIMEOUT_SECONDS: bad" in completed.stderr


def test_make_verify_codexea_e2e_exit_gate_passes_in_healthy_path() -> None:
    completed = subprocess.run(
        ["make", "-C", str(ROOT), "verify-codexea-e2e-exit-gate"],
        cwd=ROOT,
        env={"PATH": "/usr/bin:/bin"},
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0
    assert "bash scripts/verify_codexea_e2e_exit_gate.sh" in completed.stdout
    assert "passed" in completed.stdout
    assert "deselected" in completed.stdout
    assert completed.stderr == ""


def test_make_ci_gates_dry_run_includes_both_codexea_gate_layers() -> None:
    completed = subprocess.run(
        ["make", "-C", str(ROOT), "-n", "ci-gates"],
        cwd=ROOT,
        env={"PATH": "/usr/bin:/bin"},
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0
    assert "make verify-codexea-e2e-exit-gate" in completed.stdout
    assert "make verify-codexea-fleet-shim-parity" in completed.stdout
    assert "make verify-local-quality-gates" in completed.stdout
    assert completed.stderr == ""


def test_make_all_local_dry_run_includes_both_codexea_gate_layers() -> None:
    completed = subprocess.run(
        ["make", "-C", str(ROOT), "-n", "all-local"],
        cwd=ROOT,
        env={"PATH": "/usr/bin:/bin"},
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0
    assert "bash scripts/verify_codexea_e2e_exit_gate.sh" in completed.stdout
    assert ".venv/bin/python scripts/verify_codexea_fleet_shim_parity.py" in completed.stdout
    assert ".venv/bin/python scripts/verify_local_quality_gates.py" in completed.stdout
    assert completed.stderr == ""


def test_make_operator_help_dry_run_mentions_codexea_gate_script() -> None:
    completed = subprocess.run(
        ["make", "-C", str(ROOT), "-n", "operator-help"],
        cwd=ROOT,
        env={"PATH": "/usr/bin:/bin"},
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0
    assert "scripts/verify_codexea_e2e_exit_gate.sh" in completed.stdout
    assert "scripts/verify_codexea_fleet_shim_parity.py" in completed.stdout
    assert "scripts/verify_local_quality_gates.py" in completed.stdout
    assert "*.py) .venv/bin/python $s --help" in completed.stdout
    assert "*) bash $s --help" in completed.stdout
    assert completed.stderr == ""
